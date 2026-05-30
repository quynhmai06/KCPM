import os
import io
import jwt
from datetime import datetime
from flask import Blueprint, jsonify, request, render_template_string, Response, redirect, url_for
from db import db
from models import (
    Payment,
    PaymentMethod,
    PaymentStatus,
    Contract,
    ContractType,
    ContractStatus,
    SignatureType,
)

# VAT mặc định 10% (có thể override bằng biến môi trường VAT_RATE)
VAT_RATE = float(os.getenv("VAT_RATE", "0.10"))

# ============ Blueprint ============
bp = Blueprint("payment", __name__, url_prefix="/payment")

# ============ CORS ============
@bp.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,PUT"
    return resp


# Ensure common python builtins are available in Jinja templates (some templates
# use `int` in expressions). We set this before each request to be safe.
@bp.before_app_request
def _ensure_jinja_globals():
    from flask import current_app
    try:
        current_app.jinja_env.globals.setdefault("int", int)
    except Exception:
        # if current_app isn't available for any reason, ignore silently
        pass


@bp.route("/<path:subpath>", methods=["OPTIONS"])
def payment_options(subpath):
    return ("", 204)


# ============ CONFIG ============
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")

BANK_NAME = os.getenv("BANK_NAME", "MB Bank")
# Mặc định thay đổi theo yêu cầu: số tài khoản mặc định được đặt thành '0359506148'
BANK_ACCOUNT = os.getenv("BANK_ACCOUNT", "0359506148")
# Tên chủ tài khoản hiển thị - dùng tên nền tảng theo yêu cầu
BANK_OWNER = os.getenv("BANK_OWNER", "Second-hand EV & Battery Trading Platform")

VAT_RATE = float(os.getenv("VAT_RATE", "0.1"))
PAYMENT_PUBLIC_BASE = os.getenv("PAYMENT_PUBLIC_BASE", "http://localhost:5008")


# ============ UTILS ============
def _commit():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _payment_json(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "order_id": payment.order_id,
        "buyer_id": payment.buyer_id,
        "seller_id": payment.seller_id,
        "amount": float(payment.amount or 0),
        "items": (
            payment.items
            if isinstance(payment.items, list)
            else (payment.items or [])
        ),
        "method": payment.method.value,
        "provider": payment.provider,
        "status": payment.status.value,
        # Ensure we return explicit UTC timestamps (append 'Z' if naive)
        "created_at": (payment.created_at.isoformat() + "Z")
        if payment.created_at and payment.created_at.tzinfo is None
        else (payment.created_at.isoformat() if payment.created_at else None),
        "updated_at": (payment.updated_at.isoformat() + "Z")
        if payment.updated_at and payment.updated_at.tzinfo is None
        else (payment.updated_at.isoformat() if payment.updated_at else None),
        "contracts": [
            {
                "id": c.id,
                "type": c.contract_type.value,
                "title": c.title,
                "signed_at": c.signed_at.isoformat() if c.signed_at else None,
            }
            for c in (payment.contracts or [])
        ],
        "checkout_url": f"/payment/checkout/{payment.id}",
    }


def _ensure_sale_contract(payment: Payment, buyer_info: dict) -> Contract:
    """
    Tạo (nếu chưa có) HỢP ĐỒNG MUA BÁN tiếng Việt đầy đủ cho payment này.
    """
    existing = next(
        (c for c in payment.contracts if c.contract_type == ContractType.DIGITAL_SALE),
        None,
    )
    if existing:
        return existing

    now = datetime.utcnow()
    ngay = now.strftime("%d/%m/%Y")
    gio = now.strftime("%H:%M")

    buyer_name = (buyer_info.get("full_name") or "(Chưa cung cấp)").strip()
    buyer_phone = (buyer_info.get("phone") or "(Chưa cung cấp)").strip()
    buyer_email = (buyer_info.get("email") or "(Chưa cung cấp)").strip()
    buyer_addr = (buyer_info.get("address") or "(Chưa cung cấp)").strip()

    # Thông tin chung
    order_id = payment.order_id
    tri_gia = f"{float(payment.amount or 0):,.0f} VND".replace(",", ".")
    phuong_thuc = "Chuyển khoản ngân hàng (VietQR/IB)"

    content = f"""
HỢP ĐỒNG MUA BÁN HÀNG HÓA (ĐIỆN TỬ)

Số: HĐMB-{payment.id:06d}     Ngày lập: {ngay} {gio} (UTC)

Căn cứ:
- Bộ luật Dân sự hiện hành; Luật Thương mại và các văn bản pháp luật liên quan.
- Nhu cầu và sự tự nguyện thỏa thuận giữa các Bên.

BÊN BÁN (Bên B): Nền tảng EV & Battery Platform
Địa chỉ: 01 Sample Road, Quận 1, TP. Hồ Chí Minh
Điện thoại: 0123 456 789
Email: support@ev-battery.example

BÊN MUA (Bên A):
- Họ và tên: {buyer_name}
- Số điện thoại: {buyer_phone}
- Email: {buyer_email}
- Địa chỉ: {buyer_addr}

ĐIỀU 1. THÔNG TIN HÀNG HÓA/GIAO DỊCH
- Mã đơn hàng: {order_id}
- Mô tả hàng hóa/dịch vụ: Theo thông tin hiển thị tại đơn mua {order_id} trên hệ thống.
- Số lượng/chủng loại: Theo đơn mua {order_id}.
- Giá trị hợp đồng (đã/hoặc chưa gồm thuế tùy cấu hình hóa đơn): {tri_gia}.

ĐIỀU 2. PHƯƠNG THỨC THANH TOÁN
- Phương thức: {phuong_thuc}.
- Nội dung chuyển khoản: PAY{payment.id}-ORD{payment.order_id}.
- Bên A chịu trách nhiệm chuyển đúng Số tiền và Nội dung theo hướng dẫn trên Hóa đơn thanh toán.

ĐIỀU 3. GIAO HÀNG VÀ CHUYỂN QUYỀN SỞ HỮU
- Thời hạn giao hàng: Trong vòng 03–05 ngày làm việc (trừ khi hai Bên có thỏa thuận khác).
- Địa điểm/Phương thức: Theo địa chỉ/thoả thuận từ Bên A trên hệ thống.
- Quyền sở hữu chuyển sang Bên A kể từ khi thanh toán đủ và hàng hóa được bàn giao.

ĐIỀU 4. BẢO HÀNH, ĐỔI TRẢ
- Chính sách bảo hành/đổi trả theo quy định công bố trên nền tảng tại thời điểm giao dịch.
- Bên A có trách nhiệm kiểm tra hàng hóa khi nhận; phản hồi trong 24 giờ nếu có sai lệch.

ĐIỀU 5. NGHĨA VỤ VÀ TRÁCH NHIỆM
- Bên B cung cấp hàng hóa đúng mô tả, đúng số lượng/chất lượng.
- Bên A thanh toán đúng hạn, đúng giá trị; cung cấp thông tin nhận hàng chính xác.

ĐIỀU 6. BẤT KHẢ KHÁNG
- Hai Bên không chịu trách nhiệm khi vi phạm do sự kiện bất khả kháng (thiên tai, dịch bệnh, quyết định cơ quan Nhà nước...).

ĐIỀU 7. GIẢI QUYẾT TRANH CHẤP
- Ưu tiên thương lượng hoà giải. Nếu không đạt, tranh chấp được giải quyết tại Tòa án có thẩm quyền tại TP. Hồ Chí Minh.

ĐIỀU 8. HIỆU LỰC HỢP ĐỒNG
- Hợp đồng có hiệu lực kể từ thời điểm hai Bên xác nhận/ký điện tử trên hệ thống.
- Hợp đồng điện tử có giá trị pháp lý tương đương bản giấy theo quy định pháp luật.

BÊN MUA (Bên A)                                 BÊN BÁN (Bên B)
Ký/ghi rõ họ tên                                Đại diện nền tảng
"""

    contract = Contract(
        payment=payment,
        contract_type=ContractType.DIGITAL_SALE,
        title=f"HỢP ĐỒNG MUA BÁN — Đơn {order_id}",
        content=content,
        created_at=datetime.utcnow(),
    )
    db.session.add(contract)
    _commit()
    return contract


def _invoice_contract(payment: Payment) -> Contract | None:
    return next(
        (c for c in (payment.contracts or []) if c.contract_type == ContractType.INVOICE),
        None,
    )

def _is_paid_like(status_str) -> bool:
    """
    Trả về True nếu status là dạng 'PAID' / 'paid' / 'completed'...
    dùng để lọc các giao dịch đã thanh toán.
    """
    if not status_str:
        return False
    s = str(status_str).strip().lower()
    return s in ("paid", "completed", "done")


def _invoice_data(payload: dict, payment: Payment) -> dict:
    return {
        # cá nhân
        "full_name": payload.get("full_name", "").strip(),
        "phone": payload.get("phone", "").strip(),
        "email": payload.get("email", "").strip(),
        "address": payload.get("address", "").strip(),
        "dob": payload.get("dob", "").strip(),  # YYYY-MM-DD
        "id_number": payload.get("id_number", "").strip(),  # CCCD/CMND
        # địa chỉ chi tiết
        "province": payload.get("province", "").strip(),
        "district": payload.get("district", "").strip(),
        "ward": payload.get("ward", "").strip(),
        # hóa đơn công ty
        "is_company_invoice": bool(payload.get("is_company_invoice")),
        "company_name": payload.get("company_name", "").strip(),
        "company_address": payload.get("company_address", "").strip(),
        "tax_code": payload.get("tax_code", "").strip(),
        # khác
        "note": payload.get("note", "").strip(),
        "product_name": payload.get("product_name", "").strip(),
        "method": payment.method.value,
        "confirmed": bool(payload.get("confirmed", False)),
    }


def _invoice_text(info: dict, payment: Payment) -> str:
    lines = [
        f"Invoice for payment #{payment.id}",
        f"Order id: {payment.order_id}",
        f"Buyer: {info.get('full_name','')}",
        f"Phone: {info.get('phone','')}",
        f"Email: {info.get('email','')}",
        f"Address: {info.get('address','')}",
    ]
    if info.get("dob"):
        lines.append(f"DOB: {info['dob']}")
    if info.get("id_number"):
        lines.append(f"ID/CCCD: {info['id_number']}")
    if info.get("province") or info.get("district") or info.get("ward"):
        lines.append(
            "Region: "
            + ", ".join(
                [
                    x
                    for x in [
                        info.get("ward"),
                        info.get("district"),
                        info.get("province"),
                    ]
                    if x
                ]
            )
        )
    if info.get("is_company_invoice"):
        lines += [
            "== VAT Invoice (Company) ==",
            f"Company: {info.get('company_name','')}",
            f"Tax code: {info.get('tax_code') or 'N/A'}",
            f"Company address: {info.get('company_address','')}",
        ]
    else:
        lines.append(f"Tax code: {info.get('tax_code') or 'N/A'}")
    lines += [
        f"Payment method: {info.get('method','')}",
        f"Amount: {float(payment.amount or 0):,.0f} VND",
        f"Created at: {datetime.utcnow().isoformat()}",
    ]
    if info.get("note"):
        lines.append(f"Note: {info['note']}")
    return "\n".join(lines)


def _payment_response(
    payment: Payment, invoice: Contract, sale_contract: Contract | None = None
) -> dict:
    # Buyer: chỉ trả đúng amount
    subtotal = float(payment.amount or 0)  # tiền khách trả (gross)
    vat = int(round(subtotal * VAT_RATE))  # VAT áp cho người bán
    seller_net = subtotal - vat  # tiền thực nhận của người bán

    # Tổng buyer phải chuyển = subtotal (không + VAT)
    total = subtotal

    memo = f"PAY{payment.id}-ORD{payment.order_id}"
    return {
        "message": "invoice_ready",
        "status": payment.status.value,
        "invoice_id": invoice.id,
        "invoice_url": f"{PAYMENT_PUBLIC_BASE}/payment/invoice/{invoice.id}",
        "payment_id": payment.id,
        "sale_contract_id": sale_contract.id if sale_contract else None,
        "sign_url": f"{PAYMENT_PUBLIC_BASE}/payment/contract/sign/{sale_contract.id}"
        if sale_contract
        else None,
        "next_action": "sign_contract",
        "payment_info": {
            "amount_vnd": f"{subtotal:,.0f} VND",  # tiền khách trả
            "vat_vnd": f"{vat:,.0f} VND",  # VAT áp cho người bán
            "seller_net_vnd": f"{seller_net:,.0f} VND",  # seller thực nhận
            "grand_vnd": f"{total:,.0f} VND",  # tổng buyer phải chuyển
            "method": payment.method.value,
            "bank_name": BANK_NAME,
            "bank_account": BANK_ACCOUNT,
            "bank_owner": BANK_OWNER,
            "memo": memo,
            "qr_text": f"{BANK_NAME}|{BANK_ACCOUNT}|{BANK_OWNER}|{memo}|{int(total)}",
        },
    }


def _coerce_int(v):
    try:
        return int(v)
    except Exception:
        return None


def _coerce_amount(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def _extract_buyer_id(data):
    cand = (
        data.get("buyer_id")
        or data.get("user_id")
        or (data.get("buyer") or {}).get("id")
    )
    if cand is not None:
        return _coerce_int(cand)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
            return _coerce_int(payload.get("user_id") or payload.get("id"))
        except Exception:
            pass
    return None


def _extract_seller_id(data):
    cand = data.get("seller_id") or (data.get("seller") or {}).get("id")
    if cand is not None:
        return _coerce_int(cand)
    items = data.get("items") or []
    if items:
        it0 = items[0] or {}
        cand = it0.get("seller_id") or (it0.get("seller") or {}).get("id")
        if cand is not None:
            return _coerce_int(cand)
    return None


# ============ BASIC ROUTES ============
@bp.get("/health")
def health():
    return {"service": "payment", "status": "ok"}


@bp.post("/create")
def create_payment():
    data = request.get_json(force=True) or {}
    buyer_id = _extract_buyer_id(data)
    seller_id = _extract_seller_id(data)
    amount = _coerce_amount(data.get("amount"))

    # Chuẩn hoá items
    def _normalize_items(raw_items):
        normalized = []
        if not isinstance(raw_items, list):
            return normalized
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            candidate = {}
            item_id = item.get("item_id") or item.get("id")
            if item_id is not None:
                try:
                    candidate["item_id"] = int(item_id)
                except Exception:
                    candidate["item_id"] = item_id
            title = item.get("title") or item.get("name")
            if title:
                candidate["title"] = str(title)
            price = item.get("price")
            coerced_price = _coerce_amount(price) if price is not None else None
            if coerced_price is not None:
                candidate["price"] = coerced_price
            quantity = item.get("quantity") or 1
            coerced_qty = _coerce_int(quantity)
            if coerced_qty is not None:
                candidate["quantity"] = coerced_qty
            seller_ref = item.get("seller_id") or (item.get("seller") or {}).get("id")
            if seller_ref is not None:
                coerced_seller = _coerce_int(seller_ref)
                if coerced_seller is not None:
                    candidate["seller_id"] = coerced_seller
            thumbnail = item.get("thumbnail") or item.get("image")
            if thumbnail:
                candidate["thumbnail"] = thumbnail
            if candidate:
                normalized.append(candidate)
        return normalized

    items_payload = _normalize_items(data.get("items"))
    data["items"] = items_payload

    if buyer_id is not None:
        data["buyer_id"] = buyer_id
    if seller_id is not None:
        data["seller_id"] = seller_id
    if amount is not None:
        data["amount"] = amount

    required = ["order_id", "buyer_id", "seller_id", "amount"]
    missing = [k for k in required if data.get(k) in (None, "", [])]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

    raw_method = (data.get("method") or PaymentMethod.E_WALLET.value).lower().strip()
    try:
        if raw_method in ("momo", "e_wallet", "ewallet", "vi", "vi_dien_tu"):
            method = PaymentMethod.E_WALLET
        elif raw_method in ("bank", "banking", "transfer"):
            method = PaymentMethod.BANKING
        elif raw_method in ("cash", "tien_mat"):
            method = PaymentMethod.CASH
        else:
            method = PaymentMethod(raw_method)
    except ValueError:
        return jsonify({"error": "invalid method", "raw": raw_method}), 400

    try:
        payment = Payment(
            order_id=str(data["order_id"]),
            buyer_id=int(data["buyer_id"]),
            seller_id=int(data["seller_id"]),
            amount=float(data["amount"]),
            items=data.get("items"),
            method=method,
            provider=data.get("provider", "Manual"),
        )
        db.session.add(payment)
        _commit()
    except Exception as e:
        # IN RA LOG SERVER CHO DỄ NHÌN
        import traceback, sys
        print("[payment.create] ERROR:", e, file=sys.stderr)
        traceback.print_exc()

        return jsonify(
            {
                "error": "payment_creation_failed",
                "detail": str(e),
                "payload": {
                    "order_id": data.get("order_id"),
                    "buyer_id": data.get("buyer_id"),
                    "seller_id": data.get("seller_id"),
                    "amount": data.get("amount"),
                    "method": method.value if isinstance(method, PaymentMethod) else str(method),
                },
            }
        ), 500

    return (
        jsonify(
            {
                "payment_id": payment.id,
                "id": payment.id,
                "order_id": payment.order_id,
                "status": payment.status.value,
                "amount": float(payment.amount),
                "checkout_url": f"/payment/checkout/{payment.id}",
            }
        ),
        201,
    )



@bp.get("/")
def list_payments():
    query = Payment.query
    buyer_id = request.args.get("buyer_id", type=int)
    seller_id = request.args.get("seller_id", type=int)
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    if buyer_id is not None:
        query = query.filter(Payment.buyer_id == buyer_id)
    if seller_id is not None:
        query = query.filter(Payment.seller_id == seller_id)
    if order_id is not None:
        query = query.filter(Payment.order_id == order_id)
    if status:
        try:
            query = query.filter(Payment.status == PaymentStatus(status))
        except ValueError:
            return jsonify({"error": "invalid status"}), 400
    items = query.order_by(Payment.created_at.desc()).limit(100).all()
    return jsonify({"items": [_payment_json(p) for p in items]})


@bp.get("/<int:payment_id>")
def get_payment(payment_id: int):
    payment = Payment.query.get(payment_id)
    if not payment:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_payment_json(payment))


@bp.get("/status/<int:payment_id>")
def get_status(payment_id: int):
    p = Payment.query.get(payment_id)
    if not p:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"id": p.id, "status": p.status.value})


@bp.post("/update_method/<int:payment_id>")
def update_method(payment_id: int):
    payment = Payment.query.get(payment_id)
    if not payment:
        return jsonify({"error": "not_found"}), 404
    data = request.get_json(force=True)
    method_value = data.get("method")
    try:
        payment.method = PaymentMethod(method_value)
    except Exception:
        return jsonify({"error": "invalid method"}), 400
    payment.updated_at = datetime.utcnow()
    _commit()
    return jsonify({"message": "updated", "method": payment.method.value})


# ============ CHECKOUT (GET hiển thị form / POST tạo invoice rồi redirect) ============
@bp.route("/checkout/<int:payment_id>", methods=["GET", "POST"])
def checkout_page(payment_id: int):
    payment = Payment.query.get(payment_id)
    if not payment:
        return "Not found", 404

    # Nếu đã có INVOICE -> chuyển thẳng sang xem hóa đơn
    inv = _invoice_contract(payment)
    if inv:
        return redirect(url_for("payment.invoice_page", contract_id=inv.id))

    if request.method == "POST":
        # Submit từ nút “Đặt hàng ngay” (tạo invoice & redirect)
        payload = {
            "full_name": request.form.get("full_name", "").strip() or "Khách hàng",
            "phone": request.form.get("phone", "").strip() or "0000000000",
            "email": request.form.get("email", "").strip(),
            "address": request.form.get("address", "").strip(),
            "product_name": request.form.get("product_name", "").strip(),
            "method": request.form.get("method", payment.method.value),
            "confirmed": True,
            # các field phụ (nếu muốn dùng sau này)
            "province": request.form.get("province", "").strip(),
            "district": request.form.get("district", "").strip(),
            "ward": request.form.get("ward", "").strip(),
            "tax_code": request.form.get("tax_code", "").strip(),
            "note": request.form.get("note", "").strip(),
            "dob": request.form.get("dob", "").strip(),
            "id_number": request.form.get("id_number", "").strip(),
            "is_company_invoice": request.form.get("is_company_invoice") == "on",
            "company_name": request.form.get("company_name", "").strip(),
            "company_address": request.form.get("company_address", "").strip(),
        }

        # Đổi phương thức nếu người dùng chọn khác
        try:
            payment.method = PaymentMethod(payload["method"])
        except (KeyError, ValueError):
            return (
                render_template_string(
                    _CHECKOUT_HTML,
                    payment=payment,
                    ui=_build_checkout_ui(payment),
                    error="Phương thức không hợp lệ",
                    bank_name=BANK_NAME,
                    bank_account=BANK_ACCOUNT,
                    bank_owner=BANK_OWNER,
                ),
                400,
            )

        # Chỉ cho phép banking
        if payment.method != PaymentMethod.BANKING:
            return (
                render_template_string(
                    _CHECKOUT_HTML,
                    payment=payment,
                    ui=_build_checkout_ui(payment),
                    error="Hiện chỉ hỗ trợ 'Chuyển khoản ngân hàng'. Vui lòng chọn lại phương thức này để tiếp tục.",
                    bank_name=BANK_NAME,
                    bank_account=BANK_ACCOUNT,
                    bank_owner=BANK_OWNER,
                ),
                400,
            )

        # Tạo invoice nếu chưa có
        inv = _invoice_contract(payment)
        if not inv:
            info = _invoice_data(payload, payment)
            inv = Contract(
                payment=payment,
                contract_type=ContractType.INVOICE,
                title=f"Invoice for payment #{payment.id}",
                content=_invoice_text(info, payment),
                extra_data=info,
                created_at=datetime.utcnow(),
            )
            db.session.add(inv)
            _commit()

        # Đảm bảo có HĐ mua bán
        _ensure_sale_contract(
            payment,
            {
                "full_name": payload["full_name"],
                "phone": payload["phone"],
                "email": payload["email"],
                "address": payload["address"],
            },
        )
        return redirect(url_for("payment.invoice_page", contract_id=inv.id))

    # GET: hiển thị trang giống screenshot
    ui = _build_checkout_ui(payment)
    # Build QR text similarly to invoice page (use checkout total, no VAT here)
    subtotal = float(payment.amount or 0)
    shipping = 0.0
    total = subtotal + shipping
    memo = f"PAY{payment.id}-ORD{payment.order_id}"
    qr_text = (
        f"{BANK_NAME}|{BANK_ACCOUNT}|{BANK_OWNER}|{memo}|{int(total)}"
    )

    return render_template_string(
        _CHECKOUT_HTML,
        payment=payment,
        ui=ui,
        error=None,
        qr_text=qr_text,
        bank_name=BANK_NAME,
        bank_account=BANK_ACCOUNT,
        bank_owner=BANK_OWNER,
    )


_CHECKOUT_HTML = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Giỏ hàng • Đặt hàng — {{ ui.product_name }}</title>
<style>
  :root{--bg:#f7f7f9;--card:#fff;--line:#e5e7eb;--brand:#ff7a45;--accent:#16a34a;--muted:#64748b;--text:#111827}
  *{box-sizing:border-box} html,body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial}
  .wrap{max-width:1120px;margin:24px auto;padding:0 12px}
  .grid{display:grid;grid-template-columns:1.2fr .8fr;gap:18px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 24px rgba(2,6,23,.05)}
  .section{padding:16px 18px;border-bottom:1px solid var(--line)}
  .section:last-child{border-bottom:none}
  h2{font-size:18px;margin:0;display:flex;align-items:center;gap:8px}
  .row{display:flex;align-items:center;gap:12px}
  .item{display:flex;gap:12px;align-items:center}
  .thumb{width:56px;height:56px;border-radius:10px;background:#f1f5f9;overflow:hidden;display:grid;place-items:center;font-size:12px;color:#94a3b8}
  .thumb img{width:100%;height:100%;object-fit:cover}
  .name{font-weight:700}
  .muted{color:var(--muted);font-size:12px}

  .pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);padding:8px 10px;border-radius:12px;background:#fff;cursor:pointer}
  .pill.active{border-color:#cbd5e1;background:#f8fafc}
  .radio{width:14px;height:14px;border:2px solid #cbd5e1;border-radius:50%;display:inline-block;position:relative}
  .pill.active .radio::after{content:"";position:absolute;top:3px;left:3px;width:6px;height:6px;border-radius:50%;background:var(--brand)}

  .field{display:grid;gap:6px}
  .label{font-size:12px;color:#475569}
  .input,.textarea,select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;outline:none}
  .textarea{min-height:84px;resize:vertical}
  .input:focus,.textarea:focus,select:focus{border-color:#94a3b8}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
  .error{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:10px 12px;border-radius:10px;margin-top:8px}
  .trust{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
  .seal{display:flex;align-items:center;gap:8px;border:1px solid var(--line);padding:8px 10px;border-radius:999px;background:#fff;font-size:12px;color:#334155}

  .summary{padding:16px 18px}
  .hr{height:1px;background:var(--line);margin:12px 0}
  .total{display:flex;justify-content:space-between;font-weight:800;font-size:18px}
  .btn{appearance:none;border:none;background:var(--brand);color:#fff;font-weight:700;border-radius:10px;padding:12px 14px;width:100%;cursor:pointer}
  .btn:disabled{opacity:.6;cursor:not-allowed}
  .safe{display:flex;align-items:center;gap:8px;color:#64748b;font-size:12px;margin-top:8px}
  @media(max-width:980px){.grid{grid-template-columns:1fr}.grid2,.grid3{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <div class="grid">

    <!-- LEFT -->
    <div class="col">
      <div class="card">
        <div class="section">
          <h2>📅 Xác nhận đơn hàng</h2>
        </div>
        <div class="section">
          <div class="item">
            <div class="thumb">
              {% if ui.product_img %}<img src="{{ ui.product_img }}" alt="product"/>{% else %} IMG {% endif %}
            </div>
            <div style="flex:1">
              <div class="name">{{ ui.product_name }}</div>
              <div class="muted">📍 {{ ui.province or '—' }}</div>
            </div>
            <div style="font-weight:700">{{ "{:,.0f}".format(ui.subtotal).replace(",", ".") }} đ</div>
          </div>
        </div>

        <!-- PAYMENT METHOD -->
        <div class="section">
          <h2>💳 Phương thức thanh toán</h2>
          <div style="margin-top:10px;display:grid;gap:10px">
            {% for m in ui.methods %}
            <label class="pill {% if ui.current_method==m.key %}active{% endif %}">
              <span class="radio"></span>
              <span style="font-size:18px">{{ m.icon }}</span>
              <span style="font-weight:700">{{ m.label }}</span>
              <span class="muted">— {{ m.desc }}</span>
              <input type="radio" name="method_fake" value="{{ m.key }}" style="display:none" {% if ui.current_method==m.key %}checked{% endif %} />
            </label>
            {% endfor %}
            <div class="muted">Chọn phương thức bằng cách nhấn vào ô trên (mặc định: ngân hàng).</div>
          </div>
        </div>

        <!-- BUYER INFO -->
        <div class="section">
          <h2>🧑‍💼 Thông tin người mua</h2>
          {% if error %}<div class="error">{{ error }}</div>{% endif %}

          <div class="grid2" style="margin-top:10px">
            <div class="field">
              <label class="label">Họ và tên *</label>
              <input class="input" name="full_name" form="orderForm" placeholder="Ví dụ: Nguyễn Văn A" required>
            </div>
            <div class="field">
              <label class="label">Số điện thoại *</label>
              <input class="input" name="phone" form="orderForm" placeholder="09xxxxxxxx" required pattern="^0[0-9]{9,10}$" title="Bắt đầu bằng 0, 10-11 số">
            </div>
          </div>

          <div class="grid2" style="margin-top:10px">
            <div class="field">
              <label class="label">Email</label>
              <input class="input" type="email" name="email" form="orderForm" placeholder="you@example.com">
            </div>
            <div class="field">
              <label class="label">Ngày sinh</label>
              <input class="input" type="date" name="dob" form="orderForm">
            </div>
          </div>

          <div class="grid2" style="margin-top:10px">
            <div class="field">
              <label class="label">CCCD/CMND</label>
              <input class="input" name="id_number" form="orderForm" placeholder="12 số" pattern="^[0-9]{9,12}$">
            </div>
            <div class="field">
              <label class="label">Địa chỉ</label>
              <input class="input" name="address" form="orderForm" placeholder="Số nhà, đường, phường/xã, quận/huyện">
            </div>
          </div>

          <div class="grid3" style="margin-top:10px">
            <div class="field">
              <label class="label">Tỉnh/Thành</label>
              <input class="input" name="province" form="orderForm" placeholder="VD: TP.HCM">
            </div>
            <div class="field">
              <label class="label">Quận/Huyện</label>
              <input class="input" name="district" form="orderForm" placeholder="VD: Quận 1">
            </div>
            <div class="field">
              <label class="label">Phường/Xã</label>
              <input class="input" name="ward" form="orderForm" placeholder="VD: Bến Nghé">
            </div>
          </div>

          <div style="margin-top:14px">
            <label style="display:flex;gap:8px;align-items:center">
              <input type="checkbox" name="is_company_invoice" form="orderForm" id="ckCompany">
              <span>Xuất hóa đơn công ty (VAT)</span>
            </label>
          </div>

          <div id="companyBox" style="display:none;margin-top:10px">
            <div class="grid2">
              <div class="field">
                <label class="label">Tên công ty</label>
                <input class="input" name="company_name" form="orderForm" placeholder="Công ty TNHH ABC">
              </div>
              <div class="field">
                <label class="label">Mã số thuế</label>
                <input class="input" name="tax_code" form="orderForm" placeholder="MST">
              </div>
            </div>
            <div class="field" style="margin-top:10px">
              <label class="label">Địa chỉ công ty</label>
              <input class="input" name="company_address" form="orderForm" placeholder="Địa chỉ in trên hóa đơn">
            </div>
          </div>

          <div class="field" style="margin-top:10px">
            <label class="label">Ghi chú cho người bán</label>
            <textarea class="textarea" name="note" form="orderForm" placeholder="Thời gian nhận hàng, lưu ý xuất hóa đơn..."></textarea>
          </div>

          <!-- Hidden gửi kèm -->
          <input type="hidden" name="product_name" value="{{ ui.product_name }}" form="orderForm">
          <input type="hidden" name="method" id="methodField" value="{{ ui.current_method }}" form="orderForm">

          <div class="safe">Bằng việc đặt hàng, bạn đồng ý với <a href="#" onclick="return false;">Chính sách bảo mật</a> & <a href="#" onclick="return false;">Điều khoản</a>.</div>
        </div>
      </div>
    </div>

    <!-- RIGHT -->
    <div class="col">
      <form id="orderForm" class="card" method="post" action="">
        <div class="section">
          <h2>🧾 Tóm tắt đơn hàng</h2>
        </div>
        <div class="summary">
          <div class="row" style="justify-content:space-between">
            <span class="muted">Tạm tính ({{ ui.qty }} sản phẩm)</span>
            <span>{{ "{:,.0f}".format(ui.subtotal).replace(",", ".") }} đ</span>
          </div>
          <div class="row" style="justify-content:space-between;margin-top:6px">
            <span class="muted">Phí vận chuyển</span>
            <span style="color:#16a34a">Miễn phí</span>
          </div>
          <div class="hr"></div>
          <div class="total">
            <span>Tổng thanh toán</span>
            <span style="color:#ef4444">{{ "{:,.0f}".format(ui.total).replace(",", ".") }} đ</span>
          </div>

          <div style="margin-top:12px">
            <div style="margin-bottom:8px;text-align:center">
              <div style="display:inline-block;border:1px dashed var(--line);border-radius:10px;padding:8px;background:#fff">
                <img id="qrImg" src="https://img.vietqr.io/image/mbbank-0359506148-compact2.jpg?amount={{ ui.total|int }}&addInfo={{ ('PAY' ~ payment.id ~ '-ORD' ~ payment.order_id) | urlencode }}&accountName={{ bank_owner | urlencode }}" alt="QR" width="140" height="140" loading="eager"/>
              </div>
              <div class="small" style="margin-top:8px">{{ bank_owner }}</div>
            </div>
            <button class="btn" type="submit" onclick="return onSubmit()">Đặt hàng ngay</button>
            <div class="safe">🔒 Thanh toán an toàn & bảo mật</div>
            <div id="methodWarn" class="safe" style="display:none">⚠️ Vui lòng chọn “Chuyển khoản ngân hàng” để tiếp tục đặt hàng.</div>
          </div>
        </div>
      </form>
    </div>

  </div>
</div>

<script>
  const submitBtn = document.querySelector('button.btn[type=submit]');
  const warn = document.getElementById('methodWarn');
  const methodField = document.getElementById('methodField');

  function selectedMethod(){
    const checked = document.querySelector('input[name=method_fake]:checked');
    return checked ? checked.value : (methodField ? methodField.value : '');
  }

  function setSubmitEnabled(enabled){
    if (!submitBtn) return;
    submitBtn.disabled = !enabled;
    if (warn) warn.style.display = enabled ? 'none' : 'block';
  }

  function syncMethodToForm(){
    const m = selectedMethod();
    if (methodField) methodField.value = m;
  }

  function reevaluateMethod(){
    syncMethodToForm();
    // Chỉ cho phép khi là 'banking'
    const ok = selectedMethod() === 'banking';
    setSubmitEnabled(ok);
  }

  // init: gắn sự kiện lên các "pill"
  document.querySelectorAll('.pill').forEach(l => {
    l.addEventListener('click', () => {
      document.querySelectorAll('.pill').forEach(x=>x.classList.remove('active'));
      l.classList.add('active');
      const radio = l.querySelector('input[type=radio]');
      if (radio) radio.checked = true;
      reevaluateMethod();
    });
  });

  // toggle HĐ công ty
  const ck = document.getElementById('ckCompany');
  const box = document.getElementById('companyBox');
  if (ck) ck.addEventListener('change', ()=> box.style.display = ck.checked ? 'block':'none');

  function onSubmit(){
    reevaluateMethod();
    const name = document.querySelector('input[name=full_name]');
    const phone = document.querySelector('input[name=phone]');
    if (selectedMethod() !== 'banking'){
      alert('Hiện chỉ hỗ trợ “Chuyển khoản ngân hàng”. Vui lòng chọn lại.');
      return false;
    }
    if (!name.value.trim() || !phone.checkValidity()){
      alert('Vui lòng nhập Họ tên và SĐT hợp lệ');
      return false;
    }
    return true;
  }

  // chạy lần đầu khi trang load
  reevaluateMethod();
</script>
</body>
</html>
"""


# ============ CONFIRM -> CREATE INVOICE ============
@bp.post("/confirm/<int:payment_id>")
def confirm_payment(payment_id: int):
    payment = Payment.query.get(payment_id)
    if not payment:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    invoice = _invoice_contract(payment)

    # Chỉ bắt buộc full_name, phone nếu chưa có invoice
    if not invoice:
        required = ["full_name", "phone"]
        missing = [k for k in required if not payload.get(k)]
        if missing:
            return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

        method_override = payload.get("method")
        if method_override:
            try:
                payment.method = PaymentMethod(method_override)
            except ValueError:
                return jsonify({"error": "invalid method"}), 400

        info = _invoice_data(payload, payment)

        invoice = Contract(
            payment=payment,
            contract_type=ContractType.INVOICE,
            title=f"Invoice for payment #{payment.id}",
            content=_invoice_text(info, payment),
            extra_data=info,
            created_at=datetime.utcnow(),
        )
        db.session.add(invoice)
        _commit()

    # luôn đảm bảo có HĐ mua bán & trả id
    buyer_stub = {
        "full_name": payload.get("full_name", ""),
        "phone": payload.get("phone", ""),
        "email": payload.get("email", ""),
        "address": payload.get("address", ""),
    }
    sale_contract = _ensure_sale_contract(payment, buyer_stub)

    return jsonify(_payment_response(payment, invoice, sale_contract))


# ============ CONTRACT APIs ============
@bp.post("/contract/create")
def create_contract():
    data = request.get_json(force=True)
    payment_id = data.get("payment_id")
    if not payment_id:
        return jsonify({"error": "missing payment_id"}), 400
    payment = Payment.query.get(payment_id)
    if not payment:
        return jsonify({"error": "not_found"}), 404
    title = data.get("title", f"Digital contract for payment #{payment.id}")
    content = data.get("content", "Digital contract")
    contract = Contract(
        payment=payment,
        contract_type=ContractType.DIGITAL_SALE,
        title=title,
        content=content,
        created_at=datetime.utcnow(),
    )
    db.session.add(contract)
    _commit()
    return jsonify({"message": "created", "contract_id": contract.id}), 201


@bp.post("/contract/create-from-payment")
def create_contract_from_payment():
    data = request.get_json(force=True)
    payment_id = data.get("payment_id")
    if not payment_id:
        return jsonify({"error": "missing payment_id"}), 400

    payment = Payment.query.get(payment_id)
    if not payment:
        return jsonify({"error": "payment_not_found"}), 404

    existing = Contract.query.filter_by(payment_id=payment_id).first()
    if existing:
        return jsonify(
            {"message": "contract_exists", "contract_id": existing.id}
        ), 200

    product_info = data.get("product_info", {})
    buyer_info = data.get("buyer_info", {})
    seller_info = data.get("seller_info", {})
    cart_items = data.get("cart_items")

    title = f"HỢP ĐỒNG MUA BÁN PIN VÀ XE ĐIỆN - {payment.order_id}"
    content = f"""
HỢP ĐỒNG MUA BÁN PIN VÀ XE ĐIỆN QUA SỬ DỤNG

Mã hợp đồng: HD{payment.id}
Mã đơn hàng: {payment.order_id}

BÊN MUA (Bên A):
- Họ tên: {buyer_info.get('name', 'N/A')}
- Email: {buyer_info.get('email', 'N/A')}
- Số điện thoại: {buyer_info.get('phone', 'N/A')}

BÊN BÁN (Bên B):
- Họ tên: {seller_info.get('name', 'N/A')}
- Email: {seller_info.get('email', 'N/A')}
- Số điện thoại: {seller_info.get('phone', 'N/A')}

THÔNG TIN SẢN PHẨM:
{product_info.get('details', 'Chi tiết sản phẩm')}

GIÁ TRỊ HỢP ĐỒNG: {payment.amount:,.0f} VNĐ

ĐIỀU KHOẢN:
1. Bên A đồng ý mua sản phẩm với giá trị như trên
2. Bên B đảm bảo sản phẩm đúng mô tả và chất lượng
3. Thanh toán: Chuyển khoản ngân hàng qua VietQR
4. Giao hàng: Trong 3-5 ngày làm việc
5. Bảo hành: Theo chính sách của nền tảng

Ngày lập: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}
"""

    extra_payload = {
        "product_info": product_info,
        "buyer_info": buyer_info,
        "seller_info": seller_info,
    }
    if cart_items:
        extra_payload["cart_items"] = cart_items

    contract = Contract(
        payment=payment,
        contract_type=ContractType.DIGITAL_SALE,
        contract_status=ContractStatus.PENDING_SIGNATURE,
        title=title,
        content=content,
        extra_data=extra_payload,
        created_at=datetime.utcnow(),
    )
    db.session.add(contract)
    _commit()

    return jsonify(
        {
            "message": "contract_created",
            "contract_id": contract.id,
            "contract_code": f"HD{contract.id}",
            "status": contract.contract_status.value,
        }
    ), 201


@bp.post("/contract/sign")
def sign_contract():
    data = request.get_json(force=True)
    contract_id = data.get("contract_id")
    signer_name = data.get("signer_name")
    if not contract_id or not signer_name:
        return jsonify({"error": "missing arguments"}), 400
    contract = Contract.query.get(contract_id)
    if not contract:
        return jsonify({"error": "not_found"}), 404
    payload = {
        "contract_id": contract.id,
        "payment_id": contract.payment_id,
        "signer": signer_name,
        "iat": int(datetime.utcnow().timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    contract.signer_name = signer_name
    contract.signature_jwt = token
    contract.signed_at = datetime.utcnow()
    _commit()
    return jsonify({"message": "signed", "signature_jwt": token})


# POST: API ghi chữ ký (buyer/seller)
@bp.post("/contract/sign/<int:contract_id>", endpoint="contract_sign_api")
def sign_contract_v2(contract_id: int):
    data = request.get_json(force=True)
    contract = Contract.query.get(contract_id)
    if not contract:
        return jsonify({"error": "contract_not_found"}), 404

    signer_role = data.get("signer_role")  # 'buyer' | 'seller'
    signature_type = data.get("signature_type")  # 'text' | 'image'
    signature_data = data.get("signature_data")  # text hoặc dataURL ảnh

    if (
        signer_role not in ("buyer", "seller")
        or signature_type not in ("text", "image")
        or not signature_data
    ):
        return jsonify({"error": "missing_signature_data"}), 400

    now = datetime.utcnow()
    if signer_role == "buyer":
        contract.buyer_signature_type = (
            SignatureType.TEXT if signature_type == "text" else SignatureType.IMAGE
        )
        contract.buyer_signature_data = signature_data
        contract.buyer_signed_at = now
    else:
        contract.seller_signature_type = (
            SignatureType.TEXT if signature_type == "text" else SignatureType.IMAGE
        )
        contract.seller_signature_data = signature_data
        contract.seller_signed_at = now

    if contract.buyer_signed_at and contract.seller_signed_at:
        contract.contract_status = ContractStatus.SIGNED
        contract.signed_at = now

    _commit()
    return jsonify(
        {
            "message": "signature_recorded",
            "contract_id": contract.id,
            "contract_status": contract.contract_status.value
            if getattr(contract, "contract_status", None)
            else "draft",
            "buyer_signed": bool(contract.buyer_signed_at),
            "seller_signed": bool(contract.seller_signed_at),
        }
    )


@bp.get("/contract/view/<int:contract_id>")
def view_contract(contract_id: int):
    contract = Contract.query.get(contract_id)
    if not contract:
        return jsonify({"error": "not_found"}), 404

    payment = contract.payment

    return jsonify(
        {
            "id": contract.id,
            "payment_id": contract.payment_id,
            "type": contract.contract_type.value,
            "status": contract.contract_status.value
            if hasattr(contract, "contract_status")
            else "draft",
            "title": contract.title,
            "content": contract.content,
            "signer_name": contract.signer_name,
            "signed_at": (contract.signed_at.isoformat() + "Z")
            if contract.signed_at and contract.signed_at.tzinfo is None
            else (
                contract.signed_at.isoformat() if contract.signed_at else None
            ),
            "signature_jwt": contract.signature_jwt,
            "created_at": (contract.created_at.isoformat() + "Z")
            if contract.created_at and contract.created_at.tzinfo is None
            else (
                contract.created_at.isoformat() if contract.created_at else None
            ),
            "contract_code": f"HD{contract.id}",
            "buyer_signature_type": contract.buyer_signature_type.value
            if contract.buyer_signature_type
            else None,
            "buyer_signature_data": contract.buyer_signature_data,
            "buyer_signed_at": (contract.buyer_signed_at.isoformat() + "Z")
            if contract.buyer_signed_at and contract.buyer_signed_at.tzinfo is None
            else (
                contract.buyer_signed_at.isoformat()
                if contract.buyer_signed_at
                else None
            ),
            "seller_signature_type": contract.seller_signature_type.value
            if contract.seller_signature_type
            else None,
            "seller_signature_data": contract.seller_signature_data,
            "seller_signed_at": (contract.seller_signed_at.isoformat() + "Z")
            if contract.seller_signed_at and contract.seller_signed_at.tzinfo is None
            else (
                contract.seller_signed_at.isoformat()
                if contract.seller_signed_at
                else None
            ),
            "payment": {
                "order_id": payment.order_id,
                "amount": float(payment.amount),
                "buyer_id": payment.buyer_id,
                "seller_id": payment.seller_id,
                "method": payment.method.value,
                "status": payment.status.value,
            }
            if payment
            else None,
            "extra_data": contract.extra_data,
        }
    )


# ============ INVOICE PAGE (UI) ============
@bp.get("/invoice/<int:contract_id>")
def invoice_page(contract_id: int):
    contract = Contract.query.get(contract_id)
    if not contract or contract.contract_type != ContractType.INVOICE:
        return "Not found", 404

    payment = contract.payment
    info = contract.extra_data or {}
    confirmed = bool(info.get("confirmed"))
    sale = next(
        (c for c in (payment.contracts or []) if c.contract_type == ContractType.DIGITAL_SALE),
        None,
    )
    sale_code = f"H{sale.id:03d}" if sale else "—"
    sale_id = sale.id if sale else None
    buyer_signed = bool(getattr(sale, "buyer_signed_at", None)) if sale else False
    seller_signed = bool(getattr(sale, "seller_signed_at", None)) if sale else False
    sale_status = (
        getattr(sale, "contract_status", None).value
        if sale and getattr(sale, "contract_status", None)
        else "draft"
    )

    # Buyer: chỉ thanh toán đúng amount (subtotal)
    subtotal = float(payment.amount or 0)
    vat = int(round(subtotal * VAT_RATE))  # áp cho người bán
    seller_net = subtotal - vat
    total = subtotal  # số tiền buyer chuyển

    buyer_name = (
        info.get("full_name")
        or getattr(payment, "buyer_name", None)
        or "Khách hàng"
    )
    product_name = info.get("product_name") or f"Thanh toán đơn hàng {payment.order_id}"
    memo = f"PAY{payment.id}-ORD{payment.order_id}"
    qr_text = (
        f"{BANK_NAME}|{BANK_ACCOUNT}|{BANK_OWNER}|{memo}|{int(total)}"
    )

    bank_initials = (
        "".join([w[0] for w in BANK_NAME.split()[:2]]).upper() or "BK"
    )

    html = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>THANH TOÁN ĐƠN HÀNG — {{ payment.order_id }}</title>
<style>
  :root{
    --bg:#f5f7fb;--card:#fff;--line:#e5e7eb;--muted:#64748b;--text:#0f172a;
    --brand1:#6b8cff;--brand2:#7b5cff;--accent:#ef4444;--ok:#16a34a;--warn:#f59e0b;
  }
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial}
  .wrap{max-width:760px;margin:28px auto;padding:0 12px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 10px 28px rgba(2,6,23,.06);overflow:hidden}
  .header{padding:18px 20px;background:linear-gradient(135deg,var(--brand1),var(--brand2));color:#fff;text-align:center}
  .title{font-weight:800;letter-spacing:.5px}
  .sub{opacity:.9;font-size:12px;margin-top:4px}
  .badges{display:flex;gap:8px;justify-content:center;margin-top:10px;flex-wrap:wrap}
  .badge{background:#ffffff22;border:1px solid #ffffff44;color:#fff;padding:6px 10px;border-radius:999px;font-size:12px;backdrop-filter:blur(2px)}
  .body{padding:18px 20px}
  .totalbox{border:1px solid var(--line);border-radius:12px;background:#fff;box-shadow:inset 0 1px 0 #fff}
  .totalhead{padding:12px 14px;border-bottom:1px dashed var(--line);text-align:center;background:#fff}
  .totalval{padding:16px 14px;text-align:center;font-size:28px;font-weight:900;color:var(--accent)}
  .totalnote{padding:0 0 6px 0;text-align:center;font-size:12px;color:#6b7280}
  .section{margin-top:14px}
  .callout{background:#f1f5ff;border:1px solid #dbe3ff;border-radius:12px;padding:12px 14px;color:#304073}
  .callout ol{margin:6px 0 0 16px;padding:0}
  .center{display:flex;justify-content:center}
  .qrwrap{margin-top:14px;border:1px solid var(--line);border-radius:12px;padding:16px 14px;background:#fff}
  .qrhead{display:flex;align-items:center;gap:8px;justify-content:center;color:#475569;font-weight:700}
  .vietqr{width:72px;height:20px;background:url('https://upload.wikimedia.org/wikipedia/commons/6/6b/VietQR_logo.svg') center/contain no-repeat;filter:grayscale(0)}
  .qrgrid{display:grid;grid-template-columns:160px 1fr;gap:16px;margin-top:10px}
  .qrbox{width:160px;height:160px;border:1px dashed var(--line);border-radius:10px;display:grid;place-items:center;overflow:hidden}
  .kv{display:grid;grid-template-columns:140px 1fr;gap:6px 10px;font-size:14px}
  .kv .k{color:#475569}
  .note{margin-top:14px;background:#fff7ed;border:1px solid #fed7aa;color:#7c2d12;padding:10px 12px;border-radius:10px;font-size:13px}
  .foot{display:flex;gap:10px;justify-content:flex-end;margin-top:14px}
  .btn{appearance:none;border:1px solid var(--line);background:#fff;border-radius:10px;padding:10px 14px;font-weight:700;cursor:pointer}
  .btn.primary{background:#16a34a;color:#fff;border-color:#16a34a}
  .btn.ghost{background:transparent}
  .small{font-size:12px;color:var(--muted)}
  @media (max-width:720px){.qrgrid{grid-template-columns:1fr}.kv{grid-template-columns:120px 1fr}}
  @media print{.foot{display:none}.card{border:none;box-shadow:none;border-radius:0}}
  .btn.disabled{opacity:.5;pointer-events:none}
  .contract-doc{
    font-family: ui-serif, Georgia, "Times New Roman", serif;
    line-height:1.7;font-size:14px;color:#0f172a;
    background:#fff;border:1px solid #e5e7eb;border-radius:12px;
    padding:14px;max-height:65vh;overflow:auto
  }
  .contract-doc pre{white-space:pre-wrap;margin:0}
  .modal-backdrop{
    display:none;position:fixed;inset:0;background:rgba(15,23,42,.35);
    backdrop-filter:blur(4px);z-index:40;align-items:center;justify-content:center
  }
  .modal{
    background:#fff;border-radius:14px;max-width:780px;width:92%;
    max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 50px rgba(15,23,42,.4)
  }
  .modal-head,.modal-foot{padding:10px 14px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center}
  .modal-foot{border-top:1px solid #e5e7eb;border-bottom:none}
  .modal-body{padding:12px 14px;overflow:auto}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <!-- HEADER -->
    <div class="header">
      <div class="title">🧾 THANH TOÁN ĐƠN HÀNG</div>
      <div class="sub">Mã đơn hàng: <b>{{ payment.order_id }}</b></div>
      <div class="badges">
        <span class="badge">Hợp đồng: {{ sale_code }}</span>
        <span class="badge">Trạng thái: {{ payment.status.value|upper }}</span>
      </div>
    </div>

    <!-- BODY -->
    <div class="body">

      <!-- TỔNG THANH TOÁN -->
      <div class="totalbox">
        <div class="totalhead">Tổng thanh toán</div>
        <div class="totalval">{{ "{:,.0f}".format(total).replace(",", ".") }} đ</div>
        <div class="totalnote">Nội dung CK: {{ info.get('product_name') or ("Đơn hàng " ~ payment.order_id) }}</div>
      </div>

      <!-- HƯỚNG DẪN -->
      <div class="section callout">
        <b>📘 Hướng dẫn thanh toán</b>
        <ol>
          <li>Mở ứng dụng ngân hàng có tính năng quét QR Code.</li>
          <li>Chọn <b>“Quét mã QR”</b> và quét mã bên dưới.</li>
          <li>Kiểm tra <b>Ngân hàng / Số TK / Số tiền / Nội dung</b>.</li>
          <li>Xác nhận chuyển tiền, sau đó quay lại trang này.</li>
          <li>Nhấn nút <b>“Đã chuyển tiền – kiểm tra”</b>.</li>
        </ol>
      </div>

      <!-- QR + THÔNG TIN NGÂN HÀNG -->
      <div class="section qrwrap">
        <div class="qrhead">🔎 Second-hand EV &amp; Battery Trading Platform <span class="vietqr" aria-label="VietQR"></span></div>
        <div class="qrgrid">
          <div class="center">
            <div class="qrbox">
              <img id="qrImg" src="https://img.vietqr.io/image/mbbank-0359506148-compact2.jpg?amount={{ total|int }}&addInfo={{ memo | urlencode }}&accountName={{ bank_owner | urlencode }}" alt="QR" width="160" height="160" loading="eager"/>
            </div>
          </div>
          <div class="kv">
            <div class="k">Ngân hàng</div><div><b>{{ bank_name }}</b></div>
            <div class="k">Số tài khoản</div><div><b>{{ bank_account }}</b></div>
            <div class="k">Chủ tài khoản</div><div><b>{{ bank_owner }}</b></div>
            <div class="k">Số tiền</div><div><b>{{ "{:,.0f}".format(total).replace(",", ".") }} đ</b></div>
            <div class="k">Nội dung chuyển khoản</div><div><b id="memo">{{ memo }}</b></div>
            <div class="k">Sản phẩm/ghi chú</div><div>{{ info.get('product_name') or ("Thanh toán đơn " ~ payment.order_id) }}</div>
          </div>
        </div>
      </div>

      <!-- HỢP ĐỒNG MUA BÁN -->
      <div class="section" style="margin-top:14px">
        <div style="background:linear-gradient(135deg,#6b8cff,#7b5cff);color:#fff;border-radius:12px 12px 0 0;padding:10px 14px;font-weight:800;">
          📄 HỢP ĐỒNG MUA BÁN
        </div>
        <div style="border:1px solid var(--line);border-top:none;border-radius:0 0 12px 12px;padding:12px 14px;background:#fff">
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px">
            <span class="badge">Mã HĐ: {{ sale_code }}</span>
            <span class="badge">Trạng thái: {{ sale_status|upper }}</span>
            <span class="badge" style="background:#16a34a22;border-color:#16a34a55;color:#14532d">
              Người mua: {{ 'ĐÃ KÝ' if buyer_signed else 'CHƯA KÝ' }}
            </span>
            <span class="badge" style="background:#f59e0b22;border-color:#f59e0b55;color:#7c2d12">
              Người bán: {{ 'ĐÃ KÝ' if seller_signed else 'CHƯA KÝ' }}
            </span>
          </div>

          {% if sale_id %}
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <button type="button" class="btn ghost" onclick="openContract()">Xem hợp đồng</button>
            </div>
          {% else %}
            <div class="small">Hợp đồng sẽ được tạo tự động sau khi lập hóa đơn.</div>
          {% endif %}
        </div>
      </div>

      <!-- Modal HỢP ĐỒNG -->
      <div id="contractModal" class="modal-backdrop">
        <div class="modal" role="dialog" aria-modal="true" aria-label="Nội dung hợp đồng">
          <div class="modal-head">
            <div style="font-weight:800">📄 Nội dung hợp đồng</div>
            <button class="btn" onclick="closeContract()">Đóng</button>
          </div>
          <div class="modal-body">
            <div class="contract-doc">
              <pre>{{ sale_content }}</pre>
            </div>
          </div>
          <div class="modal-foot">
            {% if sale_id %}
              {% if buyer_signed %}
                <button class="btn primary disabled" aria-disabled="true" title="Bạn đã ký hợp đồng">Đã ký</button>
              {% else %}
                <a class="btn primary" href="/payment/contract/sign/{{ sale_id }}">Ký hợp đồng</a>
              {% endif %}
            {% endif %}
            <button class="btn" onclick="closeContract()">Đóng</button>
          </div>
        </div>
      </div>

      <!-- CẢNH BÁO -->
      <div class="note">
        ⚠️ <b>Lưu ý quan trọng:</b> Vui lòng <u>KHÔNG thay đổi</u> số tiền hoặc nội dung chuyển khoản để hệ thống đối soát nhanh.
        Sau khi chuyển thành công, hãy bấm “Đã chuyển tiền – kiểm tra”.
      </div>

      <!-- ACTIONS -->
      <div class="foot">
        <button class="btn" onclick="window.print()">In hóa đơn</button>
        <button class="btn primary" onclick="checkStatus()">Đã chuyển tiền – kiểm tra</button>
      </div>

      <div class="small">Người mua: <b>{{ buyer_name }}</b> • Tạo lúc {{ payment.created_at.strftime('%d/%m/%Y %H:%M') if payment.created_at else '' }}</div>
    </div>
  </div>
</div>

<script>
let _pollTimer = null;

function openContract(){ const m=document.getElementById('contractModal'); if(m){m.style.display='flex';} }
function closeContract(){ const m=document.getElementById('contractModal'); if(m){m.style.display='none';} }
document.addEventListener('click',e=>{ const m=document.getElementById('contractModal'); if(e.target===m) closeContract(); });

async function _checkAndMaybeRedirect(){
  const r = await fetch('/payment/status/{{ payment.id }}');
  const d = await r.json();
  const st = String(d.status || '').toLowerCase();
  console.log("Trạng thái đơn:", st);

  if (st === 'paid') {
    if (_pollTimer) clearInterval(_pollTimer);
    location.href = '/payment/thankyou/{{ payment.id }}';
    return true;
  }
  return false;
}

async function checkStatus(){
  const ok = await _checkAndMaybeRedirect();
  if (ok) return;

  alert('Trạng thái đơn: pending (đang chờ duyệt)');
  if (!_pollTimer){
    _pollTimer = setInterval(_checkAndMaybeRedirect, 5000);
  }
}
</script>
</body>
</html>
"""
    return render_template_string(
        html,
        payment=payment,
        info=info,
        confirmed=confirmed,
        VAT=VAT_RATE,
        bank_name=BANK_NAME,
        bank_account=BANK_ACCOUNT,
        bank_owner=BANK_OWNER,
        buyer_name=buyer_name,
        memo=memo,
        qr_text=qr_text,
        total=total,
        subtotal=subtotal,
        vat=vat,
        bank_initials=bank_initials,
        sale_code=sale_code,
        sale_id=sale_id,
        buyer_signed=buyer_signed,
        seller_signed=seller_signed,
        sale_status=sale_status,
        sale_content=(sale.content if sale else ""),
        seller_net=seller_net,
    )


# ============ QR / BARCODE ============
@bp.get("/qr/<path:data>")
def qr_image(data):
    try:
        import qrcode

        img = qrcode.make(data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(buf.getvalue(), mimetype="image/png")
    except Exception as e:
        return jsonify(
            {"error": "qr_generation_failed", "detail": str(e)}
        ), 500


@bp.get("/barcode/<path:code>")
def barcode_image(code):
    try:
        import barcode
        from barcode.writer import ImageWriter

        ean = barcode.get("code128", code, writer=ImageWriter())
        buf = io.BytesIO()
        ean.write(buf)
        buf.seek(0)
        return Response(buf.getvalue(), mimetype="image/png")
    except Exception as e:
        return jsonify(
            {"error": "barcode_generation_failed", "detail": str(e)}
        ), 500


# ============ ADMIN APIS (for Admin UI) ============
# ============ ADMIN APIS (for Admin UI) ============
@bp.get("/admin/reports")
def admin_reports():
    limit = request.args.get("limit", type=int) or 100
    items = Payment.query.order_by(Payment.created_at.desc()).limit(limit).all()

    out = []
    for p in items:
        gross = float(p.amount or 0)

        # Nếu model chưa có cột vat_amount / seller_net_amount thì fallback tính runtime
        vat_attr = getattr(p, "vat_amount", None)
        seller_attr = getattr(p, "seller_net_amount", None)

        vat_amount = float(vat_attr) if vat_attr is not None else round(gross * VAT_RATE)
        seller_net_amount = (
            float(seller_attr) if seller_attr is not None else gross - vat_amount
        )

        inv = _invoice_contract(p)

        out.append(
            {
                "id": p.id,
                "order_id": p.order_id,
                "buyer_id": p.buyer_id,
                "seller_id": p.seller_id,
                "items": p.items or [],
                "amount": gross,
                "vat_amount": vat_amount,
                "seller_net_amount": seller_net_amount,
                "status": p.status.value if isinstance(p.status, PaymentStatus) else str(p.status),
                "created_at": (
                    p.created_at.isoformat() + "Z"
                    if p.created_at and p.created_at.tzinfo is None
                    else (p.created_at.isoformat() if p.created_at else None)
                ),
                "pay_url": f"/payment/invoice/{inv.id}" if inv else f"/payment/checkout/{p.id}",
            }
        )

    # ===== Enrich buyer_name / seller_name từ auth-service (giữ nguyên logic cũ) =====
    try:
        import requests

        ADMIN_TOKEN = (
            os.getenv("ADMIN_TOKEN")
            or os.getenv("GATEWAY_ADMIN_TOKEN")
            or os.getenv("ADMIN_TOKEN_FALLBACK")
        )
        AUTH_URL = os.getenv("AUTH_URL", "http://auth_service:5001")
        headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"} if ADMIN_TOKEN else {}
        user_map = {}
        if headers:
            ur = requests.get(f"{AUTH_URL}/auth/admin/users", headers=headers, timeout=5)
            if ur.ok and ur.headers.get("content-type", "").startswith("application/json"):
                udata = ur.json().get("data", [])
                for u in udata:
                    try:
                        uid = int(u.get("id"))
                    except Exception:
                        continue
                    name = u.get("full_name") or u.get("username") or u.get("email")
                    if name:
                        user_map[uid] = name
        if user_map:
            for it in out:
                bid = it.get("buyer_id")
                sid = it.get("seller_id")
                if bid is not None and not it.get("buyer_name"):
                    it["buyer_name"] = user_map.get(int(bid))
                if sid is not None and not it.get("seller_name"):
                    it["seller_name"] = user_map.get(int(sid))
    except Exception:
        # nếu enrich lỗi thì bỏ qua, không làm hỏng API
        pass

    # ===== Tổng hợp doanh thu (chỉ tính những giao dịch đã thanh toán) =====
    paid_rows = [r for r in out if _is_paid_like(r.get("status"))]

    # Nếu vì lý do gì đó không có bản ghi nào "paid" nhưng vẫn có dữ liệu,
    # fallback lấy toàn bộ để admin vẫn thấy số tổng
    if not paid_rows and out:
        paid_rows = out

    total_gross = sum(float(r.get("amount") or 0) for r in paid_rows)
    total_vat = sum(float(r.get("vat_amount") or 0) for r in paid_rows)
    total_seller_net = sum(float(r.get("seller_net_amount") or 0) for r in paid_rows)

    return jsonify(
        {
            "items": out,
            "totals": {
                "total_gross": total_gross,
                "total_vat": total_vat,
                "total_seller_net": total_seller_net,
            },
        }
    )


@bp.post("/admin/approve/<int:pid>")
def admin_approve(pid):
    p = Payment.query.get(pid)
    if not p:
        return jsonify({"error": "not_found"}), 404
    p.status = PaymentStatus.PAID
    p.updated_at = datetime.utcnow()
    _commit()
    return jsonify({"message": "approved", "id": p.id})


@bp.post("/admin/reject/<int:pid>")
def admin_reject(pid):
    p = Payment.query.get(pid)
    if not p:
        return jsonify({"error": "not_found"}), 404
    p.status = PaymentStatus.CANCELED
    p.updated_at = datetime.utcnow()
    _commit()
    return jsonify({"message": "rejected", "id": p.id})


def _build_checkout_ui(payment: Payment):
    product_name = (
        request.args.get("product_name")
        or request.args.get("name")
        or ""
    )
    product_img = request.args.get("img") or ""
    province = request.args.get("province") or ""

    subtotal = float(payment.amount or 0)
    shipping = 0.0
    total = subtotal + shipping

    return {
        "product_name": product_name or f"Đơn hàng #{payment.order_id}",
        "product_img": product_img,
        "province": province,
        "qty": 1,
        "subtotal": subtotal,
        "shipping": shipping,
        "total": total,
        "methods": [
            {
                "key": "banking",
                "label": "Chuyển khoản ngân hàng",
                "desc": "Chuyển khoản qua Internet Banking hoặc QR Code",
                "icon": "🏦",
            },
        ],
        "current_method": payment.method.value,
    }


# GET: trang UI “Ký ngay”
@bp.get("/contract/sign/<int:contract_id>", endpoint="contract_sign_ui")
def sign_contract_page(contract_id: int):
    c = Contract.query.get(contract_id)
    if not c or c.contract_type != ContractType.DIGITAL_SALE:
        return "Not found", 404

    code = f"HD{c.id:02d}"
    created = c.created_at.strftime("%d/%m/%Y %H:%M") if c.created_at else ""
    buyer_already_signed = bool(getattr(c, "buyer_signed_at", None))

    html = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>HỢP ĐỒNG MUA BÁN ĐIỆN TỬ</title>
<style>
  :root{--bg:#f5f7fb;--card:#fff;--line:#e5e7eb;--muted:#64748b;--text:#0f172a;--header:#6b8cff;--cta:#7c3aed}
  *{box-sizing:border-box} html,body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial}
  .wrap{max-width:900px;margin:20px auto;padding:0 12px}
  .card{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 24px rgba(2,6,23,.06);overflow:hidden}
  .head{padding:14px 16px;background:linear-gradient(135deg,#6b8cff,#7b5cff);color:#fff}
  .title{font-weight:800} .sub{opacity:.9;font-size:12px;margin-top:4px}
  .body{padding:16px}
  textarea.contract{width:100%;min-height:320px;border:1px solid var(--line);border-radius:12px;padding:12px;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap}
  .sigbox{border:1px dashed var(--line);border-radius:12px;padding:12px;margin-top:12px;background:#fbfaff}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .field{display:grid;gap:6px} .label{font-size:12px;color:#475569}
  .input{padding:10px 12px;border:1px solid var(--line);border-radius:10px}
  .btn{appearance:none;border:none;border-radius:10px;padding:12px 14px;font-weight:800;cursor:pointer}
  .btn.cta{background:#7c3aed;color:#fff;width:100%}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .muted{color:var(--muted);font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="head">
      <div class="title">🖊️ HỢP ĐỒNG MUA BÁN ĐIỆN TỬ</div>
      <div class="sub">Mã hợp đồng: <b>{{ code }}</b> • Tạo lúc {{ created }}</div>
    </div>
    <div class="body">
      <!-- Nội dung hợp đồng -->
      <textarea class="contract" readonly>{{ content }}</textarea>

      <!-- Khối chữ ký -->
      <div class="sigbox">
        <div class="grid">
          <div class="field">
            <label class="label">Chữ ký người mua (tải ảnh)</label>
            <input class="input" type="file" id="sigImg" accept="image/*">
            <div class="muted">Hoặc bạn có thể ký bằng text ở khung bên phải.</div>
          </div>
          <div class="field">
            <label class="label">Chữ ký người mua (text)</label>
            <input class="input" type="text" id="sigText" placeholder="Nhập họ tên viết tay/kiểu chữ ký">
          </div>
        </div>

        <div class="grid" style="margin-top:12px">
          <div class="field">
            <label class="label">Họ và tên đầy đủ *</label>
            <input class="input" type="text" id="fullName" placeholder="Ví dụ: Nguyễn Văn A" required>
          </div>
          <div class="field">
            <label class="label">Xác nhận</label>
            <label class="row"><input type="checkbox" id="agree"> <span>Tôi đã đọc, hiểu và đồng ý toàn bộ nội dung hợp đồng.</span></label>
          </div>
        </div>

        <div style="margin-top:14px">
          <button class="btn cta" onclick="submitSign()" {% if buyer_already_signed %}disabled{% endif %}>
            ✅ XÁC NHẬN KÝ HỢP ĐỒNG
          </button>
          <div id="msg" class="muted" style="margin-top:8px"></div>
        </div>
      </div>

      <div class="row" style="margin-top:12px">
        <a class="muted" href="/payment/invoice/{{ invoice_id }}">← Quay lại hoá đơn</a>
      </div>
    </div>
  </div>
</div>

<script>
async function submitSign(){
  const agree = document.getElementById('agree').checked;
  const fullName = document.getElementById('fullName').value.trim();
  const sigText = document.getElementById('sigText').value.trim();
  const sigImg = document.getElementById('sigImg').files[0];
  const msg = document.getElementById('msg');
  msg.textContent = '';

  if (!agree){ msg.textContent = 'Vui lòng tick xác nhận đã đọc và đồng ý.'; return; }
  if (!fullName){ msg.textContent = 'Vui lòng nhập Họ và tên đầy đủ.'; return; }

  let signature_type = 'text';
  let signature_data = sigText;
  if (sigImg){
    const b64 = await toBase64(sigImg);
    signature_type = 'image';
    signature_data = b64;
  } else if (!sigText){
    msg.textContent = 'Vui lòng tải ảnh chữ ký hoặc nhập chữ ký dạng text.'; return;
  }

  const payload = {
    signer_role: 'buyer',
    signature_type,
    signature_data
  };

  const r = await fetch('/payment/contract/sign/{{ contract_id }}', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  const d = await r.json();

  if (!r.ok){
    msg.textContent = 'Lỗi ký hợp đồng: ' + (d.error || r.status);
    return;
  }
  msg.textContent = 'Đã ghi nhận chữ ký. Bạn có thể quay lại hoá đơn để thanh toán hoặc chờ người bán ký.';
  setTimeout(()=>{ window.location.href = '/payment/invoice/{{ invoice_id }}'; }, 800);
}

function toBase64(file){
  return new Promise((resolve,reject)=>{
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
</script>
</body>
</html>
"""
    inv = Contract.query.filter_by(
        payment_id=c.payment_id, contract_type=ContractType.INVOICE
    ).first()
    return render_template_string(
        html,
        content=c.content or "",
        code=code,
        created=created,
        contract_id=c.id,
        invoice_id=(inv.id if inv else 0),
        buyer_already_signed=buyer_already_signed,
    )


@bp.get("/thankyou/<int:payment_id>")
def thankyou_page(payment_id: int):
    p = Payment.query.get(payment_id)
    if not p:
        return "Not found", 404

    inv = next(
        (c for c in (p.contracts or []) if c.contract_type == ContractType.INVOICE),
        None,
    )
    sale = next(
        (c for c in (p.contracts or []) if c.contract_type == ContractType.DIGITAL_SALE),
        None,
    )

    order_id = p.order_id
    sale_code = f"H{sale.id:03d}" if sale else "—"
    amount = float(p.amount or 0)

    html = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Cảm ơn — EV Trading</title>
<style>
  :root{--bg:#f6f8fb;--card:#fff;--line:#e5e7eb;--ok:#16a34a;--muted:#64748b;--text:#0f172a}
  *{box-sizing:border-box} html,body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial}
  .wrap{max-width:760px;margin:28px auto;padding:0 12px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:0 12px 32px rgba(2,6,23,.06);padding:22px}
  .check{width:88px;height:88px;border-radius:50%;background:#dcfce7;display:grid;place-items:center;margin:8px auto 12px auto}
  .check svg{width:42px;height:42px;fill:#16a34a}
  h1{margin:6px 0 8px 0;text-align:center}
  .lead{color:var(--muted);text-align:center;max-width:560px;margin:0 auto 14px auto}
  .kv{border:1px solid var(--line);border-radius:12px;padding:12px;background:#fff;margin:12px 0}
  .row{display:grid;grid-template-columns:160px 1fr;gap:6px 12px}
  .k{color:#475569}
  .pill{display:inline-flex;align-items:center;gap:8px;border:1px solid #bbf7d0;background:#ecfdf5;color:#065f46;border-radius:999px;padding:6px 10px;font-weight:700;font-size:12px}
  .info{background:#eef2ff;border:1px solid #c7d2fe;border-radius:12px;padding:12px;color:#3730a3;margin-top:10px}
  .actions{display:flex;gap:10px;justify-content:center;margin-top:14px;flex-wrap:wrap}
  .btn{appearance:none;border:1px solid #e5e7eb;background:#fff;border-radius:10px;padding:10px 14px;font-weight:700;cursor:pointer;text-decoration:none}
  .btn.primary{background:#0ea5e9;border-color:#0ea5e9;color:#fff}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="check">
      <svg viewBox="0 0 24 24"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
    </div>
    <h1>Cảm ơn quý khách!</h1>
    <div class="lead">
      Chúng tôi đã nhận được thanh toán của bạn. Nhân viên sẽ sớm kiểm tra &amp; xác nhận thông tin.
      Sản phẩm sẽ được chuẩn bị và giao tới địa chỉ của bạn trong thời gian sớm nhất.
    </div>

    <div class="kv">
      <div class="row">
        <div class="k">Mã đơn hàng</div><div><b>{{ order_id }}</b></div>
        <div class="k">Mã hợp đồng</div><div><b>{{ sale_code }}</b></div>
        <div class="k">Số tiền</div><div><b>{{ "{:,.0f}".format(amount).replace(",", ".") }} đ</b></div>
        <div class="k">Trạng thái</div><div><span class="pill">Thanh toán đã được xác nhận</span></div>
      </div>
    </div>

    <div class="info">
      <b>Thông tin quan trọng</b>
      <ul style="margin:8px 0 0 18px;padding:0">
        <li>Đơn hàng của bạn đã được ghi nhận.</li>
        <li>Chúng tôi sẽ xác minh giao dịch trong 5–10 phút.</li>
        <li>Bạn sẽ nhận email/SMS khi xác minh hoàn tất.</li>
        <li>Sản phẩm dự kiến giao trong 3–5 ngày làm việc.</li>
      </ul>
    </div>

    <div class="actions">
      <a class="btn" href="/">Quay về trang chủ</a>
      {% if inv %}<a class="btn primary" href="/payment/invoice/{{ inv.id }}">Xem hoá đơn</a>{% endif %}
    </div>
  </div>
</div>
</body>
</html>
"""
    return render_template_string(
        html,
        p=p,
        inv=inv,
        sale=sale,
        order_id=order_id,
        sale_code=sale_code,
        amount=amount,
    )
