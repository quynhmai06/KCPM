import os, requests
from flask import Blueprint, request
from auth_mw import require_admin

# Khi chạy local, nên để 127.0.0.1 thay vì auth_service (docker)
AUTH_URL = os.getenv("AUTH_URL", "http://127.0.0.1:5001")

bp_users = Blueprint("admin_users", __name__, url_prefix="/admin/users")

def fwd_headers():
    # forward token admin từ request gốc
    auth = request.headers.get("Authorization", "")
    return {"Authorization": auth} if auth else {}

@bp_users.get("/")
@require_admin
def list_users():
    try:
        r = requests.get(f"{AUTH_URL}/auth/admin/users",
                         headers=fwd_headers(), timeout=6)
        return (r.json(), r.status_code) if r.ok else ({"error":"auth_upstream","detail":r.text}, r.status_code)
    except requests.RequestException as e:
        return {"error":"upstream_unreachable","detail":str(e)}, 502

@bp_users.patch("/<int:user_id>/status")
@require_admin
def update_user_status(user_id: int):
    body = request.get_json(silent=True) or {}
    status = str(body.get("status","")).lower()
    if status not in {"approved","locked"}:
        return {"error":"invalid_status"}, 400
    try:
        r = requests.patch(f"{AUTH_URL}/auth/users/{user_id}/status",
                           json={"status": status},
                           headers=fwd_headers(), timeout=6)
        return (r.json(), r.status_code) if r.ok else ({"error":"auth_upstream","detail":r.text}, r.status_code)
    except requests.RequestException as e:
        return {"error":"upstream_unreachable","detail":str(e)}, 502
