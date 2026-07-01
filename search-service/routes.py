from flask import Blueprint, request, jsonify
from models import db, Product, ItemType
import json
from sqlalchemy import cast, Float

bp = Blueprint("search", __name__, url_prefix="/search")

MAX_KEYWORD_LEN = 180
MAX_PRICE = 10_000_000_000


def bad_request(message, field=None, code="invalid_query"):
    payload = {
        "error": message,
        "code": code
    }
    if field:
        payload["field"] = field
    return jsonify(payload), 400


def parse_int_strict(value, field, minv=None, maxv=None):
    """
    Parse số nguyên theo kiểu strict:
    - Không truyền hoặc chuỗi rỗng => None
    - Sai kiểu / ngoài biên => raise ValueError
    """
    if value is None or value == "":
        return None

    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer")

    if minv is not None and n < minv:
        raise ValueError(f"{field} must be greater than or equal to {minv}")

    if maxv is not None and n > maxv:
        raise ValueError(f"{field} must be less than or equal to {maxv}")

    return n


def parse_float_strict(value, field, minv=None, maxv=None):
    """
    Parse số thực theo kiểu strict:
    - Không truyền hoặc chuỗi rỗng => None
    - Sai kiểu / ngoài biên => raise ValueError
    """
    if value is None or value == "":
        return None

    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")

    if minv is not None and n < minv:
        raise ValueError(f"{field} must be greater than or equal to {minv}")

    if maxv is not None and n > maxv:
        raise ValueError(f"{field} must be less than or equal to {maxv}")

    return n


# Giữ lại hàm cũ nếu chỗ khác còn import, nhưng logic chính dùng strict parser phía trên.
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
    except Exception:
        return default


def parse_float(v, default=None, minv=None, maxv=None):
    if v is None or v == "":
        return default
    try:
        n = float(v)
        if minv is not None and n < minv:
            return default
        if maxv is not None and n > maxv:
            return default
        return n
    except Exception:
        return default


def to_json(p: Product):
    # Chuyển Enum sang string nếu cần
    item_type_val = p.item_type.value if hasattr(p.item_type, "value") else str(p.item_type)
    status_val = p.status.value if hasattr(p, "status") and hasattr(p.status, "value") else getattr(p, "status", "pending")

    return {
        "id": p.id,
        "item_type": item_type_val,
        "product_type": item_type_val,  # Backward compatibility
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "brand": p.brand,
        "province": p.province,
        "year": p.year,
        "mileage": p.mileage,
        "battery_capacity": p.battery_capacity,
        "owner": p.owner,
        "main_image_url": p.main_image_url,
        "sub_image_urls": json.loads(p.sub_image_urls or "[]"),
        "approved": p.approved,
        "status": status_val,
        "verified": getattr(p, "verified", False),
        "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "approved_by": p.approved_by,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@bp.get("/")
def health():
    return {"service": "search", "status": "ok"}


@bp.get("/listings")
def search_products():
    return do_search(request.args)


def normalize_product_type(args):
    """
    Hỗ trợ cả item_type và product_type.
    - product_type=car được chuẩn hóa thành vehicle.
    - Chỉ cho phép vehicle/battery.
    """
    product_type = args.get("product_type") or args.get("item_type")

    if product_type is None or product_type == "":
        return None

    product_type = str(product_type).strip().lower()

    if product_type == "car":
        product_type = "vehicle"

    if product_type not in {"vehicle", "battery"}:
        raise ValueError("item_type must be vehicle or battery")

    return product_type


def do_search(args):
    """Core search logic extracted so other endpoints can call with modified args mapping."""

    # =========================
    # Validate query parameters
    # =========================

    kw = args.get("q", "").strip()
    if len(kw) > MAX_KEYWORD_LEN:
        return bad_request("q length must be less than or equal to 180", "q")

    try:
        product_type = normalize_product_type(args)

        min_price = parse_int_strict(
            args.get("min_price"),
            "min_price",
            minv=0,
            maxv=MAX_PRICE
        )

        max_price = parse_int_strict(
            args.get("max_price"),
            "max_price",
            minv=0,
            maxv=MAX_PRICE
        )

        if min_price is not None and max_price is not None and min_price > max_price:
            return bad_request("min_price must be less than or equal to max_price", "price_range")

        # Các validate dưới đây phục vụ thêm cho /search/vehicles và /search/batteries.
        year_from = parse_int_strict(args.get("year_from"), "year_from", minv=1990, maxv=2026)
        year_to = parse_int_strict(args.get("year_to"), "year_to", minv=1990, maxv=2026)
        if year_from is not None and year_to is not None and year_from > year_to:
            return bad_request("year_from must be less than or equal to year_to", "year_range")

        mileage_min = parse_int_strict(args.get("mileage_min"), "mileage_min", minv=0, maxv=1_000_000)
        mileage_max = parse_int_strict(args.get("mileage_max"), "mileage_max", minv=0, maxv=1_000_000)
        if mileage_min is not None and mileage_max is not None and mileage_min > mileage_max:
            return bad_request("mileage_min must be less than or equal to mileage_max", "mileage_range")

        bmin = parse_float_strict(args.get("battery_capacity_min"), "battery_capacity_min", minv=0, maxv=200)
        bmax = parse_float_strict(args.get("battery_capacity_max"), "battery_capacity_max", minv=0, maxv=200)
        if bmin is not None and bmax is not None and bmin > bmax:
            return bad_request(
                "battery_capacity_min must be less than or equal to battery_capacity_max",
                "battery_capacity_range"
            )

        brand = args.get("brand")
        if brand is not None and len(str(brand)) > 80:
            return bad_request("brand length must be less than or equal to 80", "brand")

    except ValueError as e:
        msg = str(e)
        field = msg.split(" ")[0] if msg else None
        return bad_request(msg, field)

    q = Product.query

    # Keyword search
    if kw:
        like = f"%{kw}%"
        q = q.filter(db.or_(Product.name.ilike(like), Product.description.ilike(like)))

    # Brand
    brand = args.get("brand")
    if brand:
        q = q.filter(Product.brand.ilike(f"%{brand}%"))

    # Province
    province = args.get("province")
    if province:
        q = q.filter(Product.province == province)

    # Product type
    if product_type:
        q = q.filter(Product.item_type == ItemType(product_type))

    # Owner
    owner = args.get("owner")
    if owner:
        q = q.filter(Product.owner == owner)

    # Approved
    approved = args.get("approved")
    if approved is not None:
        q = q.filter(Product.approved == (approved in ["1", "true", "True"]))

    # Price range
    if min_price is not None:
        q = q.filter(Product.price >= min_price)

    if max_price is not None:
        q = q.filter(Product.price <= max_price)

    # Year
    if year_from is not None:
        q = q.filter(Product.year >= year_from)

    if year_to is not None:
        q = q.filter(Product.year <= year_to)

    # Mileage range
    if mileage_min is not None:
        q = q.filter(Product.mileage >= mileage_min)

    if mileage_max is not None:
        q = q.filter(Product.mileage <= mileage_max)

    # Battery capacity numeric filters (best-effort cast)
    try:
        if bmin is not None:
            q = q.filter(cast(Product.battery_capacity, Float) >= bmin)
        if bmax is not None:
            q = q.filter(cast(Product.battery_capacity, Float) <= bmax)
    except Exception:
        # Một vài DB/value không cast được thì bỏ qua filter numeric capacity.
        # Validate input vẫn đã được xử lý ở phía trên.
        pass

    # Allow textual battery_capacity contains (e.g. '87', 'kWh')
    batt_txt = args.get("battery_capacity")
    if batt_txt:
        q = q.filter(Product.battery_capacity.ilike(f"%{batt_txt}%"))

    # Sort
    sort = args.get("sort", "created_desc")
    if sort == "created_asc":
        q = q.order_by(Product.created_at.asc())
    elif sort == "price_asc":
        q = q.order_by(Product.price.asc())
    elif sort == "price_desc":
        q = q.order_by(Product.price.desc())
    else:
        q = q.order_by(Product.created_at.desc())

    # Pagination
    try:
        page = parse_int_strict(args.get("page"), "page", minv=1) or 1
        per_page = parse_int_strict(args.get("per_page"), "per_page", minv=1, maxv=50) or 12
    except ValueError as e:
        msg = str(e)
        field = msg.split(" ")[0] if msg else None
        return bad_request(msg, field)

    page_obj = q.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "items": [to_json(p) for p in page_obj.items],
        "page": page_obj.page,
        "per_page": page_obj.per_page,
        "total": page_obj.total,
        "pages": page_obj.pages,
    })


@bp.get("/vehicles")
def search_vehicles():
    """Shortcut endpoint for vehicles (item_type=vehicle)"""
    args = dict(request.args.to_dict(flat=True))
    args["item_type"] = "vehicle"
    return do_search(args)


@bp.get("/batteries")
def search_batteries():
    """Shortcut endpoint for batteries (item_type=battery)"""
    args = dict(request.args.to_dict(flat=True))
    args["item_type"] = "battery"
    return do_search(args)


# Endpoint cũ không còn cần thiết - đã thay thế bằng /search/listings
