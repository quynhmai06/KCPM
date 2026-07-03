import os
import sys
from pathlib import Path

import jwt
import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

os.environ["JWT_SECRET"] = "testsecret"

from app import create_app
from models import db, Product, ItemType


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "listing_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import routes

    routes.JWT_SECRET = "testsecret"

    class FakeAuthResponse:
        ok = True

        def json(self):
            return {"id": 1}

    monkeypatch.setattr(routes.requests, "get", lambda *args, **kwargs: FakeAuthResponse())

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_header():
    def make(username="member1", role="member"):
        token = jwt.encode(
            {"username": username, "role": role},
            "testsecret",
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture()
def allowed_province():
    import routes

    return next(iter(routes.ALLOWED_PROVINCES))


@pytest.fixture()
def valid_create_payload(allowed_province):
    return {
        "name": "VinFast VF8",
        "description": "Xe con moi",
        "price": 500000000,
        "brand": "VinFast",
        "province": allowed_province,
        "year": 2024,
        "mileage": 1000,
        "battery_capacity": "82 kWh",
        "item_type": "vehicle",
        "main_image_url": "vf8.jpg",
        "sub_image_urls": [],
    }


@pytest.fixture()
def make_product(app, allowed_province):
    def create(
        owner="member1",
        approved=False,
        name="VinFast VF8",
        item_type=ItemType.vehicle,
        main_image_url="vf8.jpg",
        sub_image_urls="[]",
    ):
        with app.app_context():
            p = Product(
                name=name,
                description="Xe test",
                price=500000000,
                brand="VinFast",
                province=allowed_province,
                year=2024,
                mileage=1000,
                battery_capacity="82 kWh",
                owner=owner,
                approved=approved,
                item_type=item_type,
                main_image_url=main_image_url,
                sub_image_urls=sub_image_urls,
            )
            db.session.add(p)
            db.session.commit()
            return p.id

    return create