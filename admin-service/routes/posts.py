import os, requests
from flask import Blueprint, jsonify, request
from auth_mw import require_admin

LISTINGS_URL = os.getenv("LISTINGS_URL", "http://listings_service:5005")
bp_posts = Blueprint("admin_posts", __name__, url_prefix="/admin/posts")

@bp_posts.get("/")
@require_admin
def list_posts():
    # có thể nhận query: status, q, page, size...
    try:
        r = requests.get(f"{LISTINGS_URL}/posts", params=request.args, timeout=6)
        return (r.json(), r.status_code) if r.ok else ({"error":"listings_upstream","detail":r.text}, r.status_code)
    except requests.RequestException as e:
        return {"error":"upstream_unreachable","detail":str(e)}, 502

@bp_posts.patch("/<string:post_id>/moderate")
@require_admin
def moderate_post(post_id: str):
    """
    Body: { "action": "approve|reject|flag_spam|mark_verified", "reason": "..." }
    """
    body = request.get_json(force=True)
    action = str(body.get("action","")).lower()
    if action not in {"approve","reject","flag_spam","mark_verified"}:
        return {"error":"invalid_action"}, 400
    try:
        r = requests.patch(f"{LISTINGS_URL}/posts/{post_id}/moderate", json=body, timeout=6)
        return (r.json(), r.status_code) if r.ok else ({"error":"listings_upstream","detail":r.text}, r.status_code)
    except requests.RequestException as e:
        return {"error":"upstream_unreachable","detail":str(e)}, 502
