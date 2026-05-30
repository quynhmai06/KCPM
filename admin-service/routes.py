import requests
from flask import Blueprint, jsonify, request

def create_bp(require_admin, auth_url: str):
    bp = Blueprint("admin_api", __name__)

    @bp.get("/users")
    @require_admin
    def list_users():
        """Lấy danh sách người dùng từ auth-service và lọc bỏ admin."""
        try:
            r = requests.get(f"{auth_url}/auth/admin/users", timeout=6)
            if not r.ok:
                return jsonify({"error": "auth_service_error", "detail": r.text}), r.status_code
            data = r.json().get("data", [])
            members = [u for u in data if not (u.get("is_admin") or str(u.get("role","")).lower() == "admin")]
            return jsonify({"data": members})
        except requests.RequestException as e:
            return jsonify({"error": "upstream_unreachable", "detail": str(e)}), 502

    @bp.patch("/users/<int:user_id>/status")
    @require_admin
    def update_user_status(user_id: int):
        """Cập nhật trạng thái user qua auth-service. Body: {status: approved|locked}"""
        body = request.get_json(silent=True) or {}
        status = str(body.get("status", "")).lower()
        if status not in {"approved", "locked"}:
            return jsonify({"error": "invalid_status"}), 400
        try:
            r = requests.patch(
                f"{auth_url}/auth/users/{user_id}/status",
                json={"status": status},
                timeout=6,
            )
            if r.ok:
                return jsonify({"ok": True})
            try:
                return jsonify(r.json()), r.status_code
            except Exception:
                return r.text, r.status_code
        except requests.RequestException as e:
            return jsonify({"error": "upstream_unreachable", "detail": str(e)}), 502

    return bp

    