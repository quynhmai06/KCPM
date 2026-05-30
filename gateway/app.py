# gateway/app.py 
from flask import Flask, render_template, redirect, url_for, request, session, flash, Response, jsonify
import os, requests, jwt, time, json, re
from functools import wraps
from werkzeug.utils import secure_filename

# ===================== Config =====================
AUTH_URL     = os.getenv("AUTH_URL",     "http://auth_service:5001")
ADMIN_URL    = os.getenv("ADMIN_URL",    "http://admin_service:5003")
LISTING_URL  = os.getenv("LISTING_URL",  "http://listing_service:5002")
SEARCH_URL   = os.getenv("SEARCH_URL",   "http://search_service:5003")
PRICING_URL  = os.getenv("PRICING_URL",  "http://pricing_service:5003")
FAVORITES_URL = os.getenv("FAVORITES_URL", "http://favorites_service:5004")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://payment_service:5003")

JWT_SECRET = os.getenv("JWT_SECRET", "devsecret")
JWT_ALGOS  = ["HS256"]

app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/static")
app.secret_key = os.getenv("GATEWAY_SECRET", "dev")
app.config.update(SESSION_COOKIE_SAMESITE="Lax")

# Dev-only: show session debug info in templates and enable a debug endpoint if set
GATEWAY_DEBUG_SESSION = os.getenv("GATEWAY_DEBUG_SESSION", "0").lower() in ("1", "true", "yes")

@app.context_processor
def inject_debug_flags():
    return {
        "GATEWAY_DEBUG_SESSION": GATEWAY_DEBUG_SESSION,
        "session": session,
    }
UPLOAD_DIR = os.path.join(app.static_folder, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXTS = {"jpg", "jpeg", "png", "webp"}

# ===================== Helpers =====================
def _num(x):
    if x is None: 
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(x))
    return float(m.group(0)) if m else None

def save_image(file_storage, prefix="img"):
    if not file_storage or file_storage.filename == "":
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTS:
        return None
    fname = f"{prefix}_{int(time.time()*1000)}_{secure_filename(file_storage.filename)}"
    path = os.path.join(UPLOAD_DIR, fname)
    file_storage.save(path)
    return f"/static/uploads/{fname}"  # public URL served by gateway

def decode_token(token: str):
    # bỏ verify_sub để tránh lỗi nếu sub không phải string
    return jwt.decode(token, JWT_SECRET, algorithms=JWT_ALGOS, options={"verify_sub": False})

def is_admin_session() -> bool:
    token = session.get("admin_access_token") or session.get("access_token")
    if not token:
        return False
    try:
        payload = decode_token(token)
        return str(payload.get("role", "")).lower() == "admin"
    except Exception:
        return False

def login_required(next_endpoint_name="login_page"):
    def _wrap(f):
        @wraps(f)
        def inner(*args, **kwargs):
            token = session.get("access_token")
            if not token:
                # lưu lại route để quay lại sau khi login
                session["next_after_login"] = url_for(request.endpoint, **(request.view_args or {}))
                return redirect(url_for(next_endpoint_name))
            return f(*args, **kwargs)
        return inner
    return _wrap

def _update_display_name_from_payload(obj):
    """Đồng bộ display name vào session sau khi GET/PUT/POST profile ok."""
    if not isinstance(obj, dict):
        return
    prof = obj.get("profile") if "profile" in obj else obj
    if isinstance(prof, dict):
        dn = prof.get("full_name") or prof.get("display_name")
        if dn:
            session["display_name"] = dn
            u = session.get("user") or {}
            u["full_name"] = dn
            session["user"] = u
            session.modified = True

# ===================== Basic/Health =====================
@app.get("/health")
def health():
    return {"status": "ok"}, 200

@app.get("/__routes")
def __routes():
    out=[]
    for rule in app.url_map.iter_rules():
        methods=",".join(sorted(rule.methods - {"HEAD","OPTIONS"}))
        out.append({"rule": str(rule), "methods": methods, "endpoint": rule.endpoint})
    return {"routes": out}, 200

# ===================== Home =====================
@app.route("/", endpoint="home")
def home():
    """Homepage with search and listings"""
    # If a 'next_after_login' was previously stored (e.g., user tried to open /admin
    # while logged out), clear it here so visiting / doesn't cause an automatic redirect
    # after subsequent login attempts.
    session.pop('next_after_login', None)
    # Do not automatically redirect admins away from the public homepage.
    # If the user is an admin and wants to open the admin dashboard they can
    # click the explicit link in the header. We intentionally do not redirect
    # admins here so they can preview the public site or test features.
    # Check if we have any search parameters
    has_search_params = any([
        request.args.get("q"),
        request.args.get("brand"),
        request.args.get("province"),
        request.args.get("item_type"),
        request.args.get("min_price"),
        request.args.get("max_price"),
        request.args.get("year_from"),
        request.args.get("year_to"),
        request.args.get("mileage_max"),
        request.args.get("battery_capacity_min"),
        request.args.get("battery_capacity_max"),
        request.args.get("sort"),
    ])
    
    if has_search_params:
        # User is searching - call search service
        params = {}
        
        # Build search parameters
        for key in ["q", "brand", "province", "item_type", "min_price", "max_price",
                    "year_from", "year_to", "mileage_min", "mileage_max",
                    "battery_capacity", "battery_capacity_min", "battery_capacity_max", "sort"]:
            val = request.args.get(key, "").strip()
            if val:
                params[key] = val
        
        # Always filter approved items
        params["approved"] = "1"
        
        # Pagination
        page = request.args.get("page", "1")
        per_page = request.args.get("per_page", "20")
        params["page"] = page
        params["per_page"] = per_page
        
        # Call search service
        try:
            resp = requests.get(f"{SEARCH_URL}/search/listings", params=params, timeout=10)
            if resp.ok:
                data = resp.json()
                search_results = data.get("items", [])
                total = data.get("total", 0)
                pages = data.get("pages", 1)
                current_page = data.get("page", 1)
                
                return render_template(
                    "index.html",
                    cars=[],  # Don't show default cars when searching
                    batts=[],  # Don't show default batts when searching
                    search_results=search_results,
                    total=total,
                    pages=pages,
                    current_page=current_page,
                    query_params=params,
                    is_search=True
                )
        except requests.RequestException:
            # Error calling search service - ignore and continue to show defaults
            pass
    def fetch(params):
        try:
            r = requests.get(f"{LISTING_URL}/listings/", params=params, timeout=6)
            if r.ok and r.headers.get("content-type","").startswith("application/json"):
                return r.json().get("items", [])
        except requests.RequestException:
            pass
        return []

    cars = fetch({
        "approved": "1",
        "item_type": "vehicle",
        "sort": "created_desc",
        "per_page": 12,
    })

    batts = fetch({
        "approved": "1",
        "item_type": "battery",
        "sort": "created_desc",
        "per_page": 12,
    })

    # Enrich with current user's favorites (IDs + mapping) for heart state in template
    favorites_ids = set()
    favorites_map = {}
    user = session.get("user") or {}
    uid = user.get("id")
    token = session.get("access_token")
    if uid and token:
        try:
            r = requests.get(f"{FAVORITES_URL}/favorites/me", params={"user_id": uid}, timeout=5,
                              headers={"Authorization": f"Bearer {token}"})
            if r.ok and r.headers.get("content-type", "").startswith("application/json"):
                data = (r.json() or {}).get("data", [])
                for f in data:
                    fid = f.get("item_id")
                    if fid:
                        favorites_ids.add(fid)
                        favorites_map[fid] = f.get("id")  # map listing -> favorite row id
        except Exception as e:
            print("[gateway] load favorites for home failed", e)

    return render_template("index.html", cars=cars, batts=batts, is_search=False,
                           favorites_ids=favorites_ids, favorites_map=favorites_map)



# ===================== Auth =====================
@app.route("/login", methods=["GET", "POST"], endpoint="login_page")
def login_page():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Vui lòng nhập đầy đủ thông tin.", "error")
            return render_template("login.html")
        try:
            r = requests.post(f"{AUTH_URL}/auth/login",
                              json={"username": username, "password": password}, timeout=8)
        except requests.RequestException:
            flash("Không kết nối được Auth service.", "error")
            return render_template("login.html")

        if r.ok:
            token = (r.json() or {}).get("access_token")
            if not token:
                flash("Auth service không trả về access_token.", "error")
                return render_template("login.html")
            try:
                payload = decode_token(token)
            except Exception:
                flash("Token không hợp lệ.", "error")
                return render_template("login.html")
            session["access_token"] = token
            session["user"] = {
                "id": payload.get("sub"),  # user ID from JWT
                "username": payload.get("username"),
                "role": payload.get("role")
            }
            next_url = request.args.get("next") or session.pop("next_after_login", None)
            # Redirect to admin page only if the token used to login is admin.
            is_token_admin = str(payload.get("role", "")).lower() == "admin"
            return redirect(next_url or (url_for("admin_page") if is_token_admin else url_for("home")))
        flash("Đăng nhập thất bại.", "error")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"], endpoint="register_page")
def register_page():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")
        if password != confirm:
            flash("Mật khẩu xác nhận không khớp.", "error")
            return render_template("register.html")
        try:
            r = requests.post(f"{AUTH_URL}/auth/register",
                              json={"username": username, "email": email, "password": password},
                              timeout=10)
        except requests.RequestException:
            flash("Không kết nối được Auth service.", "error")
            return render_template("register.html")
        if r.status_code in (200, 201):
            flash("Đăng ký thành công! Vui lòng chờ admin duyệt.", "success")
            return redirect(url_for("login_page"))
        msg = None
        if r.headers.get("content-type","").startswith("application/json"):
            msg = (r.json() or {}).get("error")
        flash(msg or "Đăng ký thất bại.", "error")
    return render_template("register.html")

@app.get("/logout", endpoint="logout_page")
def logout_page():
    # If the session has an admin_user but also a normal user, treat this as a normal user logout
    user_present = bool(session.get('user'))
    admin_present = bool(session.get('admin_user'))
    # Determine whether this was an admin-only session
    admin_only = admin_present and not user_present
    session.clear()
    flash("Đã đăng xuất!", "success")
    return redirect(url_for("admin_page") if admin_only else url_for("home"))

# ===================== Profile proxy (auth-service) =====================
@app.route("/auth/me")
def proxy_me():
    token = session.get("access_token")
    if not token:
        return Response("Unauthorized", status=401)
    try:
        r = requests.get(f"{AUTH_URL}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=8)
        ctype = r.headers.get("content-type") or "application/json"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException:
        return Response("Auth service unreachable", status=502)

@app.route("/auth/profile", methods=["GET", "PUT", "POST"])
def proxy_profile():
    token = session.get("access_token")
    if not token:
        return Response("Unauthorized", status=401)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        if request.method == "GET":
            r = requests.get(f"{AUTH_URL}/auth/profile", headers=headers, timeout=10)
            if r.ok and (r.headers.get("content-type","").startswith("application/json")):
                try: _update_display_name_from_payload(r.json())
                except Exception: pass
        elif request.method == "PUT":
            r = requests.put(f"{AUTH_URL}/auth/profile",
                             headers={**headers, "Content-Type": "application/json"},
                             json=request.json, timeout=12)
            if r.ok and (r.headers.get("content-type","").startswith("application/json")):
                try: _update_display_name_from_payload(r.json())
                except Exception: pass
        else:  # POST multipart (upload avatar)
            files = {name: (fs.filename, fs.read(), fs.mimetype or "application/octet-stream")
                     for name, fs in request.files.items()}
            r = requests.post(f"{AUTH_URL}/auth/profile", headers=headers,
                              files=files, data=request.form, timeout=20)
            if r.ok and (r.headers.get("content-type","").startswith("application/json")):
                try: _update_display_name_from_payload(r.json())
                except Exception: pass
        ctype = r.headers.get("content-type") or "application/json"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException:
        return Response("Auth service unreachable", status=502)

@app.get("/auth/avatar/<path:name>")
def proxy_avatar(name):
    headers = {}
    if session.get("access_token"):
        headers["Authorization"] = f"Bearer {session['access_token']}"
    try:
        r = requests.get(f"{AUTH_URL}/auth/avatar/{name}", headers=headers, timeout=12, stream=True)
    except requests.RequestException:
        return Response("Auth service unreachable", status=502)
    ctype = r.headers.get("content-type", "image/jpeg")
    return Response(r.content, status=r.status_code, content_type=ctype)

# ===================== Listings (Member) =====================
@app.route("/listings/new", methods=["GET", "POST"], endpoint="add_listing")
@login_required()
def add_listing():
    u = session.get("user") or {}
    if request.method == "POST":
        payload = {
            "product_type": (request.form.get("product_type") or "car").strip(),
            "name": (request.form.get("name") or "").strip(),
            "description": (request.form.get("description") or "").strip(),
            "price": int(_num(request.form.get("price")) or 0),
            "brand": (request.form.get("brand") or "").strip(),
            "province": (request.form.get("province") or "").strip(),
            "year": int(_num(request.form.get("year")) or 0),
            "mileage": int(_num(request.form.get("mileage")) or 0),
            "battery_capacity": (request.form.get("battery_capacity") or "").strip(),
        }
        if not payload["name"] or payload["price"] <= 0:
            flash("Nhập các thông tin bắt buộc!", "error")
            return render_template("post_product.html")

        # upload ảnh
        main_url = save_image(request.files.get("main_image"), prefix=f"{u.get('username','user')}_main")
        sub_urls = []
        for f in request.files.getlist("sub_images"):
            url = save_image(f, prefix=f"{u.get('username','user')}_sub")
            if url:
                sub_urls.append(url)
        pt = payload.get("product_type", "car").lower()
        item_type = "vehicle" if pt == "car" else "battery"

        body = {
            "item_type": item_type,                     
            "name": payload["name"],
            "description": payload["description"],
            "price": payload["price"],
            "brand": payload["brand"],
            "province": payload["province"],
            "year": payload["year"],
            "mileage": payload["mileage"],
            "battery_capacity": payload["battery_capacity"],
            "main_image_url": main_url,
            "sub_image_urls": sub_urls,
    }

        try:
            r = requests.post(
                f"{LISTING_URL}/listings/",
                json=body,
                headers={"Authorization": f"Bearer {session.get('access_token','')}"},
                timeout=10
            )
        except requests.RequestException:
            flash("Không kết nối được Listing service.", "error")
            return render_template("post_product.html")
        if r.status_code == 201:
            flash("Đăng tin thành công! Bài đang chờ admin duyệt.", "success")
            return redirect(url_for("home"))

        if r.status_code == 403:
            msg = None
            try:
                if r.headers.get("content-type","").startswith("application/json"):
                    msg = (r.json() or {}).get("error")
            except Exception:
                pass
            flash(msg or "Tài khoản của bạn đang bị hạn chế đăng tin (spam).", "error")
            return render_template("post_product.html"), 403

        ct = r.headers.get("content-type", "")
        msg = None
        if ct.startswith("application/json"):
            try:
                msg = r.json().get("error")
            except Exception:
                pass
        flash(f"Đăng tin thất bại (HTTP {r.status_code}). {msg or (r.text or '')[:200]}", "error")
        return render_template("post_product.html"), r.status_code


    return render_template("post_product.html")


# ----------------- Member helpers: mine endpoints (module-level) -----------------
@app.get('/listings/mine')
def proxy_my_listings():
    """Return current user's listings by proxying to listing-service.
    Expected by front-end at `/listings/mine`.
    """
    u = session.get('user') or {}
    username = u.get('username')
    if not username:
        return Response('Unauthorized', status=401)
    headers = {}
    if session.get('access_token'):
        headers['Authorization'] = f"Bearer {session.get('access_token')}"
    try:
        # Include sold items so the user's own listing view shows sold/removed items too
        params = {'owner': username, 'per_page': 200, 'include_sold': '1'}
        r = requests.get(f"{LISTING_URL}/listings", params=params, timeout=8, headers=headers)
    except requests.RequestException:
        return Response('Listing service unreachable', status=502)
    ctype = r.headers.get('content-type','application/json')
    return Response(r.content, status=r.status_code, content_type=ctype)


@app.get('/payments/mine')
def proxy_my_payments():
    """Return payments related to current user (as buyer or seller).
    Front-end expects an object with `items` list.
    """
    u = session.get('user') or {}
    uid = u.get('id')
    if not uid:
        return Response('Unauthorized', status=401)
    headers = {}
    if session.get('access_token'):
        headers['Authorization'] = f"Bearer {session.get('access_token')}"

    items = []
    try:
        # payments where user is buyer
        r1 = requests.get(f"{PAYMENT_URL}/payment", params={'buyer_id': uid, 'per_page': 200}, timeout=8, headers=headers)
        if r1.ok and r1.headers.get('content-type','').startswith('application/json'):
            j1 = r1.json() or {}
            items += j1.get('items') or j1.get('data') or j1 or []
        # payments where user is seller
        r2 = requests.get(f"{PAYMENT_URL}/payment", params={'seller_id': uid, 'per_page': 200}, timeout=8, headers=headers)
        if r2.ok and r2.headers.get('content-type','').startswith('application/json'):
            j2 = r2.json() or {}
            items += j2.get('items') or j2.get('data') or j2 or []
    except requests.RequestException:
        return Response('Payment service unreachable', status=502)
    # normalize items: ensure dicts (skip malformed string items)
    normalized = []
    for it in items:
        if isinstance(it, dict):
            normalized.append(it)
        elif isinstance(it, str):
            try:
                parsed = json.loads(it)
                if isinstance(parsed, dict):
                    normalized.append(parsed)
            except Exception:
                # skip unparseable string
                continue
        else:
            # unexpected type - skip
            continue

    # dedupe by id or order_id
    seen = set()
    out = []
    for it in normalized:
        key = None
        try:
            key = str(it.get('id') or it.get('order_id') or (it.get('order') if isinstance(it, dict) else None))
        except Exception:
            key = None
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(it)

    # sort by created_at/updated_at defensively
    def _ts(x):
        if not isinstance(x, dict):
            return ''
        return x.get('created_at') or x.get('updated_at') or ''

    out.sort(key=_ts, reverse=True)

    return jsonify({'items': out})



@app.get("/listings/<int:pid>")
def product_detail(pid):
    try:
        r = requests.get(f"{LISTING_URL}/listings/{pid}", timeout=8)
        if not r.ok or not r.headers.get("content-type","").startswith("application/json"):
            flash("Không tải được thông tin sản phẩm.", "error")
            return redirect(url_for("home"))
        item = r.json()
    except requests.RequestException:
        flash("Không kết nối được listing service.", "error")
        return redirect(url_for("home"))
    return render_template("product_detail.html", item=item)


@app.get('/seller/info')
def seller_info():
    """Return basic seller display info (full_name, avatar) for a given username.
    This attempts to use an admin listing from auth-service (requires admin token in env or admin session).
    If no admin access is available, returns a minimal object with username only.
    Query params: username (required)
    """
    username = request.args.get('username') or request.args.get('user')
    if not username:
        return jsonify(error='missing_username'), 400

    # Try to use admin session first
    user_map = {}
    try:
        if is_admin_session():
            hdr = _forward_admin_headers()
            r = requests.get(f"{AUTH_URL}/auth/admin/users", headers=hdr, timeout=8)
            if r.ok:
                data = r.json().get('data', [])
                for u in data:
                    user_map[str(u.get('username'))] = u
        # Fallback to ADMIN_TOKEN env
        if not user_map:
            admin_token = os.getenv('ADMIN_TOKEN') or os.getenv('GATEWAY_ADMIN_TOKEN')
            if admin_token:
                hdr = {'Authorization': f'Bearer {admin_token}'}
                r = requests.get(f"{AUTH_URL}/auth/admin/users", headers=hdr, timeout=8)
                if r.ok:
                    data = r.json().get('data', [])
                    for u in data:
                        user_map[str(u.get('username'))] = u
    except Exception:
        user_map = {}

    u = user_map.get(username)
    if u:
        # If admin endpoint returned an avatar filename, expose it as /auth/avatar/<name>
        avatar_field = u.get('avatar_url') or u.get('avatar') or None
        avatar_src = (f"/auth/avatar/{avatar_field}" if avatar_field else None)
        return jsonify({
            'username': u.get('username'),
            'full_name': u.get('full_name') or u.get('username'),
            'email': u.get('email'),
            'phone': u.get('phone'),
            'id': u.get('id'),
            'avatar_src': avatar_src,
            'reviews': []
        })

    # Try public user endpoint on auth service as a fallback so we can show contact info
    try:
        r = requests.get(f"{AUTH_URL}/auth/users/{username}", timeout=6)
        if r.ok:
            data = r.json() or {}
            return jsonify({
                'id': data.get('id'),
                'username': data.get('username', username),
                'full_name': data.get('full_name', username),
                'email': data.get('email'),
                'phone': data.get('phone'),
                'avatar_src': data.get('avatar_url') and f"/auth/avatar/{data.get('avatar_url')}" or None,
                'reviews': []
            })
    except Exception:
        pass

    # No info - return minimal
    return jsonify({'username': username, 'full_name': username, 'phone': None, 'reviews': []})

# ===================== Admin (duyệt/xoá bài, duyệt user) =====================
@app.route("/admin", methods=["GET"], endpoint="admin_page")
def admin_page():
    users, products, transactions = [], [], []

    # --- tham số lọc luôn có giá trị mặc định ---
    cur_status   = (request.args.get("status") or "").strip()     # '', pending, approved, spam, rejected
    cur_verified = (request.args.get("verified") or "").strip()   # '', '1', '0'

    # ---- USERS (chỉ khi là admin) ----
    if is_admin_session():
        # Use admin headers (fall back to normal access token if admin token not present)
        headers = _forward_admin_headers()
        for url in (f"{ADMIN_URL}/admin/users",
                    f"{AUTH_URL}/auth/admin/users",
                    f"{AUTH_URL}/auth/users"):
            try:
                r = requests.get(url, headers=headers, timeout=8)
                if r.ok and r.headers.get("content-type","").startswith("application/json"):
                    data = r.json()
                    raw = data.get("data", data if isinstance(data, list) else [])
                    users = [u for u in raw if not (u.get("is_admin") or str(u.get("role","")).lower()=="admin")]
                    break
            except requests.RequestException:
                pass

    # ---- PRODUCTS (lọc theo trạng thái/kiểm định) ----
    url = f"{LISTING_URL}/listings/?sort=created_desc"
    if cur_status in {"pending", "approved", "rejected", "spam"}:
        url += f"&status={cur_status}"
    if cur_verified in {"0", "1"}:
        url += f"&verified={'true' if cur_verified=='1' else 'false'}"

    try:
        r2 = requests.get(url, timeout=8)
        if r2.ok and r2.headers.get("content-type","").startswith("application/json"):
            data = r2.json()
            products = data.get("items", data if isinstance(data, list) else [])
    except requests.RequestException:
        flash("Không kết nối được listing service.", "error")

    return render_template(
        "admin.html",
        users=users, products=products, transactions=transactions,
        is_admin=is_admin_session(),
        cur_status=cur_status, cur_verified=cur_verified
    )



@app.post("/admin/login", endpoint="admin_login")
def admin_login():
    username = request.form.get("username","").strip()
    password = request.form.get("password","")
    if not username or not password:
        flash("Vui lòng nhập đầy đủ thông tin.", "error")
        return redirect(url_for("admin_page"))
    try:
        r = requests.post(f"{AUTH_URL}/auth/login", json={"username": username, "password": password}, timeout=8)
    except requests.RequestException:
        flash("Không kết nối được Auth service.", "error")
        return redirect(url_for("admin_page"))
    if not r.ok:
        flash("Đăng nhập thất bại.", "error")
        return redirect(url_for("admin_page"))
    token = (r.json() or {}).get("access_token")
    if not token:
        flash("Auth service không trả về access_token.", "error")
        return redirect(url_for("admin_page"))
    try:
        payload = decode_token(token)
    except Exception:
        flash("Token không hợp lệ.", "error")
        return redirect(url_for("admin_page"))
    if str(payload.get("role","")).lower() != "admin":
        flash("Tài khoản không phải admin.", "error")
        return redirect(url_for("admin_page"))
    # Do not override normal user session when an admin logs in on the admin page.
    # Store admin token and admin_user separately to avoid switching the primary user.
    session["admin_access_token"] = token
    session["admin_user"] = {
        "id": payload.get("sub"),
        "username": payload.get("username"),
        "role": payload.get("role")
    }
    flash("Đăng nhập admin thành công!", "success")
    return redirect(url_for("admin_page"))

@app.get("/admin/logout", endpoint="admin_logout")
def admin_logout():
    # Remove only admin session values (keep normal user session intact)
    session.pop("admin_access_token", None)
    session.pop("admin_user", None)
    flash("Đã đăng xuất khỏi Admin!", "success")
    return redirect(url_for("admin_page"))

# --- DUYỆT ---
@app.post("/admin/approve/<int:pid>")
@app.get("/admin/approve/<int:pid>")
def approve_product(pid):
    if not is_admin_session():
        session["next_after_login"] = url_for("approve_product", pid=pid)
        return redirect(url_for("login_page"))
    try:
        r = requests.put(
            f"{LISTING_URL}/listings/{pid}/approve",
            headers=_forward_admin_headers(),
            timeout=10,
        )
        if r.ok:
            flash("✅ Đã duyệt bài đăng.", "success")
        else:
            msg = None
            try:
                if r.headers.get("content-type","").startswith("application/json"):
                    msg = (r.json() or {}).get("error")
            except Exception:
                pass
            flash(msg or f"Không duyệt được (HTTP {r.status_code}).", "error")
    except requests.RequestException:
        flash("Không kết nối được listing service.", "error")
    return redirect(url_for("admin_page"))

# --- TỪ CHỐI ---
@app.post("/admin/reject/<int:pid>")
def reject_product(pid):
    if not is_admin_session():
        session["next_after_login"] = url_for("reject_product", pid=pid)
        return redirect(url_for("login_page"))
    note = request.form.get("note")
    requests.put(
        f"{LISTING_URL}/listings/{pid}/reject",
        json={"note": note},
        headers=_forward_admin_headers(),
        timeout=10,
    )
    return redirect(url_for("admin_page"))


@app.post("/admin/mark_spam/<int:pid>")
@app.get("/admin/mark_spam/<int:pid>")
def mark_spam(pid):
    if not is_admin_session():
        session["next_after_login"] = url_for("mark_spam", pid=pid)
        return redirect(url_for("login_page"))
    note = request.values.get("note")  
    try:
        r = requests.put(
            f"{LISTING_URL}/listings/{pid}/mark_spam",
            json={"note": note} if note else None,
            headers=_forward_admin_headers(),
            timeout=10,
        )
        if r.ok:
            flash("🚫 Đã gắn spam & chặn user đăng bài mới.", "success")
        else:
            msg = None
            try:
                if r.headers.get("content-type","").startswith("application/json"):
                    msg = (r.json() or {}).get("error")
            except Exception:
                pass
            flash(msg or f"Đánh dấu spam thất bại (HTTP {r.status_code}).", "error")
    except requests.RequestException:
        flash("Không kết nối được listing service.", "error")
    return redirect(url_for("admin_page"))

@app.post("/admin/unspam/<int:pid>")
@app.get("/admin/unspam/<int:pid>")
def unspam(pid):
    if not is_admin_session():
        session["next_after_login"] = url_for("unspam", pid=pid)
        return redirect(url_for("login_page"))
    try:
        r = requests.put(
            f"{LISTING_URL}/listings/{pid}/unspam",
            headers=_forward_admin_headers(),
            timeout=10,
        )
        flash("✅ Đã bỏ spam (mở khoá nếu không còn bài spam).", "success" if r.ok else "error")
    except requests.RequestException:
        flash("Không kết nối được listing service.", "error")
    return redirect(url_for("admin_page"))

@app.post("/admin/verify/<int:pid>")
def verify(pid):
    if not is_admin_session():
        session["next_after_login"] = url_for("verify", pid=pid)
        return redirect(url_for("login_page"))
    requests.put(f"{LISTING_URL}/listings/{pid}/verify",
                 headers=_forward_admin_headers(), timeout=10)
    return redirect(url_for("admin_page"))

@app.post("/admin/unverify/<int:pid>")
def unverify(pid):
    if not is_admin_session():
        session["next_after_login"] = url_for("unverify", pid=pid)
        return redirect(url_for("login_page"))
    requests.put(f"{LISTING_URL}/listings/{pid}/unverify",
                 headers=_forward_admin_headers(), timeout=10)
    return redirect(url_for("admin_page"))


@app.get("/admin/delete/<int:pid>")
def delete_product(pid):
    if not is_admin_session():
        session["next_after_login"] = url_for("delete_product", pid=pid)
        return redirect(url_for("login_page"))
    try:
        r = requests.delete(f"{LISTING_URL}/listings/{pid}",
                            headers=_forward_admin_headers())
        flash("Đã xoá bài đăng." if r.ok else "Xoá thất bại.", "success" if r.ok else "error")
    except requests.RequestException:
        flash("Không kết nối được listing service.", "error")
    return redirect(url_for("admin_page"))


def _try_patch(urls_with_payload, headers, timeout=8):
    last_err = "No targets"
    for url, payload in urls_with_payload:
        try:
            r = requests.patch(url, json=payload, headers=headers, timeout=timeout)
            if r.ok:
                return True, r
            last_err = f"{url} -> HTTP {r.status_code} {r.text[:200]}"
        except requests.RequestException as e:
            last_err = f"{url} -> {e}"
    return False, last_err

@app.route("/admin/approve_user/<int:user_id>", methods=["POST","GET"])
def approve_user(user_id):
    if not is_admin_session():
        session["next_after_login"] = url_for("approve_user", user_id=user_id)
        return redirect(url_for("login_page"))

    headers = {**_forward_admin_headers(), "Content-Type": "application/json"}

    targets = [
        (f"{ADMIN_URL}/admin/users/{user_id}/status", {"status": "approved"}),
        (f"{AUTH_URL}/auth/admin/users/{user_id}/status", {"status": "approved"}),
        (f"{AUTH_URL}/auth/users/{user_id}/status", {"status": "approved"}),
        (f"{AUTH_URL}/auth/admin/users/{user_id}", {"approved": True}),
    ]
    ok, res = _try_patch(targets, headers)
    if ok:
        flash("✅ Đã duyệt tài khoản.", "success")
    else:
        flash(f"Không duyệt được: {res}", "error")
    return redirect(url_for("admin_page"))

@app.route("/admin/delete_user/<int:user_id>", methods=["POST","GET"])
def delete_user(user_id):
    if not is_admin_session():
        session["next_after_login"] = url_for("delete_user", user_id=user_id)
        return redirect(url_for("login_page"))

    headers = {**_forward_admin_headers(), "Content-Type": "application/json"}
    targets = [
        (f"{ADMIN_URL}/admin/users/{user_id}/status", {"status": "locked"}),
        (f"{AUTH_URL}/auth/admin/users/{user_id}/status", {"status": "locked"}),
        (f"{AUTH_URL}/auth/users/{user_id}/status", {"status": "locked"}),
        (f"{AUTH_URL}/auth/admin/users/{user_id}", {"locked": True}),
    ]
    ok, res = _try_patch(targets, headers)
    if ok:
        flash("🔒 Đã khóa tài khoản.", "success")
    else:
        flash(f"Không khóa được: {res}", "error")
    return redirect(url_for("admin_page"))

 

# ===================== AI price suggest =====================
@app.post("/ai/price_suggest")
def price_suggest():
    raw = request.get_json(silent=True) or request.form.to_dict() or {}
    product_type = (raw.get("product_type") or "car").strip().lower()
    name         = (raw.get("name") or "").strip()
    brand        = (raw.get("brand") or "").strip()
    province     = (raw.get("province") or "").strip()
    year         = _num(raw.get("year"))
    mileage      = _num(raw.get("mileage"))
    cap_kwh      = _num(raw.get("battery_capacity_kwh") or raw.get("battery_capacity"))
    description  = (raw.get("description") or "").strip()

    payload = {
        "product_type": product_type,
        "name": name,
        "brand": brand,
        "province": province,
        "year": int(year) if year is not None else None,
        "mileage": int(mileage) if mileage is not None else None,
        "battery_capacity_kwh": float(cap_kwh) if cap_kwh is not None else None,
        "description": description,
    }
    try:
        r = requests.post(f"{PRICING_URL}/predict", json=payload, timeout=(5, 90))
    except requests.exceptions.ReadTimeout as e:
        return jsonify(error="pricing-service quá thời gian phản hồi", detail=str(e)), 504
    except requests.exceptions.RequestException as e:
        return jsonify(error="Không kết nối được pricing-service", detail=str(e)), 502

    ct = r.headers.get("content-type", "")
    if ct.startswith("application/json"):
        try:
            return jsonify(r.json()), r.status_code
        except Exception:
            pass
    return (r.text, r.status_code, {"Content-Type": ct or "text/plain"})

# ===================== Profile page (UI) =====================
@app.get("/profile", endpoint="profile")
def profile_page():
    return render_template("profile.html")


# ===================== Cart (UI) =====================
@app.get("/cart", endpoint="cart_page")
def cart_page():
    """Render cart page. Cart is mainly managed client-side via localStorage.
    Server may optionally pass `items` for server-side carts; absent by default."""
    return render_template("cart.html")

@app.route("/policy", methods=["GET"], endpoint="policy_page")
def policy_page():
    return render_template("policy.html")

# ===================== Favorites =====================
@app.route("/favorites", methods=["GET"])
@login_required()
def favorites_page():
    """Display user's favorite listings"""
    token = session.get("access_token")
    user = session.get("user", {})
    user_id = user.get("id")
    
    if not user_id:
        flash("Không tìm thấy thông tin người dùng.", "error")
        return redirect(url_for("home"))
    
    try:
        # Get favorites from favorites service
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(f"{FAVORITES_URL}/favorites/me", params={"user_id": user_id}, headers=headers, timeout=5)
        view_favs = []
        if resp.ok and (resp.headers.get("content-type","" ).startswith("application/json")):
            favs = resp.json().get("data", [])
            # Fetch full listing details for each favorite, attach into expected template shape
            for fav in favs:
                item = None
                try:
                    r2 = requests.get(f"{LISTING_URL}/listings/{fav['item_id']}", headers=headers, timeout=6)
                    if r2.ok and r2.headers.get("content-type","" ).startswith("application/json"):
                        item = r2.json()
                except Exception:
                    item = None
                view_favs.append({
                    "id": fav.get("id"),
                    "item_type": fav.get("item_type"),
                    "item_id": fav.get("item_id"),
                    "item": item,
                })
        
        return render_template("favorites.html", favs=view_favs)
    except requests.RequestException:
        flash("Không thể tải danh sách yêu thích.", "error")
        return render_template("favorites.html", favs=[])

@app.post("/favorites/add")
@login_required()
def add_favorite():
    """Add item to favorites"""
    token = session.get("access_token")
    user = session.get("user", {})

    def _resolve_user_id():
        # 1. session
        uid = user.get("id") or user.get("user_id")
        if uid:
            return uid
        # 2. decode token
        if token:
            try:
                payload = decode_token(token)
                uid = payload.get("sub")
                if uid:
                    return uid
            except Exception as e:
                print("[gateway] decode_token failed", e)
        # 3. call /auth/me (final fallback)
        if token:
            try:
                r = requests.get(f"{AUTH_URL}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=4)
                if r.ok and r.headers.get("content-type","" ).startswith("application/json"):
                    uid = (r.json() or {}).get("sub")
                    return uid
            except requests.RequestException as e:
                print("[gateway] /auth/me fallback failed", e)
        return None

    user_id = _resolve_user_id()
    if user_id and not user.get("id"):
        # persist to session for next requests
        user["id"] = user_id
        session["user"] = user
        session.modified = True

    print(f"[gateway] favorites/add session_user={user}")
    print(f"[gateway] favorites/add resolved_user_id={user_id}")
    if not user_id:
        return jsonify(error="not_logged_in", detail="Không xác định được người dùng"), 400
    
    data = request.get_json() or {}
    item_id = data.get("item_id")
    item_type = data.get("item_type", "vehicle")
    
    if not item_id:
        return jsonify(error="missing_item_id"), 400
    
    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"user_id": int(user_id), "item_type": str(item_type), "item_id": int(item_id)}
        print(f"DEBUG favorites/add payload -> {payload}")
        resp = requests.post(f"{FAVORITES_URL}/favorites", json=payload, headers=headers, timeout=5)
        print(f"DEBUG favorites/add upstream status={resp.status_code} body={resp.text[:200]}")
        
        if resp.ok:
            return jsonify(resp.json()), 201
        elif resp.status_code == 409:
            return jsonify(error="already_exists"), 409
        elif resp.status_code == 400:
            try:
                upstream = resp.json()
            except Exception:
                upstream = {"raw": resp.text[:200]}
            return jsonify(error="upstream_400", upstream=upstream), 400
        else:
            return jsonify(error="upstream_failure", status=resp.status_code, body=resp.text[:300]), resp.status_code
    except requests.RequestException as e:
        print(f"[gateway] favorites/add exception: {str(e)}")
        return jsonify(error=str(e)), 500

@app.post("/favorites/remove_by_item")
@login_required()
def remove_favorite_by_item():
    """Remove favorite by listing item_id (convenience endpoint for toggle UI)."""
    token = session.get("access_token")
    user = session.get("user") or {}
    uid = user.get("id")
    if not uid:
        return jsonify(error="not_logged_in"), 401
    payload = request.get_json() or {}
    item_id = payload.get("item_id")
    try:
        item_id = int(item_id)
    except Exception:
        return jsonify(error="invalid_item_id"), 400
    # Fetch favorites to locate the favorite record id
    try:
        r = requests.get(f"{FAVORITES_URL}/favorites/me", params={"user_id": uid}, timeout=5,
                          headers={"Authorization": f"Bearer {token}"})
        fav_id = None
        if r.ok and r.headers.get("content-type", "").startswith("application/json"):
            for f in (r.json() or {}).get("data", []):
                if f.get("item_id") == item_id:
                    fav_id = f.get("id")
                    break
        if not fav_id:
            return jsonify(error="favorite_not_found"), 404
        del_resp = requests.delete(f"{FAVORITES_URL}/favorites/{fav_id}", timeout=5,
                                   headers={"Authorization": f"Bearer {token}"})
        if del_resp.ok:
            return jsonify(ok=True, removed=fav_id)
        return jsonify(error="upstream_delete_failed", status=del_resp.status_code,
                       body=del_resp.text[:200]), del_resp.status_code
    except requests.RequestException as e:
        return jsonify(error="upstream_unreachable", detail=str(e)), 502

@app.delete("/favorites/<int:fav_id>")
@login_required()
def remove_favorite(fav_id):
    """Remove item from favorites"""
    token = session.get("access_token")
    
    try:
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.delete(f"{FAVORITES_URL}/favorites/{fav_id}", headers=headers, timeout=5)
        
        if resp.ok:
            return jsonify(ok=True), 200
        else:
            return jsonify(error="Failed to remove"), resp.status_code
    except requests.RequestException as e:
        return jsonify(error=str(e)), 500

# ===================== Compare =====================
@app.route("/compare", methods=["GET"])
def compare_page():
    """Compare multiple vehicles/batteries"""
    ids = request.args.get("ids", "").split(",")
    ids = [i.strip() for i in ids if i.strip().isdigit()]
    
    if not ids:
        return render_template("compare.html", items=[])
    
    items = []
    token = session.get("access_token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    for item_id in ids[:4]:  # Limit to 4 items max
        try:
            resp = requests.get(f"{LISTING_URL}/listings/{item_id}", headers=headers, timeout=5)
            if resp.ok:
                items.append(resp.json())
        except Exception:
            pass
    
    return render_template("compare.html", items=items)


# Lightweight JSON proxy for listings (used by compare page and potential clients)
@app.get("/api/listings/<int:pid>")
def api_get_listing(pid: int):
    headers = {}
    if session.get("access_token"):
        headers["Authorization"] = f"Bearer {session['access_token']}"
    try:
        r = requests.get(f"{LISTING_URL}/listings/{pid}", headers=headers, timeout=8)
    except requests.RequestException as e:
        return jsonify(error="listing_upstream_unreachable", detail=str(e)), 502
    ct = r.headers.get("content-type", "")
    if ct.startswith("application/json"):
        try:
            return jsonify(r.json()), r.status_code
        except Exception:
            pass
    # Fallback: return raw
    return (r.text, r.status_code, {"Content-Type": ct or "text/plain"})


_AI_PRICE_CACHE = {}  
_AI_PRICE_TTL_S = 300  

def _ai_cache_get(key):
    now = __import__("time").time()
    v = _AI_PRICE_CACHE.get(key)
    if not v:
        return None
    exp, data = v
    if now > exp:
        _AI_PRICE_CACHE.pop(key, None)
        return None
    return data

def _ai_cache_set(key, data, ttl=_AI_PRICE_TTL_S):
    now = __import__("time").time()
    _AI_PRICE_CACHE[key] = (now + ttl, data)

def _ai_hash_payload(payload: dict) -> str:
    m = __import__("hashlib").sha256()
    m.update(__import__("json").dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return m.hexdigest()

def _ai_num(x):
    try:
        return _num(x) 
    except Exception:
        import re
        if x is None:
            return None
        m = re.search(r"\d+(?:\.\d+)?", str(x))
        return float(m.group(0)) if m else None

def _ai_build_predict_payload(raw: dict) -> dict:
    pt = (raw.get("product_type") or raw.get("item_type") or "car").strip().lower()
    name = (raw.get("name") or "").strip()
    brand = (raw.get("brand") or "").strip()
    province = (raw.get("province") or "").strip()
    year = _ai_num(raw.get("year"))
    mileage = _ai_num(raw.get("mileage"))
    cap_kwh = _ai_num(raw.get("battery_capacity_kwh") or raw.get("battery_capacity"))
    description = (raw.get("description") or "").strip()
    return {
        "product_type": pt,
        "name": name,
        "brand": brand,
        "province": province,
        "year": int(year) if year is not None else None,
        "mileage": int(mileage) if mileage is not None else None,
        "battery_capacity_kwh": float(cap_kwh) if cap_kwh is not None else None,
        "description": description,
    }

def _ai_safe_jsonify(obj, status=200):
    from flask import jsonify
    return jsonify(obj), status

@app.post("/ai/price_suggest_v2")
def ai_price_suggest_v2():
    import os, requests, json
    if (getattr(request, "content_type", "") or "").startswith("application/json"):
        raw = request.get_json(silent=True) or {}
    else:
        raw = request.form.to_dict()

    payload = _ai_build_predict_payload(raw)
    cache_key = _ai_hash_payload(payload)
    cached = _ai_cache_get(cache_key)
    if cached is not None:
        return _ai_safe_jsonify({"cached": True, "data": cached})

    PRICING_URL = os.getenv("PRICING_URL", "http://pricing_service:5003")
    try:
        r = requests.post(f"{PRICING_URL}/predict", json=payload, timeout=(5, 90))
    except requests.exceptions.ReadTimeout as e:
        app.logger.exception("pricing-service read timeout (v2)")
        return _ai_safe_jsonify({"error": "pricing-service quá thời gian phản hồi", "detail": str(e)}, 504)
    except requests.exceptions.RequestException as e:
        app.logger.exception("price_suggest_v2 failed: %s", e)
        return _ai_safe_jsonify({"error": "Không kết nối được pricing-service", "detail": str(e)}, 502)

    ct = (r.headers.get("content-type") or "")
    if ct.startswith("application/json"):
        try:
            data = r.json()
            _ai_cache_set(cache_key, data)
            return _ai_safe_jsonify({"cached": False, "data": data}, r.status_code)
        except Exception:
            pass
    try:
        _ai_cache_set(cache_key, {"text": r.text, "content_type": ct})
    except Exception:
        pass
    return (r.text, r.status_code, {"Content-Type": ct or "text/plain"})


@app.get("/ai/estimate_from_listing/<int:pid>")
def ai_estimate_from_listing(pid: int):
    import os, requests
    LISTING_URL = os.getenv("LISTING_URL", "http://listing_service:5002")
    PRICING_URL = os.getenv("PRICING_URL", "http://pricing_service:5003")

    headers = {}
    tok = session.get("access_token")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        r = requests.get(f"{LISTING_URL}/listings/{pid}", headers=headers, timeout=8)
        if not r.ok or not (r.headers.get("content-type","").startswith("application/json")):
            return _ai_safe_jsonify({"error": "Không tải được thông tin sản phẩm.", "status": r.status_code}, 502)
        item = r.json()
    except requests.RequestException as e:
        return _ai_safe_jsonify({"error": "Không kết nối được listing-service", "detail": str(e)}, 502)

    raw = {
        "product_type": item.get("item_type") or item.get("product_type") or "car",
        "name": item.get("name"),
        "brand": item.get("brand"),
        "province": item.get("province"),
        "year": item.get("year"),
        "mileage": item.get("mileage"),
        "battery_capacity_kwh": item.get("battery_capacity_kwh") or item.get("battery_capacity"),
        "description": item.get("description"),
    }
    payload = _ai_build_predict_payload(raw)

    cache_key = "id:" + str(pid) + ":" + _ai_hash_payload(payload)
    cached = _ai_cache_get(cache_key)
    if cached is not None:
        return _ai_safe_jsonify({"cached": True, "listing": item, "data": cached})

    try:
        r2 = requests.post(f"{PRICING_URL}/predict", json=payload, timeout=(5, 90))
    except requests.exceptions.ReadTimeout as e:
        app.logger.exception("pricing-service read timeout (from_listing)")
        return _ai_safe_jsonify({"error": "pricing-service quá thời gian phản hồi", "detail": str(e)}, 504)
    except requests.exceptions.RequestException as e:
        app.logger.exception("estimate_from_listing failed: %s", e)
        return _ai_safe_jsonify({"error": "Không kết nối được pricing-service", "detail": str(e)}, 502)

    ct2 = (r2.headers.get("content-type") or "")
    if ct2.startswith("application/json"):
        try:
            data = r2.json()
            _ai_cache_set(cache_key, data)
            return _ai_safe_jsonify({"cached": False, "listing": item, "data": data}, r2.status_code)
        except Exception:
            pass
    return (r2.text, r2.status_code, {"Content-Type": ct2 or "text/plain"})

@app.post("/ai/bulk_price_suggest")
def ai_bulk_price_suggest():
    import requests, os
    PRICING_URL = os.getenv("PRICING_URL", "http://pricing_service:5003")

    payloads = []
    if (getattr(request, "content_type", "") or "").startswith("application/json"):
        data = request.get_json(silent=True) or {}
        payloads = data.get("items") or []
    else:
        import json as _json
        try:
            payloads = _json.loads(request.form.get("items") or "[]")
        except Exception:
            payloads = []

    if not isinstance(payloads, list) or not payloads:
        return _ai_safe_jsonify({"error": "Thiếu danh sách items"}, 400)

    results = []
    for raw in payloads:
        pl = _ai_build_predict_payload(raw or {})
        key = _ai_hash_payload(pl)
        cached = _ai_cache_get(key)
        if cached is not None:
            results.append({"input": pl, "cached": True, "data": cached})
            continue
        try:
            r = requests.post(f"{PRICING_URL}/predict", json=pl, timeout=(5, 90))
            if (r.headers.get("content-type") or "").startswith("application/json"):
                data = r.json()
                _ai_cache_set(key, data)
                results.append({"input": pl, "cached": False, "data": data, "status": r.status_code})
            else:
                results.append({"input": pl, "cached": False, "text": r.text, "content_type": r.headers.get("content-type"), "status": r.status_code})
        except requests.RequestException as e:
            results.append({"input": pl, "error": str(e)})

    return _ai_safe_jsonify({"items": results}, 200)

@app.get("/ai/upstream_status")
def ai_upstream_status():
    import os, requests
    urls = {
        "auth": os.getenv("AUTH_URL", "http://auth_service:5001"),
        "listing": os.getenv("LISTING_URL", "http://listing_service:5002"),
        "pricing": os.getenv("PRICING_URL", "http://pricing_service:5003"),
    }
    out = {}
    for name, base in urls.items():
        try:
            # ưu tiên endpoint health; fallback GET /
            for path in ("/health", "/"):
                try_url = base.rstrip("/") + path
                r = requests.get(try_url, timeout=4)
                out[name] = {
                    "url": try_url,
                    "ok": r.ok,
                    "status": r.status_code,
                    "content_type": r.headers.get("content-type"),
                }
                break
            if name not in out:
                out[name] = {"url": base, "ok": False, "status": None}
        except requests.RequestException as e:
            out[name] = {"url": base, "ok": False, "error": str(e)}
    return _ai_safe_jsonify(out, 200)

@app.post("/ai/normalize_fields")
def ai_normalize_fields():
    if (getattr(request, "content_type", "") or "").startswith("application/json"):
        raw = request.get_json(silent=True) or {}
    else:
        raw = request.form.to_dict()
    return _ai_safe_jsonify(_ai_build_predict_payload(raw), 200)

@app.get("/ai/upstream_status_v2")
def ai_upstream_status_v2():
    import os, requests
    checks = {
        "auth": os.getenv("AUTH_URL", "http://auth_service:5001"),
        "listing": os.getenv("LISTING_URL", "http://listing_service:5002"),
        "pricing": os.getenv("PRICING_URL", "http://pricing_service:5003"),
    }
    out = {}
    for name, base in checks.items():
        base = base.rstrip("/")
        tried = []
        for path in ("/health", "/"):
            url = base + path
            tried.append(url)
            try:
                r = requests.get(url, timeout=4)
                out[name] = {
                    "url": url,
                    "ok": r.ok,
                    "status": r.status_code,
                    "content_type": r.headers.get("content-type"),
                }
                if r.ok:
                    break
            except requests.RequestException as e:
                out[name] = {"url": url, "ok": False, "error": str(e)}
        out[name]["tried"] = tried
    return (out, 200)


# ===================== Reviews proxy =====================
REVIEWS_URL = os.getenv("REVIEWS_URL", "http://reviews_service:5010")


@app.route('/reviews/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def gw_reviews_proxy(subpath: str):
    """Simple proxy to forward /reviews/* requests to the reviews-service.

    This lets templates link to /reviews/product/<id> and have the gateway
    transparently forward the request to the reviews service inside compose.
    """
    try:
        import requests
        # Build target URL inside the compose network
        target = REVIEWS_URL.rstrip('/') + '/reviews/' + subpath.lstrip('/')
        # Prepare headers: forward auth if present and content-type
        headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'}
        headers.update(_forward_auth_headers())

        # OPTIONS quick response
        if request.method == 'OPTIONS':
            return ('', 204)

        if request.method == 'GET':
            r = requests.get(target, params=request.args, headers=headers, timeout=10)
        elif request.method == 'POST':
            # Support JSON and form posts
            if (request.content_type or '').lower().startswith('application/json'):
                r = requests.post(target, json=request.get_json(silent=True) or {}, headers=headers, timeout=10)
            else:
                r = requests.post(target, data=request.form or request.get_data(), headers=headers, timeout=10)
        elif request.method == 'PUT':
            r = requests.put(target, json=request.get_json(silent=True) or {}, headers=headers, timeout=10)
        elif request.method == 'DELETE':
            r = requests.delete(target, headers=headers, timeout=10)
        else:
            r = requests.request(request.method, target, headers=headers, timeout=10)

        resp = Response(r.content, status=r.status_code, content_type=r.headers.get('content-type', 'application/json'))
        return resp
    except requests.RequestException as e:
        return jsonify({'error': 'reviews_upstream_unreachable', 'detail': str(e)}), 502
# ===================== Payment (proxy) =====================
def _forward_auth_headers():
    """Forward Authorization header if user logged in."""
    headers = {}
    # Use normal user access token for user-facing flows; admin-only flows should
    # explicitly call `_forward_admin_headers()` to forward the admin token instead.
    tok = session.get("access_token")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def _forward_admin_headers():
    """Forward admin Authorization header if admin user logged in.

    Falls back to normal access_token if admin token not present.
    """
    headers = {}
    tok = session.get("admin_access_token") or session.get("access_token")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers

@app.post("/payment/create")
def gw_payment_create():
    """Tạo paymentId rồi trả về checkout_url"""
    try:
        payload = request.get_json(silent=True) or {}
        
        # Auto-populate seller_id from listing if not provided or if items contain listing references
        # Priority: explicit seller_id > items[0].seller_id > fetch from listing-service
        if not payload.get("seller_id"):
            # Try to derive seller from items
            items = payload.get("items") or []
            if items and isinstance(items, list):
                first_item = items[0]
                if isinstance(first_item, dict):
                    # Check if item has item_id (listing id) but no seller_id
                    item_id = first_item.get("item_id") or first_item.get("id")
                    existing_seller = first_item.get("seller_id")
                    
                    if item_id and not existing_seller:
                        # Fetch listing owner from listing-service
                        try:
                            lr = requests.get(f"{LISTING_URL}/listings/{item_id}", timeout=5)
                            if lr.ok:
                                listing_data = lr.json()
                                owner_id = None
                                # Listing may return owner as object with id, or as username string.
                                if isinstance(listing_data.get("owner"), dict):
                                    owner_id = listing_data.get("owner_id") or (listing_data.get("owner") or {}).get("id")
                                else:
                                    # owner is likely a username string; try to resolve to user id via auth-service
                                    owner_name = listing_data.get("owner")
                                    if owner_name:
                                        try:
                                            ar = requests.get(f"{AUTH_URL}/auth/users/{owner_name}", timeout=5)
                                            if ar.ok:
                                                au = ar.json() or {}
                                                # public endpoint may return id now (see auth-service change)
                                                owner_id = au.get("id")
                                        except Exception:
                                            owner_id = None
                                if owner_id:
                                    try:
                                        payload["seller_id"] = int(owner_id)
                                        # Also update item seller_id for consistency
                                        first_item["seller_id"] = int(owner_id)
                                    except Exception:
                                        pass
                        except Exception:
                            pass  # Silently skip enrichment on error
                    elif existing_seller:
                        payload["seller_id"] = existing_seller
        
        r = requests.post(
            f"{PAYMENT_URL}/payment/create",
            json=payload,
            headers={**_forward_auth_headers(), "Content-Type": "application/json"},
            timeout=10
        )
        ctype = r.headers.get("content-type") or "application/json"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException as e:
        return jsonify(error="payment_upstream_unreachable", detail=str(e)), 502

@app.route("/payment/checkout/<int:payment_id>", methods=["GET", "POST"])
def gw_payment_checkout(payment_id: int):
    """
    Proxy trang Checkout (GET hiển thị form / POST confirm tạo invoice)
    """
    try:
        if request.method == "GET":
            r = requests.get(
                f"{PAYMENT_URL}/payment/checkout/{payment_id}",
                headers=_forward_auth_headers(),
                timeout=12,
            )
        else:
            # POST confirm từ form checkout
            # Hỗ trợ cả form-urlencoded & application/json
            if (request.content_type or "").startswith("application/json"):
                r = requests.post(
                    f"{PAYMENT_URL}/payment/checkout/{payment_id}",
                    json=request.get_json(silent=True) or {},
                    headers={**_forward_auth_headers(), "Content-Type": "application/json"},
                    timeout=15,
                )
            else:
                r = requests.post(
                    f"{PAYMENT_URL}/payment/checkout/{payment_id}",
                    data=request.form,
                    headers=_forward_auth_headers(),
                    timeout=15,
                )
        ctype = r.headers.get("content-type") or "text/html"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException as e:
        return Response(f"Payment upstream error: {e}", status=502)

@app.get("/payment/invoice/<path:contract_id>")
def gw_payment_invoice(contract_id: str):
    """Proxy trang invoice"""
    try:
        r = requests.get(
            f"{PAYMENT_URL}/payment/invoice/{contract_id}",
            headers=_forward_auth_headers(),
            timeout=12,
        )
        ctype = r.headers.get("content-type") or "text/html"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException as e:
        return Response(f"Payment upstream error: {e}", status=502)

@app.post("/payment/simulate/<int:payment_id>")
def gw_payment_simulate(payment_id: int):
    """Tiện test: đặt trạng thái đã thanh toán (nếu upstream có)."""
    try:
        r = requests.post(
            f"{PAYMENT_URL}/payment/simulate/{payment_id}",
            headers=_forward_auth_headers(),
            timeout=10,
        )
        ctype = r.headers.get("content-type") or "application/json"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException as e:
        return jsonify(error="payment_upstream_unreachable", detail=str(e)), 502
# ==== Catch-all proxy cho mọi đường /payment/* ====
import os, requests
from flask import request, Response, jsonify

PAYMENT_URL = os.getenv("PAYMENT_URL", "http://payment_service:5003")
ADMIN_TOKEN  = os.getenv("ADMIN_TOKEN", "changeme-super-admin-token")

@app.route("/payment/<path:subpath>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def proxy_payment_catchall(subpath):
    """
    Proxy mọi request /payment/* sang payment-service (500x/compose).
    Các route cụ thể (nếu có) sẽ được Flask match trước; cái này là lưới an toàn.
    """
    upstream = f"{PAYMENT_URL}/payment/{subpath}"

    headers = {k: v for k, v in request.headers if k.lower() != "host"}

    # nếu là đường admin/* và phía payment yêu cầu X-Admin-Token, thì tự chèn
    if subpath.startswith("admin/") and "X-Admin-Token" not in headers:
        headers["X-Admin-Token"] = ADMIN_TOKEN

    try:
        resp = requests.request(
            method=request.method,
            url=upstream,
            params=request.args,
            data=request.get_data(),
            headers=headers,
            cookies=request.cookies,
            allow_redirects=False,
            timeout=20,
        )
    except requests.RequestException as e:
        return jsonify(error="payment_upstream_unreachable", detail=str(e)), 502

    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    out_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
    return Response(resp.content, resp.status_code, out_headers)

# --------- Đường dẫn ngắn /checkout ----------
@app.get("/checkout")
def short_checkout_query():
    """
    Hỗ trợ: /checkout?payment_id=123 hoặc ?id=123
    """
    pid = request.args.get("payment_id") or request.args.get("id")
    if pid and str(pid).isdigit():
        return redirect(url_for("gw_payment_checkout", payment_id=int(pid)))
    # Không truyền id thì thông báo rõ cách dùng
    return Response("Thiếu payment_id. Dùng /checkout?payment_id=<id> hoặc /checkout/<id>", status=400)

@app.get("/checkout/<int:payment_id>")
def short_checkout(payment_id: int):
    return redirect(url_for("gw_payment_checkout", payment_id=payment_id))

# --- Admin reports / approve / reject (proxy qua payment-service) ---
GATEWAY_ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", os.getenv("GATEWAY_ADMIN_TOKEN", "changeme-super-admin-token"))

@app.get("/payment/admin/reports")
def gw_payment_admin_reports():
    """Proxy danh sách giao dịch cho trang Admin"""
    try:
        r = requests.get(f"{PAYMENT_URL}/payment/admin/reports",
                 headers=_forward_admin_headers(), timeout=10)
        ctype = r.headers.get("content-type") or "application/json"

        # Try to parse JSON so we can enrich with buyer/seller display names when
        # the current session is admin. If parsing fails, return raw upstream body.
        try:
            payload = r.json()
        except Exception:
            return Response(r.content, status=r.status_code, content_type=ctype)

        items = payload.get("items") or []

        # If current session is admin, attempt to fetch user list from Auth service
        # (requires admin token in session) and map ids -> username for better UX.
        user_map = {}

        # First attempt: use current admin session (forward Authorization header)
        admin_session = is_admin_session()
        print(f"[DEBUG] is_admin_session: {admin_session}, session keys: {list(session.keys())}")
        
        if admin_session:
            try:
                auth_headers = _forward_admin_headers()
                print(f"[DEBUG] Calling /auth/admin/users with headers: {auth_headers}")
                user_r = requests.get(f"{AUTH_URL}/auth/admin/users", headers=auth_headers, timeout=8)
                print(f"[DEBUG] Auth response status: {user_r.status_code}")
                if user_r.ok:
                    udata = user_r.json().get("data", [])
                    print(f"[DEBUG] Got {len(udata)} users from auth-service")
                    user_map = {int(u.get("id")): (u.get("full_name") or u.get("username") or u.get("email") or f"#{u.get('id')}") for u in udata if u.get("id") is not None}
                else:
                    print(f"[DEBUG] Auth call failed: {user_r.text[:200]}")
            except requests.RequestException as e:
                # If auth service is unreachable or token not valid, silently skip this attempt
                print(f"[DEBUG] Auth service unreachable: {e}")
                user_map = {}

        # Fallback attempt: try using an admin token from environment (useful for non-interactive sessions)
        if not user_map:
            try:
                admin_token = os.getenv("ADMIN_TOKEN") or os.getenv("GATEWAY_ADMIN_TOKEN") or os.getenv("ADMIN_TOKEN_FALLBACK")
                print(f"[DEBUG] Fallback token exists: {bool(admin_token)}, length: {len(admin_token) if admin_token else 0}")
                if admin_token:
                    hdr = {"Authorization": f"Bearer {admin_token}"}
                    user_r = requests.get(f"{AUTH_URL}/auth/admin/users", headers=hdr, timeout=8)
                    print(f"[DEBUG] Fallback auth response status: {user_r.status_code}")
                    if user_r.ok:
                        udata = user_r.json().get("data", [])
                        print(f"[DEBUG] Fallback got {len(udata)} users")
                        user_map = {int(u.get("id")): (u.get("full_name") or u.get("username") or u.get("email") or f"#{u.get('id')}") for u in udata if u.get("id") is not None}
                    else:
                        print(f"[DEBUG] Fallback auth failed: {user_r.text[:200]}")
            except Exception as e:
                print(f"[DEBUG] Fallback exception: {e}")
                user_map = {}
        
        print(f"[DEBUG] Final user_map size: {len(user_map)}")

        # Apply enrichment to items using any user_map we obtained
        if user_map:
            for it in items:
                try:
                    bid = it.get("buyer_id")
                    sid = it.get("seller_id")
                    if bid is not None:
                        it["buyer_name"] = it.get("buyer_name") or user_map.get(int(bid)) or (f"#{bid}" if bid is not None else None)
                    if sid is not None:
                        it["seller_name"] = it.get("seller_name") or user_map.get(int(sid)) or (f"#{sid}" if sid is not None else None)
                except Exception:
                    # ignore per-item enrichment failures
                    pass

        # Return the potentially-enriched items
        import json as _json
        return Response(_json.dumps({"items": items}, ensure_ascii=False).encode("utf-8"), status=r.status_code, content_type="application/json; charset=utf-8")
    except requests.RequestException as e:
        return jsonify(error="payment_upstream_unreachable", detail=str(e)), 502

@app.post("/payment/admin/approve/<int:payment_id>")
def gw_payment_admin_approve(payment_id: int):
    """Proxy duyệt giao dịch, sau đó đánh dấu listing đã bán"""
    try:
        # Approve payment
        r = requests.post(f"{PAYMENT_URL}/payment/admin/approve/{payment_id}",
                  headers={**_forward_admin_headers(),
                                   "X-Admin-Token": GATEWAY_ADMIN_TOKEN},
                          timeout=10)
        
        if r.ok:
            # Get payment details to retrieve stored items and mark listings as sold
            try:
                pr = requests.get(
                    f"{PAYMENT_URL}/payment/{payment_id}",
                    headers=_forward_admin_headers(),
                    timeout=5,
                )
                if pr.ok:
                    payment_data = pr.json()
                    items = payment_data.get("items") or []
                    processed_ids = set()

                    # Prefer explicit items payload to determine listing IDs
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        item_id = item.get("item_id") or item.get("id")
                        if item_id is None:
                            continue
                        try:
                            listing_id = int(item_id)
                        except Exception:
                            continue
                        if listing_id in processed_ids:
                            continue
                        processed_ids.add(listing_id)
                        try:
                            mark_resp = requests.put(
                                f"{LISTING_URL}/listings/{listing_id}/mark_sold",
                                headers=_forward_admin_headers(),
                                timeout=5,
                            )
                            print(
                                f"[DEBUG] Marked listing {listing_id} as sold: {mark_resp.status_code}"
                            )
                        except Exception as exc:
                            print(f"[DEBUG] Failed to mark listing {listing_id}: {exc}")

                    # Fallback: attempt to parse listing IDs from order_id if no items present
                    if not processed_ids:
                        order_id = payment_data.get("order_id", "")
                        if order_id.startswith("ORD-"):
                            import re

                            for listing_id_str in re.findall(r"\d+", order_id[4:]):
                                try:
                                    listing_id = int(listing_id_str)
                                except Exception:
                                    continue
                                if listing_id in processed_ids:
                                    continue
                                try:
                                    mark_resp = requests.put(
                                        f"{LISTING_URL}/listings/{listing_id}/mark_sold",
                                        headers=_forward_admin_headers(),
                                        timeout=5,
                                    )
                                    processed_ids.add(listing_id)
                                    print(
                                        f"[DEBUG] Marked listing {listing_id} via fallback: {mark_resp.status_code}"
                                    )
                                except Exception as exc:
                                    print(f"[DEBUG] Fallback failed for listing {listing_id}: {exc}")
            except Exception as e:
                print(f"[DEBUG] Failed to mark listings as sold: {e}")
                # Payment approved but listing mark failed — do not block response
        
        ctype = r.headers.get("content-type") or "application/json"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException as e:
        return jsonify(error="payment_upstream_unreachable", detail=str(e)), 502

@app.post("/payment/admin/reject/<int:payment_id>")
def gw_payment_admin_reject(payment_id: int):
    """Proxy từ chối giao dịch"""
    try:
        r = requests.post(f"{PAYMENT_URL}/payment/admin/reject/{payment_id}",
                  headers={**_forward_admin_headers(),
                                   "X-Admin-Token": GATEWAY_ADMIN_TOKEN},
                          timeout=10)
        ctype = r.headers.get("content-type") or "application/json"
        return Response(r.content, status=r.status_code, content_type=ctype)
    except requests.RequestException as e:
        return jsonify(error="payment_upstream_unreachable", detail=str(e)), 502
    
@app.route("/auth/<path:path>")
def proxy_auth(path):
    target = f"http://auth_service:5001/auth/{path}"
    resp = requests.request(
        method=request.method,
        url=target,
        headers={k: v for k, v in request.headers if k.lower() != "host"},
        allow_redirects=False
    )
    excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
    headers = [(name, value) for (name, value) in resp.raw.headers.items() if name.lower() not in excluded_headers]
    response = Response(resp.content, resp.status_code, headers)
    return response


@app.get("/debug/session")
def debug_session():
    """Dev-only: return the entire Flask session (as JSON) when debug mode
    is enabled. Prevent exposing this in production by requiring an env var.
    """
    if not GATEWAY_DEBUG_SESSION:
        return Response("Not found", status=404)
    # Possible sensitive values: access_token. Mask a bit for convenience.
    try:
        safe = dict(session)
        if "access_token" in safe:
            safe["access_token"] = (safe["access_token"][:8] + "..." ) if safe["access_token"] else None
        return jsonify({"session": safe})
    except Exception:
        return jsonify({"session": None}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
