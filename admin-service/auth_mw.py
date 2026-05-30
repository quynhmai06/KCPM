from flask import request, jsonify
import jwt, os

SECRET = os.getenv("JWT_SECRET", "devsecret")

def require_admin(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "missing_token"}), 401
        token = auth.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        except Exception:
            return jsonify({"error": "invalid_token"}), 401

        if payload.get("role") != "admin":
            return jsonify({"error": "not_admin"}), 403

        return func(*args, **kwargs)
    return wrapper
