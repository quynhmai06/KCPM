# listing-service/routes.py
from flask import Blueprint, request, jsonify
from models import db, Product, ProductStatus, ItemType, BlockedUser
from sqlalchemy import or_
import os, jwt, json, requests
from datetime import datetime


bp = Blueprint("listing", __name__, url_prefix="/listings")
JWT_SECRET = os.getenv("JWT_SECRET", "devsecret")
STATIC_UPLOAD_PREFIX = "/static/uploads/"
AUTH_URL = os.getenv("AUTH_URL", "http://auth_service:5001")

# ---------- Auth helpers ----------
def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"verify_sub": False})
    except Exception:
        return None

def require_auth():
    u = current_user()
    if not u:
        return None, (jsonify(error="Unauthorized"), 401)
    return u, None

def require_admin():
    u = current_user()
    if not u or str(u.get("role", "")).lower() != "admin":
        return None, (jsonify(error="Forbidden"), 403)
    return u, None

# ---------- Image path helpers ----------
def _norm_img(url: str | None) -> str | None:
    """Chuẩn hóa URL ảnh để client hiển thị đúng."""
    if not url:
        return None
    url = url.strip()
    # Nếu đã có http/https hoặc / đầu => giữ nguyên
    if url.lower().startswith(("http://", "https://", "/")):
        return url
    # Nếu chỉ là tên file (không có prefix) => thêm /static/uploads/
    return STATIC_UPLOAD_PREFIX + url

def _strip_prefix(u: str | None) -> str | None:
    """Loại bỏ prefix /static/uploads/ khi lưu DB."""
    if not u:
        return None
    u = u.strip()
    if u.startswith(STATIC_UPLOAD_PREFIX):
        return u[len(STATIC_UPLOAD_PREFIX):]
    if u.startswith("/uploads/"):
        return u[len("/uploads/"):]
    if u.startswith("uploads/"):
        return u[len("uploads/"):]
    return u

# ---------- Utils ----------
def _resolve_owner_id(username: str | None) -> int | None:
    """Resolve username to user ID via auth-service."""
    if not username:
        return None
    try:
        r = requests.get(f"{AUTH_URL}/auth/users/{username}", timeout=3)
        if r.ok:
            data = r.json()
            return data.get("id")
    except Exception:
        pass
    return None

def to_json(p: Product):
    """Chuyển Product sang dict JSON trả về cho client."""
    sub_urls = []
    try:
        sub_urls = json.loads(p.sub_image_urls or "[]")
        if not isinstance(sub_urls, list):
            sub_urls = []
    except Exception:
        sub_urls = []

    owner_id = _resolve_owner_id(p.owner)

    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "brand": p.brand,
        "province": p.province,
        "year": p.year,
        "mileage": p.mileage,
        "battery_capacity": p.battery_capacity,
        "owner": p.owner,
        "owner_id": owner_id,
        "main_image_url": _norm_img(p.main_image_url),
        "sub_image_urls": [_norm_img(u) for u in sub_urls],
        "approved": bool(p.approved),
        "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "approved_by": p.approved_by,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "status": p.status.value if p.status else "pending",
        "verified": bool(p.verified),
        "moderation_notes": p.moderation_notes,
        "sold": bool(getattr(p, 'sold', False)),
    }

def parse_int(v, default=None, minv=None, maxv=None):
    if v is None or v == "":
        return default
    try:
        n = int(v)
        if minv is not None and n < minv:
            return default
        if maxv is not None and n > maxv:
            return default
        return n
    except:
        return default

# ---------- Endpoints ----------
@bp.get("/")
def list_products():
    q = Product.query

    # --- search ---
    kw = (request.args.get("q") or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

    # --- filters ---
    brand = request.args.get("brand")
    if brand:
        q = q.filter(Product.brand == brand)

    province = request.args.get("province")
    if province:
        q = q.filter(Product.province == province)

    owner = request.args.get("owner")
    if owner:
        q = q.filter(Product.owner == owner)

    approved = request.args.get("approved")
    if approved is not None:
        q = q.filter(Product.approved == (approved in ["1", "true", "True"]))

    min_price = parse_int(request.args.get("min_price"), None, 0)
    if min_price is not None:
        q = q.filter(Product.price >= min_price)

    max_price = parse_int(request.args.get("max_price"), None, 0)
    if max_price is not None:
        q = q.filter(Product.price <= max_price)

    year_from = parse_int(request.args.get("year_from"))
    if year_from is not None:
        q = q.filter(Product.year >= year_from)

    year_to = parse_int(request.args.get("year_to"))
    if year_to is not None:
        q = q.filter(Product.year <= year_to)

    mileage_max = parse_int(request.args.get("mileage_max"))
    if mileage_max is not None:
        q = q.filter(Product.mileage <= mileage_max)

    status = request.args.get("status")
    if status in {"pending", "approved", "rejected", "spam"}:
        q = q.filter(Product.status == ProductStatus(status))

    verified = request.args.get("verified")
    if verified in ["1", "true", "True", "0", "false", "False"]:
        q = q.filter(Product.verified == (verified.lower() in ["1", "true"]))

    item_type = (request.args.get("item_type") or "").strip().lower()
    if item_type in {"vehicle", "battery"}:
        q = q.filter(Product.item_type == ItemType(item_type))

    # Filter out sold products by default (unless explicitly requested via ?include_sold=1)
    include_sold = request.args.get("include_sold")
    if include_sold not in ["1", "true", "True"]:
        q = q.filter(Product.sold == False)

    sort = request.args.get("sort", "created_desc")
    if sort == "created_asc":
        q = q.order_by(Product.created_at.asc())
    elif sort == "price_asc":
        q = q.order_by(Product.price.asc())
    elif sort == "price_desc":
        q = q.order_by(Product.price.desc())
    else:
        q = q.order_by(Product.created_at.desc())

    page = parse_int(request.args.get("page"), 1, 1)
    per_page = parse_int(request.args.get("per_page"), 12, 1, 50)
    page_obj = q.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "items": [to_json(p) for p in page_obj.items],
        "page": page_obj.page,
        "per_page": page_obj.per_page,
        "total": page_obj.total,
        "pages": page_obj.pages
    })

@bp.post("/")
def create_product():
    user, err = require_auth()
    if err:
        return err
    if BlockedUser.query.filter_by(username=user["username"]).first():
        return jsonify(error="Tài khoản của bạn đã bị chặn đăng bài. Liên hệ hỗ trợ để được mở khoá."), 403


    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    price = parse_int(data.get("price"), 0, 1)
    if not name or price <= 0:
        return jsonify(error="Thiếu tên hoặc giá không hợp lệ."), 400

    year = parse_int(data.get("year"))
    mileage = parse_int(data.get("mileage"))
    sub_urls = data.get("sub_image_urls") or []
    if not isinstance(sub_urls, list):
        return jsonify(error="sub_image_urls phải là danh sách URL."), 400

    raw_item_type = (data.get("item_type") or "vehicle").strip().lower()
    if raw_item_type not in {"vehicle", "battery"}:
        raw_item_type = "vehicle"

    p = Product(
        name=name,
        description=data.get("description"),
        price=price,
        brand=data.get("brand"),
        province=data.get("province"),
        year=year,
        mileage=mileage,
        battery_capacity=data.get("battery_capacity"),
        owner=user["username"],
        item_type=ItemType(raw_item_type), 
        main_image_url=_strip_prefix(data.get("main_image_url")),
        sub_image_urls=json.dumps([_strip_prefix(u) for u in sub_urls if u]),
    )

    db.session.add(p)
    db.session.commit()
    return jsonify(id=p.id, message="Đăng tin thành công.", item=to_json(p)), 201


@bp.get("/<int:pid>")
def get_product(pid):
    p = Product.query.get_or_404(pid)
    return jsonify(to_json(p))

@bp.patch("/<int:pid>")
def update_product(pid):
    user, err = require_auth()
    if err:
        return err
    p = Product.query.get_or_404(pid)

    if user["username"] != p.owner and str(user.get("role", "")).lower() != "admin":
        return jsonify(error="Forbidden"), 403
    if p.approved and str(user.get("role", "")).lower() != "admin":
        return jsonify(error="Đã duyệt, không thể sửa."), 400

    data = request.get_json(force=True)
    if "name" in data:
        if not (data["name"] or "").strip():
            return jsonify(error="Tên không hợp lệ."), 400
        p.name = data["name"].strip()
    if "description" in data:
        p.description = data["description"]
    if "price" in data:
        val = parse_int(data["price"], None, 1)
        if val is None:
            return jsonify(error="Giá không hợp lệ."), 400
        p.price = val
    if "brand" in data:
        p.brand = data["brand"]
    if "province" in data:
        p.province = data["province"]
    if "year" in data:
        y = parse_int(data["year"])
        if y is None:
            return jsonify(error="Năm không hợp lệ."), 400
        p.year = y
    if "mileage" in data:
        m = parse_int(data["mileage"], None, 0)
        if m is None:
            return jsonify(error="Số km không hợp lệ."), 400
        p.mileage = m
    if "battery_capacity" in data:
        p.battery_capacity = data["battery_capacity"]
    if "main_image_url" in data:
        p.main_image_url = _strip_prefix(data["main_image_url"])
    if "sub_image_urls" in data:
        if not isinstance(data["sub_image_urls"], list):
            return jsonify(error="sub_image_urls phải là danh sách."), 400
        p.sub_image_urls = json.dumps([_strip_prefix(u) for u in data["sub_image_urls"] if u])

    db.session.commit()
    return jsonify(message="Đã cập nhật.", item=to_json(p))

@bp.put("/<int:pid>/approve")
def approve_product(pid):
    admin, err = require_admin()
    if err:
        return err
    p = Product.query.get_or_404(pid)
    p.approved = True
    p.approved_at = datetime.utcnow()
    p.approved_by = admin["username"]
    db.session.commit()
    return jsonify(message="Đã duyệt.", item=to_json(p))

@bp.put("/<int:pid>/unapprove")
def unapprove_product(pid):
    admin, err = require_admin()
    if err:
        return err
    p = Product.query.get_or_404(pid)
    p.approved = False
    p.approved_at = None
    p.approved_by = None
    db.session.commit()
    return jsonify(message="Đã bỏ duyệt.", item=to_json(p))

@bp.delete("/<int:pid>")
def delete_product(pid):
    user, err = require_auth()
    if err:
        return err

    p = Product.query.get_or_404(pid)

    if str(user.get("role", "")).lower() == "admin":
        db.session.delete(p)
        db.session.commit()
        return jsonify(message="Đã xoá."), 200

    if user["username"] == p.owner and not p.approved:
        db.session.delete(p)
        db.session.commit()
        return jsonify(message="Đã xoá."), 200

    return jsonify(error="Forbidden"), 403


    db.session.delete(p)
    db.session.commit()
    return jsonify(message="Đã xoá.")
@bp.put("/<int:pid>/verify")
def verify_product(pid):
    admin, err = require_admin()
    if err: return err
    p = Product.query.get_or_404(pid)
    p.verified = True
    db.session.commit()
    return jsonify(message="Verified", item=to_json(p)), 200

@bp.put("/<int:pid>/unverify")
def unverify_product(pid):
    admin, err = require_admin()
    if err: return err
    p = Product.query.get_or_404(pid)
    p.verified = False
    db.session.commit()
    return jsonify(message="Unverified", item=to_json(p)), 200
@bp.put("/<int:pid>/mark_spam")
def mark_spam(pid):
    admin, err = require_admin()
    if err: return err
    p = Product.query.get_or_404(pid)

    note = (request.get_json(silent=True) or {}).get("note")
    p.status = ProductStatus.spam
    p.approved = False
    p.approved_at = None
    p.approved_by = None
    if note:
        p.moderation_notes = ((p.moderation_notes or "") + f"\n[spam] {note}").strip()

    if not BlockedUser.query.filter_by(username=p.owner).first():
        db.session.add(BlockedUser(username=p.owner, reason=note or "spam"))

    db.session.commit()
    return jsonify(message="Đã gắn spam & chặn tài khoản đăng bài.", item=to_json(p)), 200


@bp.put("/<int:pid>/unspam")
def unspam(pid):
    admin, err = require_admin()
    if err: return err
    p = Product.query.get_or_404(pid)

    p.status = ProductStatus.pending
    db.session.commit()

    cnt = Product.query.filter(
        Product.owner == p.owner,
        Product.status == ProductStatus.spam
    ).count()
    if cnt == 0:
        BlockedUser.query.filter_by(username=p.owner).delete()
        db.session.commit()

    return jsonify(message="Đã bỏ spam. Mở khoá tài khoản nếu không còn bài spam." , item=to_json(p)), 200

@bp.put("/<int:pid>/mark_sold")
def mark_sold(pid):
    """Đánh dấu sản phẩm đã bán (gọi từ payment-service sau khi thanh toán thành công)"""
    p = Product.query.get_or_404(pid)
    p.sold = True
    db.session.commit()
    return jsonify(message="Sản phẩm đã được đánh dấu đã bán", item=to_json(p)), 200

@bp.put("/<int:pid>/mark_available")
def mark_available(pid):
    """Đánh dấu sản phẩm còn hàng (rollback nếu cần)"""
    p = Product.query.get_or_404(pid)
    p.sold = False
    db.session.commit()
    return jsonify(message="Sản phẩm đã được đánh dấu còn hàng", item=to_json(p)), 200
