from sqlalchemy import or_
import os
import re
import jwt
import time
from urllib.parse import urlencode, parse_qs
from oauth_client import oauth
from flask import send_from_directory, url_for, current_app
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session, render_template, current_app, flash, redirect
from types import SimpleNamespace
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash 
from pathlib import Path
import uuid
from models import db, User, UserProfile

WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://localhost:8000")
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
AVATAR_DIR = "uploads/avatars"  

bp = Blueprint("auth", __name__, url_prefix="/auth")
SECRET = os.getenv("JWT_SECRET", "devsecret")  

def normalize_email(s: str | None) -> str | None:
    if not s:
        return None
    return s.strip().lower()

def normalize_phone(s: str | None) -> str | None:
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if digits.startswith("84"):
        digits = "0" + digits[2:]
    elif digits.startswith("084"):
        digits = "0" + digits[3:]
    return digits

def _make_token(u: User) -> str:
    payload = {
        "sub": u.id,
        "username": u.username,
        "role": u.role,
        "approved": u.approved,
        "locked": u.locked,
        "exp": datetime.utcnow() + timedelta(hours=6),
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")

def _require_admin():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, ({"error": "no_token"}, 401)
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except Exception:
        return None, ({"error": "invalid_token"}, 401)
    if payload.get("role") != "admin":
        return None, ({"error": "forbidden"}, 403)
    return payload, None

def _require_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, ({"error": "no_token"}, 401)
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except Exception:
        return None, ({"error": "invalid_token"}, 401)
    u = User.query.get(payload.get("sub"))
    if not u:
        return None, ({"error": "user_not_found"}, 404)
    if u.locked:
        return None, ({"error": "locked"}, 403)
    if u.role != "admin" and not u.approved:
        return None, ({"error": "not_approved"}, 403)
    return u, None

def _save_avatar(file_storage, username: str | None = None):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None, "no_file"

    fname = secure_filename(file_storage.filename)
    if "." not in fname:
        return None, "bad_filename"

    ext = fname.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return None, "unsupported_type"

    dest_dir = Path(current_app.static_folder) / AVATAR_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    # If a username is provided, prefer a predictable filename based on it.
    # Use a secure version and append a short timestamp if the file exists to avoid collisions.
    if username:
        safe_user = secure_filename(username) or uuid.uuid4().hex
        base_name = f"{safe_user}.{ext}"
        target = dest_dir / base_name
        if target.exists():
            # append timestamp to avoid overwriting
            ts = int(time.time())
            base_name = f"{safe_user}_{ts}.{ext}"
            target = dest_dir / base_name
        file_storage.save(target)
        return base_name, None

    # Fallback: random UUID filename
    new_name = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(dest_dir / new_name)
    return new_name, None

@bp.get("/")
def health():
    return {"service": "auth", "status": "ok", "prefix": "/auth"}

@bp.post("/register")
def register():
    d = request.get_json(force=True) if request.is_json else request.form
    username = (d.get("username") or "").strip()
    email = normalize_email(d.get("email"))
    phone = normalize_phone(d.get("phone"))
    password = d.get("password") or ""
    if not username or not email or not password:
        return {
            "error": "missing_fields",
            "hint": "username, email, password required",
        }, 400
    conds = [User.username == username, User.email == email]
    if phone:
        conds.append(User.phone == phone)
    existed = User.query.filter(or_(*conds)).first()
    if existed:
        if existed.username == username:
            return {"error": "username_exists"}, 409
        if existed.email == email:
            return {"error": "email_exists"}, 409
        if phone and existed.phone == phone:
            return {"error": "phone_exists"}, 409
    u = User(
        username=username,
        email=email,
        password=generate_password_hash(password),
        role="member",
        approved=False, 
        locked=False,
        phone=phone,
    )
    db.session.add(u)
    db.session.commit()
    return {"id": u.id, "username": u.username}, 201


@bp.get("/users/by-id/<int:user_id>")
def get_user_by_id(user_id: int):
    """
    Returns public user information by user ID.
    This is intended for cross-service communication.
    """
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "user_not_found"}), 404

    profile = UserProfile.query.filter_by(user_id=user.id).first()

    avatar_url = None
    # New avatar system via UserProfile
    if profile and profile.avatar:
        avatar_url = url_for('static', filename=f'{AVATAR_DIR}/{profile.avatar}', _external=True)
    
    # Fallback to old avatar system if new profile avatar not found
    if not avatar_url:
        safe_user = secure_filename(user.username)
        for ext in ALLOWED_IMAGE_EXTS:
            avatar_path_str = f"{AVATAR_DIR}/{safe_user}.{ext}"
            if (Path(current_app.static_folder) / avatar_path_str).exists():
                avatar_url = url_for('static', filename=avatar_path_str, _external=True)
                break

    return jsonify({
        "id": user.id,
        "username": user.username,
        "full_name": profile.full_name if profile else user.username,
        "avatar_url": avatar_url
    })


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    data = request.get_json(force=True) if request.is_json else request.form
    identifier = (data.get("username") or data.get("identifier") or data.get("email") or "").strip()
    password = data.get("password") or ""

    if not identifier or not password:
        if request.is_json:
            return {"error": "missing_fields"}, 400
        flash("Vui lòng nhập đầy đủ thông tin!", "error")
        return redirect(url_for("auth.login"))

    by_email = "@" in identifier
    by_phone = identifier.isdigit()

    if by_email:
        u = User.query.filter_by(email=identifier.lower()).first()
    elif by_phone:
        u = User.query.filter_by(phone=normalize_phone(identifier)).first()
    else:
        u = User.query.filter_by(username=identifier).first()

    if not u or not check_password_hash(u.password, password):
        if request.is_json:
            return {"error": "invalid_credentials"}, 401
        flash("Tên đăng nhập hoặc mật khẩu không đúng!", "error")
        return redirect(url_for("auth.login"))

    if u.locked:
        if request.is_json:
            return {"error": "locked"}, 403
        flash("Tài khoản của bạn đã bị khóa!", "error")
        return redirect(url_for("auth.login"))

    if u.role != "admin" and not u.approved:
        if request.is_json:
            return {"error": "not_approved"}, 403
        flash("Tài khoản chưa được admin duyệt!", "error")
        return redirect(url_for("auth.login"))

    token = _make_token(u)

    if request.is_json:
        return {"access_token": token, "role": u.role}

    session["user_id"] = u.id
    session["username"] = u.username
    session["role"] = u.role
    flash("Đăng nhập thành công!", "success")

    if u.role == "admin":
        return redirect(url_for("auth.admin_list_users"))
    else:
        return redirect(url_for("auth.profile_page"))


@bp.get("/login_page")
def login_page():
    return render_template("login.html")


@bp.get("/me")
def me():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return {"error": "no_token"}, 401
    try:
        payload = jwt.decode(auth.split(" ", 1)[1], SECRET, algorithms=["HS256"])
    except Exception:
        return {"error": "invalid_token"}, 401
    return payload

@bp.get("/admin/users")
def admin_list_users():
    _, err = _require_admin()
    if err:
        return err
    # load users with related profile so admin view can include phone, full_name and avatar
    users = User.query.order_by(User.id.desc()).all()
    data = []
    for u in users:
        prof = None
        try:
            prof = u.profile
        except Exception:
            prof = None
        data.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "phone": u.phone,
            "role": u.role,
            "is_admin": (u.role == "admin"),
            "approved": u.approved,
            "locked": u.locked,
            "created_at": u.created_at.isoformat(),
            "full_name": (prof.full_name if prof else None),
            "avatar_url": (prof.avatar_url if prof else None),
        })
    return {"data": data}


@bp.patch("/users/<int:uid>/status")
def update_status(uid: int):
    _, err = _require_admin()
    if err:
        return err
    d = request.get_json(force=True)
    status = (d.get("status") or "pending").lower()
    u = User.query.get_or_404(uid)
    if status == "approved":
        u.approved, u.locked = True, False
    elif status == "locked":
        u.approved, u.locked = False, True
    else:
        u.approved, u.locked = False, False
    db.session.commit()
    return {"ok": True, "status": status}

@bp.get("/profile")
def get_profile():
    u, err = _require_user()
    if err:
        return err
    p = UserProfile.query.filter_by(user_id=u.id).first()
    if not p:
        p = UserProfile(user_id=u.id)
        db.session.add(p)
        db.session.commit()
    return {"user": u.to_dict_basic(), "profile": p.to_dict()}


@bp.get('/users/<username>')
def public_user(username: str):
    """Public endpoint: return minimal public info for a username.
    This is intentionally permissive for local/dev use so gateway/product pages
    can display seller contact info without admin token. Returns email/phone
    when present.
    """
    u = User.query.filter_by(username=username).first()
    if not u:
        return {"error": "not_found"}, 404
    prof = None
    try:
        prof = u.profile
    except Exception:
        prof = None
    return {
        "id": u.id,
        "username": u.username,
        "full_name": prof.full_name if prof and prof.full_name else u.username,
        "email": u.email,
        "phone": u.phone,
        "avatar_url": prof.avatar_url if prof else None,
    }



@bp.put("/profile")
def update_profile():
    u, err = _require_user()
    if err:
        return err
    d = request.get_json(force=True)
    p = UserProfile.query.filter_by(user_id=u.id).first()
    if not p:
        p = UserProfile(user_id=u.id)
        db.session.add(p)
    if "full_name" in d:  p.full_name = d.get("full_name") or None
    if "address" in d:    p.address   = d.get("address") or None
    if "gender" in d:     p.gender    = d.get("gender") or None
    if "birthdate" in d:
        val = d.get("birthdate")
        if val:
            try:
                p.birthdate = datetime.strptime(val, "%Y-%m-%d").date()
            except ValueError:
                return {"error": "invalid_birthdate_format"}, 400
        else:
            p.birthdate = None
    if "phone" in d:
        u.phone = d.get("phone") or None

    db.session.commit()
    return {"ok": True, "profile": p.to_dict(), "user": u.to_dict_basic()}

@bp.post("/profile")  
def update_profile_form():
    u, err = _require_user()
    if err:
        return err
    p = UserProfile.query.filter_by(user_id=u.id).first()
    if not p:
        p = UserProfile(user_id=u.id)
        db.session.add(p)
    p.full_name = request.form.get("full_name") or p.full_name
    p.address = request.form.get("address") or p.address
    p.vehicle_info = request.form.get("vehicle_info") or p.vehicle_info
    p.battery_info = request.form.get("battery_info") or p.battery_info
    p.gender = request.form.get("gender") or p.gender
    birthdate = request.form.get("birthdate")
    if birthdate:
        try:
            from datetime import datetime
            p.birthdate = datetime.strptime(birthdate, "%Y-%m-%d").date()
        except ValueError:
            pass  
    phone = request.form.get("phone")
    if phone is not None:
        from re import sub
        digits = sub(r"\D", "", phone)
        if digits.startswith("84"):
            digits = "0" + digits[2:]
        if digits.startswith("084"):
            digits = "0" + digits[3:]
        u.phone = digits or None
    file = request.files.get("avatar")
    if file and file.filename:
        filename, e = _save_avatar(file, username=u.username if u else None)
        if not e:
            p.avatar_url = filename  
    db.session.commit()
    return {
        "ok": True,
        "profile": p.to_dict(),
        "user": u.to_dict_basic(),
        # QUAN TRỌNG: trả về URL /auth/avatar/<name>, không phải /static/...
        "avatar_src": url_for("auth.get_avatar", name=p.avatar_url) if p.avatar_url else None,
    }

@bp.get("/profile-page", endpoint="profile_html")
def profile_html():
    return render_template("profile.html")  

@bp.get("/profile/view") 
def profile_page():
    user_id = session.get("user_id")
    user = User.query.get(user_id)
    prof = UserProfile.query.filter_by(user_id=user_id).first()
    if prof is None:
        prof = SimpleNamespace(
            full_name="",
            phone="",
            address="",
            gender="",
            birthdate="",
            vehicle_info="",
            battery_info="",
            avatar_url="",
        )
    raw = getattr(prof, "avatar_url", "") or ""
    if raw.startswith(("http://", "https://", "/")):
        avatar_src = raw
    elif raw:
        avatar_src = url_for("static", filename=f"{AVATAR_DIR}/{raw}")
    else:
        avatar_src = url_for("static", filename="img/avatar-placeholder.png")
    return render_template("profile.html", user=user, profile=prof, avatar_src=avatar_src)

@bp.get("/avatar/<path:name>")
def get_avatar(name):
    avatar_dir = Path(current_app.static_folder) / AVATAR_DIR
    file_path = avatar_dir / name
    if not file_path.exists():
        return {"error": "not_found"}, 404
    return send_from_directory(avatar_dir, name)

@bp.get("/login/google")
def login_google():
    redirect_uri = url_for("auth.callback_google", _external=True)
    client = oauth.create_client("google")
    return client.authorize_redirect(redirect_uri)

@bp.get("/callback/google")
def callback_google():
    client = oauth.create_client("google")
    token = client.authorize_access_token()  # exchange code -> token
    info = client.get("userinfo").json()     # {id, email, name, picture, ...}

    email = normalize_email(info.get("email"))
    sub   = info.get("id") or info.get("sub")
    name  = info.get("name") or (email or "").split("@")[0]
    avatar = info.get("picture") or ""

    # Tạo hoặc lấy user
    u = User.query.filter(
        or_(User.email == email, User.username == email.split("@")[0])
    ).first()
    if not u:
        u = User(
            username=(email or f"gg_{sub}")[:30],
            email=email,
            password=generate_password_hash(os.urandom(8).hex()),
            role="member",
            approved=True,   # xã hội: có thể cho auto-approve
            locked=False,
            phone=None,
        )
        db.session.add(u); db.session.commit()

        # tạo profile kèm avatar (nếu muốn)
        p = UserProfile(user_id=u.id, full_name=name or u.username)
        if avatar:
            p.avatar_url = avatar
        db.session.add(p); db.session.commit()

    # cấp JWT
    token_jwt = _make_token(u)
    # Redirect về web (gateway/UI) với token
    return redirect(f"{WEB_BASE_URL}/auth/callback?provider=google&token={token_jwt}")

@bp.get("/login/facebook")
def login_facebook():
    redirect_uri = url_for("auth.callback_facebook", _external=True)
    client = oauth.create_client("facebook")
    return client.authorize_redirect(redirect_uri)

@bp.get("/callback/facebook")
def callback_facebook():
    client = oauth.create_client("facebook")
    token = client.authorize_access_token()
    me = client.get("me?fields=id,name,email,picture{url}").json()

    email = normalize_email(me.get("email"))
    sub   = me.get("id")
    name  = me.get("name")
    avatar = ((me.get("picture") or {}).get("data") or {}).get("url")

    u = User.query.filter(
        or_(User.email == email, User.username == (email or f"fb_{sub}").split("@")[0])
    ).first()
    if not u:
        u = User(
            username=(email or f"fb_{sub}")[:30],
            email=email,
            password=generate_password_hash(os.urandom(8).hex()),
            role="member",
            approved=True,
            locked=False,
        )
        db.session.add(u); db.session.commit()
        p = UserProfile(user_id=u.id, full_name=name or u.username)
        if avatar:
            p.avatar_url = avatar
        db.session.add(p); db.session.commit()

    token_jwt = _make_token(u)
    return redirect(f"{WEB_BASE_URL}/auth/callback?provider=facebook&token={token_jwt}")