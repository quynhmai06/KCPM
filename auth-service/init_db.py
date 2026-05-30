# auth-service/init_db.py
import os
from datetime import datetime
from sqlalchemy import or_
from werkzeug.security import generate_password_hash
from app import app
from models import db, User, UserProfile

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

def ensure_admin():
    """Tạo admin nếu chưa có (không xoá dữ liệu cũ)."""
    with app.app_context():
        # tạo bảng lần đầu
        db.create_all()

        print("[init_db] SQLALCHEMY_DATABASE_URI =", app.config.get("SQLALCHEMY_DATABASE_URI"))

        # đã có admin?
        existing = (
            User.query.filter(
                or_(
                    User.role == "admin",
                    User.username == ADMIN_USERNAME,
                    User.email == ADMIN_EMAIL,
                )
            )
            .order_by(User.id.asc())
            .first()
        )

        if existing:
            print(f"[init_db] Admin đã tồn tại: id={existing.id}, username={existing.username}, email={existing.email}")
            return

        # tạo mới
        admin = User(
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            password=generate_password_hash(ADMIN_PASSWORD),
            role="admin",
            approved=True,
            locked=False,
            created_at=datetime.utcnow(),
            phone="0123456789",
        )
        db.session.add(admin)
        db.session.commit()

        # hồ sơ trống đi kèm
        prof = UserProfile(user_id=admin.id)
        db.session.add(prof)
        db.session.commit()

        print(f"[init_db] ✅ Admin created: id={admin.id}, username={ADMIN_USERNAME}, email={ADMIN_EMAIL}")

if __name__ == "__main__":
    ensure_admin()
