import os, requests
from flask import Blueprint, jsonify
from auth_mw import require_admin

LISTINGS_URL = os.getenv("LISTINGS_URL", "http://listings_service:5005")
ORDERS_URL   = os.getenv("ORDERS_URL",   "http://orders_service:5006")
bp_stats = Blueprint("admin_stats", __name__, url_prefix="/admin/stats")

@bp_stats.get("/overview")
@require_admin
def overview():
    try:
        r1 = requests.get(f"{ORDERS_URL}/orders/summary", timeout=6)    # tổng giao dịch, doanh thu
        r2 = requests.get(f"{LISTINGS_URL}/posts/summary", timeout=6)   # tổng tin, đã kiểm định, bị từ chối
        data = {
            "orders": r1.json() if r1.ok else {"error": "orders_upstream"},
            "posts":  r2.json() if r2.ok else {"error": "listings_upstream"},
        }
        status = 200 if (r1.ok or r2.ok) else 502
        return jsonify(data), status
    except requests.RequestException as e:
        return {"error":"upstream_unreachable","detail":str(e)}, 502
