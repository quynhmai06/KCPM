"""
conftest.py cho payment-service white-box test.

Dùng cho:
    payment-service/tests/test_payment_whitebox.py

Chạy từ thư mục payment-service:
    python -m pytest -q tests/test_payment_whitebox.py
"""

import os
import sys
import time
from pathlib import Path

import pytest


# Cho phép import app.py, db.py, models.py, routes.py
BASE_DIR = Path(__file__).resolve().parents[1]

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


@pytest.fixture(scope="session")
def app():
    """
    Khởi tạo Flask app test.

    White-box test dùng trực tiếp create_app()
    thay vì gọi API qua localhost.
    """
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ.setdefault("JWT_SECRET", "supersecret")
    os.environ.setdefault("JWT_ALGO", "HS256")
    os.environ.setdefault("PAYMENT_PUBLIC_BASE", "http://localhost:5008")

    from app import create_app
    from db import db

    flask_app = create_app()

    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JSON_AS_ASCII=False,
    )

    with flask_app.app_context():
        db.drop_all()
        db.create_all()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """
    Flask test client.
    """
    return app.test_client()


@pytest.fixture
def db_session(app):
    """
    DB session dùng khi cần kiểm tra trực tiếp model.
    """
    from db import db

    with app.app_context():
        yield db.session
        db.session.rollback()
        db.session.remove()


@pytest.fixture(autouse=True)
def clean_database(app):
    """
    Làm sạch database trước mỗi test case.
    Giúp test độc lập, không phụ thuộc thứ tự chạy.
    """
    from db import db

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

    yield

    with app.app_context():
        db.session.remove()


@pytest.fixture
def unique_order_id():
    """
    Sinh order_id duy nhất.
    """
    return f"ORD-WB-{int(time.time() * 1000)}"


@pytest.fixture
def invalid_payment_id():
    """
    payment_id chắc chắn không tồn tại trong DB test.
    """
    return 999999


@pytest.fixture
def max_amount():
    return 1_000_000_000


@pytest.fixture
def valid_create_payload(unique_order_id):
    """
    Payload hợp lệ cho POST /payment/create.

    Dùng cho luồng hợp lệ và làm base để chỉnh từng nhánh lỗi.
    """
    return {
        "order_id": unique_order_id,
        "buyer_id": 1,
        "seller_id": 2,
        "amount": 50_000_000,
        "method": "banking",
        "items": [
            {
                "item_id": 10,
                "title": "Pin LFP 60V 20Ah",
                "price": 50_000_000,
                "quantity": 1,
                "seller_id": 2,
                "thumbnail": "pin-lfp.png",
            }
        ],
    }


@pytest.fixture
def valid_confirm_payload():
    """
    Payload hợp lệ cho POST /payment/confirm/<payment_id>.
    """
    return {
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
        "email": "buyer@example.com",
        "address": "TP Hồ Chí Minh",
        "method": "banking",
        "product_name": "Pin LFP 60V 20Ah",
        "confirmed": True,
    }


@pytest.fixture
def create_payment(client, valid_create_payload):
    """
    Helper tạo payment.

    Ví dụ:
        response = create_payment()
        response = create_payment(amount=1)
        response = create_payment(method="transfer")
        response = create_payment(order_id="")
    """

    def _create(**overrides):
        payload = valid_create_payload.copy()
        payload["items"] = [
            item.copy() for item in valid_create_payload["items"]
        ]

        payload.update(overrides)

        # Đồng bộ items với seller_id/amount nếu test có override.
        if payload.get("items"):
            if "seller_id" in overrides:
                payload["items"][0]["seller_id"] = overrides["seller_id"]

            if "amount" in overrides:
                payload["items"][0]["price"] = overrides["amount"]

        return client.post(
            "/payment/create",
            json=payload,
        )

    return _create


@pytest.fixture
def payment_response(create_payment):
    """
    Tạo payment hợp lệ và trả về response.
    """
    response = create_payment()
    assert response.status_code == 201, response.get_data(as_text=True)
    return response


@pytest.fixture
def payment_id(payment_response):
    """
    Tạo payment hợp lệ và trả về payment_id.
    """
    data = payment_response.get_json()

    assert data is not None
    assert "payment_id" in data
    assert data["payment_id"] > 0

    return data["payment_id"]


@pytest.fixture
def payment_model(app, payment_id):
    """
    Trả về object Payment trong DB.
    Dùng cho white-box test cần kiểm tra DB state.
    """
    from models import Payment

    with app.app_context():
        return Payment.query.get(payment_id)


@pytest.fixture
def confirm_payment(client, payment_id, valid_confirm_payload):
    """
    Helper confirm payment.

    Ví dụ:
        response = confirm_payment()
        response = confirm_payment(method="cash")
        response = confirm_payment(full_name="")
        response = confirm_payment(target_payment_id=999999)
    """

    def _confirm(target_payment_id=None, **overrides):
        pid = target_payment_id if target_payment_id is not None else payment_id

        payload = valid_confirm_payload.copy()
        payload.update(overrides)

        return client.post(
            f"/payment/confirm/{pid}",
            json=payload,
        )

    return _confirm


@pytest.fixture
def confirmed_payment_response(confirm_payment):
    """
    Confirm payment hợp lệ và trả về response.
    """
    response = confirm_payment()
    assert response.status_code == 200, response.get_data(as_text=True)
    return response


@pytest.fixture
def confirmed_payment_data(confirmed_payment_response):
    """
    Trả về JSON sau khi confirm payment thành công.
    """
    data = confirmed_payment_response.get_json()

    assert data is not None
    assert data.get("message") == "invoice_ready"
    assert data.get("invoice_id") is not None
    assert data.get("sale_contract_id") is not None

    return data
@pytest.fixture
def valid_contract_payload(payment_id):
    return {
        "payment_id": payment_id,
        "product_info": {
            "details": "Pin LFP 60V 20Ah"
        },
        "buyer_info": {
            "name": "Nguyễn Văn A",
            "email": "buyer@example.com",
            "phone": "0901234567"
        },
        "seller_info": {
            "name": "Trần Văn B",
            "email": "seller@example.com",
            "phone": "0907654321"
        },
        "cart_items": []
    }
@pytest.fixture
def create_contract_from_payment(client, valid_contract_payload):

    def _create(**overrides):

        payload = valid_contract_payload.copy()
        payload.update(overrides)

        return client.post(
            "/payment/contract/create-from-payment",
            json=payload,
        )

    return _create
@pytest.fixture
def contract_id(create_contract_from_payment):

    response = create_contract_from_payment()

    assert response.status_code in (200, 201)

    return response.get_json()["contract_id"]
@pytest.fixture
def valid_signature_payload():

    return {
        "signer_role": "buyer",
        "signature_type": "text",
        "signature_data": "Nguyễn Văn A"
    }
@pytest.fixture
def sign_contract(
    client,
    contract_id,
    valid_signature_payload,
):

    def _sign(**overrides):

        payload = valid_signature_payload.copy()
        payload.update(overrides)

        return client.post(
            f"/payment/contract/sign/{contract_id}",
            json=payload,
        )

    return _sign
