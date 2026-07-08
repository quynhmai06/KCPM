import os
import sys
from pathlib import Path
from datetime import datetime

import pytest


# Đảm bảo pytest import được app.py, db.py, models.py, routes.py
# khi chạy từ root project: pytest reviews-service/tests
SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """
    Tạo Flask app dùng SQLite riêng cho white-box test.
    Không dùng DB thật để tránh ảnh hưởng dữ liệu dự án.
    """
    db_dir = tmp_path_factory.mktemp("reviews_test_db")
    db_path = db_dir / "reviews_test.db"

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["REVIEWS_DEV_ALLOW"] = "1"
    os.environ["AUTH_URL"] = "http://auth-service-test"
    os.environ["LISTING_URL"] = "http://listing-service-test"
    os.environ["PAYMENT_BASE_URL"] = "http://payment-service-test"

    from app import app as flask_app
    from db import db

    flask_app.config.update(TESTING=True)

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def clean_database(app):
    """
    Reset database trước mỗi test case để các test độc lập với nhau.
    """
    from db import db

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

    yield

    with app.app_context():
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def seed_review(app):
    """
    Helper tạo sẵn review trong DB.
    Dùng cho test reply và filter.
    """
    def _seed_review(
        product_id=1,
        buyer_id=1,
        seller_id=2,
        rating=5,
        comment="Review seed",
    ):
        from db import db
        from models import Review

        now = datetime.utcnow()

        with app.app_context():
            review = Review(
                product_id=product_id,
                buyer_id=buyer_id,
                seller_id=seller_id,
                rating=rating,
                comment=comment,
                created_at=now,
                updated_at=now,
            )
            db.session.add(review)
            db.session.commit()
            return review.id

    return _seed_review