from datetime import datetime
from pathlib import Path
import sys

import pytest
from flask import Flask


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from models import ItemType, Product, ProductStatus, db  # noqa: E402
from routes import bp  # noqa: E402


@pytest.fixture(name="app")
def _app():
    test_app = Flask("search-whitebox-tests")
    test_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(test_app)
    test_app.register_blueprint(bp)

    with test_app.app_context():
        db.create_all()
        db.session.add_all(
            [
                Product(
                    name="VinFast VF 8",
                    description="VinFast electric vehicle",
                    price=800_000_000,
                    brand="VinFast",
                    province="Hà Nội",
                    year=2024,
                    mileage=12_000,
                    battery_capacity="87 kWh",
                    owner="alice",
                    item_type=ItemType.vehicle,
                    approved=True,
                    status=ProductStatus.approved,
                    sub_image_urls="[]",
                    created_at=datetime(2024, 1, 1),
                ),
                Product(
                    name="VinFast Battery 60",
                    description="Replacement battery pack",
                    price=120_000_000,
                    brand="VinFast",
                    province="Hà Nội",
                    year=2022,
                    mileage=0,
                    battery_capacity="60",
                    owner="bob",
                    item_type=ItemType.battery,
                    approved=True,
                    status=ProductStatus.approved,
                    sub_image_urls="[]",
                    created_at=datetime(2024, 1, 2),
                ),
                Product(
                    name="Tesla Model 3",
                    description="Used electric vehicle",
                    price=900_000_000,
                    brand="Tesla",
                    province="TP Hồ Chí Minh",
                    year=2019,
                    mileage=60_000,
                    battery_capacity="75",
                    owner="alice",
                    item_type=ItemType.vehicle,
                    approved=False,
                    status=ProductStatus.pending,
                    sub_image_urls="[]",
                    created_at=datetime(2024, 1, 3),
                ),
                Product(
                    name="Legacy Battery 45",
                    description="Used battery pack",
                    price=50_000_000,
                    brand="Other",
                    province="Đà Nẵng",
                    year=2018,
                    mileage=100_000,
                    battery_capacity="45",
                    owner="charlie",
                    item_type=ItemType.battery,
                    approved=False,
                    status=ProductStatus.pending,
                    sub_image_urls="[]",
                    created_at=datetime(2024, 1, 4),
                ),
            ]
        )
        db.session.commit()

        yield test_app

        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture(name="client")
def _client(app):
    return app.test_client()
