from flask import Blueprint, request, jsonify
from models import db, Product
import json
from sqlalchemy import cast, Float

bp = Blueprint("search", __name__, url_prefix="/search")


def parse_int(v, default=None, minv=None, maxv=None):
    if v is None or v == "": return default
    try:
        n = int(v)
        if minv is not None and n < minv: return default
        if maxv is not None and n > maxv: return default
        return n
    except:
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
    except:
        return default

def to_json(p: Product):
    # Chuyển Enum sang string nếu cần
    item_type_val = p.item_type.value if hasattr(p.item_type, 'value') else str(p.item_type)
    status_val = p.status.value if hasattr(p, 'status') and hasattr(p.status, 'value') else getattr(p, 'status', 'pending')
    
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
        "verified": getattr(p, 'verified', False),
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


def do_search(args):
    """Core search logic extracted so other endpoints can call with modified args mapping."""
    q = Product.query

    # Keyword search
    kw = args.get("q", "").strip()
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

    # Product type (car/battery) - hỗ trợ cả item_type và product_type
    product_type = args.get("product_type") or args.get("item_type")
    if product_type:
        # Normalize: car -> vehicle
        if product_type.lower() == "car":
            product_type = "vehicle"
        q = q.filter(Product.item_type == product_type)

    # Owner
    owner = args.get("owner")
    if owner:
        q = q.filter(Product.owner == owner)

    # Approved
    approved = args.get("approved")
    if approved is not None:
        q = q.filter(Product.approved == (approved in ["1", "true", "True"]))

    # Price range
    min_price = parse_int(args.get("min_price"), None, 0)
    if min_price is not None:
        q = q.filter(Product.price >= min_price)

    max_price = parse_int(args.get("max_price"), None, 0)
    if max_price is not None:
        q = q.filter(Product.price <= max_price)

    # Year
    year_from = parse_int(args.get("year_from"))
    if year_from is not None:
        q = q.filter(Product.year >= year_from)

    year_to = parse_int(args.get("year_to"))
    if year_to is not None:
        q = q.filter(Product.year <= year_to)

    # Mileage range
    mileage_min = parse_int(args.get("mileage_min"))
    if mileage_min is not None:
        q = q.filter(Product.mileage >= mileage_min)
    mileage_max = parse_int(args.get("mileage_max"))
    if mileage_max is not None:
        q = q.filter(Product.mileage <= mileage_max)

    # Battery capacity numeric filters (best-effort cast)
    bmin = parse_float(args.get("battery_capacity_min"))
    bmax = parse_float(args.get("battery_capacity_max"))
    try:
        if bmin is not None:
            q = q.filter(cast(Product.battery_capacity, Float) >= bmin)
        if bmax is not None:
            q = q.filter(cast(Product.battery_capacity, Float) <= bmax)
    except Exception:
        # Some DBs or values may not cast cleanly; ignore numeric capacity filtering in that case
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
    page = parse_int(args.get("page"), 1, 1)
    per_page = parse_int(args.get("per_page"), 12, 1, 50)
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
    # Build a shallow dict from request args and force item_type
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
