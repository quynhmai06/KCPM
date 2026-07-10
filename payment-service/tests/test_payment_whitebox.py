"""
test_payment_whitebox.py cho payment-service.

Dùng fixture từ conftest.py:
- client
- create_payment
- payment_id
- confirm_payment
- invalid_payment_id
- max_amount

Chạy:
    python -m pytest -q tests/test_payment_whitebox.py
"""


# ==========================================================
# A. CREATE PAYMENT - POST /payment/create
# ==========================================================

def test_payment_create_wb_tc01_success(create_payment):
    """
    PAYMENT_CREATE_WB_TC01
    Branch: toàn bộ validate False, tạo payment thành công
    Path: PAY-CREATE-P1
    Expected: 201 Created
    """
    response = create_payment()

    assert response.status_code == 201

    data = response.get_json()
    assert data["payment_id"] > 0
    assert data["id"] == data["payment_id"]
    assert data["status"] == "pending"
    assert data["amount"] == 50000000.0
    assert "checkout_url" in data


def test_payment_create_wb_tc02_missing_order_id(create_payment):
    """
    PAYMENT_CREATE_WB_TC02
    Branch: missing required order_id
    Path: PAY-CREATE-P2
    Expected: 400
    """
    response = create_payment(order_id="")

    assert response.status_code == 400

    data = response.get_json()
    assert "error" in data
    assert "order" in str(data).lower()


def test_payment_create_wb_tc03_order_id_over_max(create_payment):
    """
    PAYMENT_CREATE_WB_TC03
    Branch: len(order_id) > 100
    Path: PAY-CREATE-P3
    Expected: 400
    """
    response = create_payment(order_id="O" * 101)

    assert response.status_code == 400

    data = response.get_json()
    assert data.get("field") == "order_id"


def test_payment_create_wb_tc04_missing_buyer_id(client, valid_create_payload):
    """
    PAYMENT_CREATE_WB_TC04
    Branch: missing buyer_id
    Path: PAY-CREATE-P4
    Expected: 400
    """
    payload = valid_create_payload.copy()
    payload.pop("buyer_id")

    response = client.post("/payment/create", json=payload)

    assert response.status_code == 400

    data = response.get_json()
    assert "buyer_id" in data["error"]


def test_payment_create_wb_tc05_buyer_id_zero(create_payment):
    """
    PAYMENT_CREATE_WB_TC05
    Branch: buyer_id <= 0
    Path: PAY-CREATE-P5
    Expected: 400
    """
    response = create_payment(buyer_id=0)

    assert response.status_code == 400

    data = response.get_json()
    assert data.get("field") == "buyer_id"


def test_payment_create_wb_tc06_buyer_id_not_integer(create_payment):
    """
    PAYMENT_CREATE_WB_TC06
    Branch: _coerce_int(buyer_id) returns None
    Path: PAY-CREATE-P6
    Expected: 400
    """
    response = create_payment(buyer_id="abc")

    assert response.status_code == 400

    data = response.get_json()
    assert "buyer" in str(data).lower()


def test_payment_create_wb_tc07_missing_seller_id(client, valid_create_payload):
    """
    PAYMENT_CREATE_WB_TC07
    Branch: missing seller_id and cannot extract from items
    Path: PAY-CREATE-P7
    Expected: 400
    """
    payload = valid_create_payload.copy()
    payload.pop("seller_id")
    payload["items"] = []

    response = client.post("/payment/create", json=payload)

    assert response.status_code == 400

    data = response.get_json()
    assert "seller_id" in data["error"]


def test_payment_create_wb_tc08_seller_id_zero(create_payment):
    """
    PAYMENT_CREATE_WB_TC08
    Branch: seller_id <= 0
    Path: PAY-CREATE-P8
    Expected: 400
    """
    response = create_payment(seller_id=0)

    assert response.status_code == 400

    data = response.get_json()
    assert data.get("field") == "seller_id"


def test_payment_create_wb_tc09_seller_id_not_integer(create_payment):
    """
    PAYMENT_CREATE_WB_TC09
    Branch: _coerce_int(seller_id) returns None
    Path: PAY-CREATE-P9
    Expected: 400
    """
    response = create_payment(seller_id="abc")

    assert response.status_code == 400

    data = response.get_json()
    assert "seller" in str(data).lower()


def test_payment_create_wb_tc10_buyer_same_seller(create_payment):
    """
    PAYMENT_CREATE_WB_TC10
    Branch: buyer_id == seller_id
    Path: PAY-CREATE-P10
    Expected: 400
    """
    response = create_payment(buyer_id=5, seller_id=5)

    assert response.status_code == 400

    data = response.get_json()
    assert data.get("field") == "seller_id"


def test_payment_create_wb_tc11_missing_amount(client, valid_create_payload):
    """
    PAYMENT_CREATE_WB_TC11
    Branch: missing amount
    Path: PAY-CREATE-P11
    Expected: 400
    """
    payload = valid_create_payload.copy()
    payload.pop("amount")

    response = client.post("/payment/create", json=payload)

    assert response.status_code == 400

    data = response.get_json()
    assert "amount" in data["error"]


def test_payment_create_wb_tc12_amount_zero(create_payment):
    """
    PAYMENT_CREATE_WB_TC12
    Branch: amount <= 0
    Path: PAY-CREATE-P12
    Expected: 400
    """
    response = create_payment(amount=0)

    assert response.status_code == 400

    data = response.get_json()
    assert data.get("field") == "amount"


def test_payment_create_wb_tc13_amount_negative(create_payment):
    """
    PAYMENT_CREATE_WB_TC13
    Branch: amount <= 0
    Path: PAY-CREATE-P12
    Expected: 400
    """
    response = create_payment(amount=-1)

    assert response.status_code == 400

    data = response.get_json()
    assert data.get("field") == "amount"


def test_payment_create_wb_tc14_amount_not_number(create_payment):
    """
    PAYMENT_CREATE_WB_TC14
    Branch: _coerce_amount(amount) returns None
    Path: PAY-CREATE-P13
    Expected: 400
    """
    response = create_payment(amount="abc")

    assert response.status_code == 400

    data = response.get_json()
    assert "amount" in str(data).lower()


def test_payment_create_wb_tc15_amount_over_max(create_payment):
    """
    PAYMENT_CREATE_WB_TC15
    Branch: amount > 1_000_000_000
    Path: PAY-CREATE-P14
    Expected: 400
    """
    response = create_payment(amount=1_000_000_001)

    assert response.status_code == 400

    data = response.get_json()
    assert data.get("field") == "amount"


def test_payment_create_wb_tc16_amount_at_min(create_payment):
    """
    PAYMENT_CREATE_WB_TC16
    Branch: amount valid min
    Path: PAY-CREATE-P1
    Expected: 201
    """
    response = create_payment(amount=1)

    assert response.status_code == 201

    data = response.get_json()
    assert data["amount"] == 1.0


def test_payment_create_wb_tc17_amount_at_max(create_payment, max_amount):
    """
    PAYMENT_CREATE_WB_TC17
    Branch: amount valid max
    Path: PAY-CREATE-P1
    Expected: 201
    """
    response = create_payment(amount=max_amount)

    assert response.status_code == 201

    data = response.get_json()
    assert data["amount"] == float(max_amount)


def test_payment_create_wb_tc18_method_banking(create_payment):
    """
    PAYMENT_CREATE_WB_TC18
    Branch: raw_method in banking
    Path: PAY-CREATE-P15
    Expected: 201
    """
    response = create_payment(method="banking")

    assert response.status_code == 201


def test_payment_create_wb_tc19_method_bank_alias(create_payment):
    """
    PAYMENT_CREATE_WB_TC19
    Branch: raw_method in bank alias
    Path: PAY-CREATE-P15
    Expected: 201
    """
    response = create_payment(method="bank")

    assert response.status_code == 201


def test_payment_create_wb_tc20_method_transfer_alias(create_payment):
    """
    PAYMENT_CREATE_WB_TC20
    Branch: raw_method in transfer alias
    Path: PAY-CREATE-P15
    Expected: 201
    """
    response = create_payment(method="transfer")

    assert response.status_code == 201


def test_payment_create_wb_tc21_method_cash(create_payment):
    """
    PAYMENT_CREATE_WB_TC21
    Branch: raw_method in cash
    Path: PAY-CREATE-P16
    Expected: 201
    """
    response = create_payment(method="cash")

    assert response.status_code == 201


def test_payment_create_wb_tc22_method_ewallet(create_payment):
    """
    PAYMENT_CREATE_WB_TC22
    Branch: raw_method in e-wallet
    Path: PAY-CREATE-P17
    Expected: 201
    """
    response = create_payment(method="e-wallet")

    assert response.status_code == 201


def test_payment_create_wb_tc23_method_momo_alias(create_payment):
    """
    PAYMENT_CREATE_WB_TC23
    Branch: raw_method in e-wallet aliases
    Path: PAY-CREATE-P17
    Expected: 201
    """
    response = create_payment(method="momo")

    assert response.status_code == 201


def test_payment_create_wb_tc24_invalid_method(create_payment):
    """
    PAYMENT_CREATE_WB_TC24
    Branch: ValueError khi parse method
    Path: PAY-CREATE-P18
    Expected: 400
    """
    response = create_payment(method="bitcoin")

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "invalid method"
    assert data["raw"] == "bitcoin"


def test_payment_create_wb_tc25_seller_id_from_items(client, valid_create_payload):
    """
    PAYMENT_CREATE_WB_TC25
    Branch: seller_id lấy từ items[0].seller_id
    Path: PAY-CREATE-P19
    Expected: 201
    """
    payload = valid_create_payload.copy()
    payload.pop("seller_id")
    payload["items"] = [
        {
            "item_id": 10,
            "title": "Pin LFP 60V 20Ah",
            "price": 50000000,
            "quantity": 1,
            "seller_id": 2,
        }
    ]

    response = client.post("/payment/create", json=payload)

    assert response.status_code == 201

    data = response.get_json()
    assert data["status"] == "pending"


def test_payment_create_wb_tc26_request_body_not_object(client):
    """
    PAYMENT_CREATE_WB_TC26
    Branch: request body không phải JSON object
    Path: PAY-CREATE-P20
    Expected: 400
    """
    response = client.post(
        "/payment/create",
        json=["not", "object"],
    )

    assert response.status_code == 400

    data = response.get_json()
    assert "json object" in data["error"].lower()


# ==========================================================
# B. CONFIRM PAYMENT - POST /payment/confirm/<payment_id>
# ==========================================================

def test_payment_confirm_wb_tc01_success(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC01
    Branch: payment tồn tại, chưa có invoice, payload hợp lệ
    Path: PAY-CONFIRM-P1
    Expected: 200
    """
    response = confirm_payment()

    assert response.status_code == 200

    data = response.get_json()
    assert data["message"] == "invoice_ready"
    assert data["status"] == "pending"
    assert data["invoice_id"] > 0
    assert data["sale_contract_id"] > 0
    assert data["next_action"] == "sign_contract"
    assert data["payment_info"]["memo"]


def test_payment_confirm_wb_tc02_payment_not_found(
    confirm_payment,
    invalid_payment_id,
):
    """
    PAYMENT_CONFIRM_WB_TC02
    Branch: if not payment
    Path: PAY-CONFIRM-P2
    Expected: 404
    """
    response = confirm_payment(target_payment_id=invalid_payment_id)

    assert response.status_code == 404

    data = response.get_json()
    assert data["error"] == "not_found"


def test_payment_confirm_wb_tc03_missing_full_name(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC03
    Branch: invoice chưa có và full_name rỗng
    Path: PAY-CONFIRM-P3
    Expected: 400
    """
    response = confirm_payment(full_name="")

    assert response.status_code == 400

    data = response.get_json()
    assert "full_name" in str(data).lower()


def test_payment_confirm_wb_tc04_missing_phone(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC04
    Branch: invoice chưa có và phone rỗng
    Path: PAY-CONFIRM-P4
    Expected: 400
    """
    response = confirm_payment(phone="")

    assert response.status_code == 400

    data = response.get_json()
    assert "phone" in str(data).lower()


def test_payment_confirm_wb_tc05_method_banking(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC05
    Branch: method hợp lệ banking
    Path: PAY-CONFIRM-P1
    Expected: 200
    """
    response = confirm_payment(method="banking")

    assert response.status_code == 200

    data = response.get_json()
    assert data["payment_info"]["method"] == "banking"


def test_payment_confirm_wb_tc06_method_cash(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC06
    Branch: method hợp lệ cash
    Path: PAY-CONFIRM-P1
    Expected: 200
    """
    response = confirm_payment(method="cash")

    assert response.status_code == 200

    data = response.get_json()
    assert data["payment_info"]["method"] == "cash"


def test_payment_confirm_wb_tc07_method_ewallet(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC07
    Branch: method hợp lệ e-wallet
    Path: PAY-CONFIRM-P1
    Expected: 200
    """
    response = confirm_payment(method="e-wallet")

    assert response.status_code == 200

    data = response.get_json()
    assert data["payment_info"]["method"] == "e-wallet"


def test_payment_confirm_wb_tc08_invalid_method(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC08
    Branch: method không thuộc enum PaymentMethod
    Path: PAY-CONFIRM-P5
    Expected: 400
    """
    response = confirm_payment(method="transfer")

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "invalid method"


def test_payment_confirm_wb_tc09_create_invoice_and_sale_contract(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC09
    Branch: chưa có invoice nên tạo invoice và sale contract
    Path: PAY-CONFIRM-P6
    Expected: 200
    """
    response = confirm_payment()

    assert response.status_code == 200

    data = response.get_json()
    assert data["invoice_id"] is not None
    assert data["sale_contract_id"] is not None
    assert data["sign_url"] is not None
    assert str(data["sale_contract_id"]) in data["sign_url"]


def test_payment_confirm_wb_tc10_confirm_again_invoice_exists(
    client,
    payment_id,
    confirm_payment,
):
    """
    PAYMENT_CONFIRM_WB_TC10
    Branch: invoice đã tồn tại, không yêu cầu full_name/phone
    Path: PAY-CONFIRM-P7
    Expected: 200
    """
    first_response = confirm_payment()
    assert first_response.status_code == 200

    second_response = client.post(
        f"/payment/confirm/{payment_id}",
        json={},
    )

    assert second_response.status_code == 200

    data = second_response.get_json()
    assert data["message"] == "invoice_ready"
    assert data["invoice_id"] is not None
    assert data["sale_contract_id"] is not None


def test_payment_confirm_wb_tc11_response_payment_info(confirm_payment):
    """
    PAYMENT_CONFIRM_WB_TC11
    Branch: _payment_response build đầy đủ payment_info
    Path: PAY-CONFIRM-P8
    Expected: 200
    """
    response = confirm_payment()

    assert response.status_code == 200

    data = response.get_json()
    payment_info = data["payment_info"]

    assert "amount_vnd" in payment_info
    assert "vat_vnd" in payment_info
    assert "seller_net_vnd" in payment_info
    assert "grand_vnd" in payment_info
    assert "bank_name" in payment_info
    assert "bank_account" in payment_info
    assert "bank_owner" in payment_info
    assert "memo" in payment_info
    assert "qr_text" in payment_info
    # ==========================================================
# C. CREATE CONTRACT FROM PAYMENT
# POST /payment/contract/create-from-payment
# ==========================================================

def test_payment_contract_wb_tc01_create_contract_success(
    create_contract_from_payment,
):
    """
    PAYMENT_CONTRACT_WB_TC01
    Branch: payment_id hợp lệ, payment tồn tại, chưa có contract
    Path: PAY-CONTRACT-P1
    Expected: 201 Created
    """
    response = create_contract_from_payment()

    assert response.status_code == 201

    data = response.get_json()
    assert data["message"] == "contract_created"
    assert data["contract_id"] > 0
    assert data["contract_code"] == f"HD{data['contract_id']}"
    assert data["status"] == "pending_signature"


def test_payment_contract_wb_tc02_missing_payment_id(
    client,
    valid_contract_payload,
):
    """
    PAYMENT_CONTRACT_WB_TC02
    Branch: missing payment_id
    Path: PAY-CONTRACT-P2
    Expected: 400
    """
    payload = valid_contract_payload.copy()
    payload.pop("payment_id")

    response = client.post(
        "/payment/contract/create-from-payment",
        json=payload,
    )

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "missing payment_id"


def test_payment_contract_wb_tc03_payment_not_found(
    create_contract_from_payment,
    invalid_payment_id,
):
    """
    PAYMENT_CONTRACT_WB_TC03
    Branch: payment_id không tồn tại
    Path: PAY-CONTRACT-P3
    Expected: 404
    """
    response = create_contract_from_payment(payment_id=invalid_payment_id)

    assert response.status_code == 404

    data = response.get_json()
    assert data["error"] == "payment_not_found"


def test_payment_contract_wb_tc04_contract_already_exists(
    create_contract_from_payment,
):
    """
    PAYMENT_CONTRACT_WB_TC04
    Branch: Contract.query.filter_by(payment_id).first() tồn tại
    Path: PAY-CONTRACT-P4
    Expected: 200 contract_exists
    """
    first_response = create_contract_from_payment()
    assert first_response.status_code == 201

    second_response = create_contract_from_payment()
    assert second_response.status_code == 200

    data = second_response.get_json()
    assert data["message"] == "contract_exists"
    assert data["contract_id"] == first_response.get_json()["contract_id"]


def test_payment_contract_wb_tc05_create_with_cart_items(
    create_contract_from_payment,
):
    """
    PAYMENT_CONTRACT_WB_TC05
    Branch: if cart_items=True, lưu cart_items vào extra_data
    Path: PAY-CONTRACT-P5
    Expected: 201
    """
    response = create_contract_from_payment(
        cart_items=[
            {
                "item_id": 10,
                "title": "Pin LFP",
                "quantity": 1,
                "price": 50000000,
            }
        ]
    )

    assert response.status_code == 201

    data = response.get_json()
    assert data["message"] == "contract_created"
    assert data["status"] == "pending_signature"


def test_payment_contract_wb_tc06_create_without_product_info(
    create_contract_from_payment,
):
    """
    PAYMENT_CONTRACT_WB_TC06
    Branch: product_info thiếu -> dùng default details
    Path: PAY-CONTRACT-P6
    """
    response = create_contract_from_payment(product_info={})

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "product_info is required"
    assert data["field"] == "product"


def test_payment_contract_wb_tc07_create_without_buyer_info(
    create_contract_from_payment,
):
    """
    PAYMENT_CONTRACT_WB_TC07
    Branch: buyer_info thiếu -> dùng N/A trong content
    Path: PAY-CONTRACT-P7
    """
    response = create_contract_from_payment(buyer_info={})

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "buyer_info is required"
    assert data["field"] == "buyer"


def test_payment_contract_wb_tc08_create_without_seller_info(
    create_contract_from_payment,
):
    """
    PAYMENT_CONTRACT_WB_TC08
    Branch: seller_info thiếu -> dùng N/A trong content
    Path: PAY-CONTRACT-P8
    """
    response = create_contract_from_payment(seller_info={})

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "seller_info is required"
    assert data["field"] == "seller"


# ==========================================================
# D. SIGN CONTRACT
# POST /payment/contract/sign/<contract_id>
# ==========================================================

def test_payment_sign_wb_tc01_buyer_sign_text_success(sign_contract):
    """
    PAYMENT_SIGN_WB_TC01
    Branch: signer_role=buyer, signature_type=text
    Path: PAY-SIGN-P1
    Expected: 200
    """
    response = sign_contract(
        signer_role="buyer",
        signature_type="text",
        signature_data="Nguyễn Văn A",
    )

    assert response.status_code == 200

    data = response.get_json()
    assert data["message"] == "signature_recorded"
    assert data["buyer_signed"] is True
    assert data["seller_signed"] is False


def test_payment_sign_wb_tc02_seller_sign_text_success(
    client,
    contract_id,
    valid_signature_payload,
):
    """
    PAYMENT_SIGN_WB_TC02
    Branch: signer_role=seller, signature_type=text
    Path: PAY-SIGN-P2
    Expected: 200
    """
    payload = valid_signature_payload.copy()
    payload.update(
        {
            "signer_role": "seller",
            "signature_type": "text",
            "signature_data": "Trần Văn B",
        }
    )

    response = client.post(
        f"/payment/contract/sign/{contract_id}",
        json=payload,
    )

    assert response.status_code == 200

    data = response.get_json()
    assert data["message"] == "signature_recorded"
    assert data["buyer_signed"] is False
    assert data["seller_signed"] is True


def test_payment_sign_wb_tc03_buyer_sign_image_success(sign_contract):
    """
    PAYMENT_SIGN_WB_TC03
    Branch: signer_role=buyer, signature_type=image
    Path: PAY-SIGN-P3
    Expected: 200
    """
    response = sign_contract(
        signer_role="buyer",
        signature_type="image",
        signature_data="data:image/png;base64,AAAA",
    )

    assert response.status_code == 200

    data = response.get_json()
    assert data["buyer_signed"] is True
    assert data["seller_signed"] is False


def test_payment_sign_wb_tc04_contract_not_found(
    client,
    invalid_payment_id,
    valid_signature_payload,
):
    """
    PAYMENT_SIGN_WB_TC04
    Branch: contract không tồn tại
    Path: PAY-SIGN-P4
    Expected: 404
    """
    response = client.post(
        f"/payment/contract/sign/{invalid_payment_id}",
        json=valid_signature_payload,
    )

    assert response.status_code == 404

    data = response.get_json()
    assert data["error"] == "contract_not_found"


def test_payment_sign_wb_tc05_missing_signer_role(sign_contract):
    """
    PAYMENT_SIGN_WB_TC05
    Branch: signer_role không hợp lệ hoặc thiếu
    Path: PAY-SIGN-P5
    Expected: 400
    """
    response = sign_contract(signer_role=None)

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "missing_signature_data"


def test_payment_sign_wb_tc06_invalid_signer_role(sign_contract):
    """
    PAYMENT_SIGN_WB_TC06
    Branch: signer_role not in buyer/seller
    Path: PAY-SIGN-P5
    Expected: 400
    """
    response = sign_contract(signer_role="admin")

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "missing_signature_data"


def test_payment_sign_wb_tc07_missing_signature_type(sign_contract):
    """
    PAYMENT_SIGN_WB_TC07
    Branch: signature_type thiếu
    Path: PAY-SIGN-P6
    Expected: 400
    """
    response = sign_contract(signature_type=None)

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "missing_signature_data"


def test_payment_sign_wb_tc08_invalid_signature_type(sign_contract):
    """
    PAYMENT_SIGN_WB_TC08
    Branch: signature_type không thuộc text/image
    Path: PAY-SIGN-P6
    Expected: 400
    """
    response = sign_contract(signature_type="file")

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "missing_signature_data"


def test_payment_sign_wb_tc09_missing_signature_data(sign_contract):
    """
    PAYMENT_SIGN_WB_TC09
    Branch: signature_data thiếu hoặc rỗng
    Path: PAY-SIGN-P7
    Expected: 400
    """
    response = sign_contract(signature_data="")

    assert response.status_code == 400

    data = response.get_json()
    assert data["error"] == "missing_signature_data"


def test_payment_sign_wb_tc10_buyer_and_seller_signed_status_signed(
    client,
    contract_id,
    valid_signature_payload,
):
    """
    PAYMENT_SIGN_WB_TC10
    Branch: buyer_signed_at and seller_signed_at đều có
    Path: PAY-SIGN-P8
    Expected: contract_status=signed
    """
    buyer_payload = valid_signature_payload.copy()
    buyer_payload.update(
        {
            "signer_role": "buyer",
            "signature_type": "text",
            "signature_data": "Nguyễn Văn A",
        }
    )

    buyer_response = client.post(
        f"/payment/contract/sign/{contract_id}",
        json=buyer_payload,
    )

    assert buyer_response.status_code == 200

    seller_payload = valid_signature_payload.copy()
    seller_payload.update(
        {
            "signer_role": "seller",
            "signature_type": "text",
            "signature_data": "Trần Văn B",
        }
    )

    seller_response = client.post(
        f"/payment/contract/sign/{contract_id}",
        json=seller_payload,
    )

    assert seller_response.status_code == 200

    data = seller_response.get_json()

    assert data["buyer_signed"] is True
    assert data["seller_signed"] is True
    assert data["contract_status"] == "signed"
