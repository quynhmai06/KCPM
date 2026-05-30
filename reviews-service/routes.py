from typing import Optional

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
import os
import requests
from datetime import datetime

from db import db
from models import Review, Reply

bp = Blueprint("reviews", __name__, url_prefix="/reviews", template_folder="templates")


@bp.get("/")
def idx():
    """Health-check endpoint for the reviews service."""
    return jsonify({"service": "reviews", "status": "ok"})


# -------------------------------------------------------------------
# HTML PAGES
# -------------------------------------------------------------------


@bp.get("/product/<int:product_id>")
def product_page(product_id: int):
    """Trang hiển thị bài đánh giá cho một sản phẩm cụ thể.

    /reviews/product/<product_id>?seller_id=<seller_id_optional>
    """
    seller_id = request.args.get("seller_id", type=int)
    # If seller_id not provided, try to resolve seller from listing-service
    if not seller_id:
        try:
            LISTING_URL = os.getenv("LISTING_URL", "http://listing_service:5002")
            lr = requests.get(f"{LISTING_URL}/listings/{int(product_id)}", timeout=4)
            if lr.ok:
                listing = lr.json() or {}
                # listing may contain owner id or owner username
                owner = listing.get("owner") or listing.get("owner_username") or listing.get("user")
                if owner:
                    try:
                        # if owner is numeric id
                        owner_int = int(owner)
                        seller_id = owner_int
                    except Exception:
                        # otherwise resolve username -> id via auth service
                        try:
                            AUTH_URL = os.getenv("AUTH_URL", "http://auth_service:5001")
                            aresp = requests.get(f"{AUTH_URL}/auth/users/{owner}", timeout=4)
                            if aresp.ok:
                                seller_id = aresp.json().get("id")
                        except Exception:
                            seller_id = None
        except Exception:
            seller_id = None

    # If we were able to resolve a seller_id, show all reviews for that seller (aggregate votes/comments)
    if seller_id:
        query = Review.query.filter(Review.seller_id == seller_id)
    else:
        query = Review.query.filter(Review.product_id == product_id)

    reviews = query.order_by(Review.created_at.desc()).all()
    avg: Optional[float] = None
    if reviews:
        avg = sum(r.rating for r in reviews) / len(reviews)

    # Map buyer_id -> buyer info (nếu sau này muốn call user-service thì bổ sung ở đây)
    buyers = {}

    return render_template(
        "product_reviews.html",
        product_id=product_id,
        seller_id=seller_id,
        avg=avg,
        reviews=reviews,
        buyers=buyers,
    )


@bp.get("/seller/<int:seller_id>")
def seller_page(seller_id: int):
    """Trang hiển thị toàn bộ đánh giá dành cho một người bán.

    Có thể lọc thêm theo product_id nếu truyền query param.
    """
    product_id = request.args.get("product_id", type=int)

    query = Review.query.filter(Review.seller_id == seller_id)
    if product_id:
        query = query.filter(Review.product_id == product_id)

    reviews = query.order_by(Review.created_at.desc()).all()
    avg: Optional[float] = None
    if reviews:
        avg = sum(r.rating for r in reviews) / len(reviews)

    buyers = {}

    return render_template(
        "product_reviews.html",
        product_id=product_id,
        seller_id=seller_id,
        avg=avg,
        reviews=reviews,
        buyers=buyers,
    )


# -------------------------------------------------------------------
# API: LIST & CREATE REVIEWS
# -------------------------------------------------------------------


@bp.get("/api/reviews")
def list_reviews():
    """API trả về danh sách đánh giá.

    Hỗ trợ filter theo:
    - product_id
    - seller_id
    - buyer_id
    """
    product_id = request.args.get("product_id", type=int)
    seller_id = request.args.get("seller_id", type=int)
    buyer_id = request.args.get("buyer_id", type=int)

    query = Review.query
    if product_id is not None:
        query = query.filter(Review.product_id == product_id)
    if seller_id is not None:
        query = query.filter(Review.seller_id == seller_id)
    if buyer_id is not None:
        query = query.filter(Review.buyer_id == buyer_id)

    reviews = query.order_by(Review.created_at.desc()).all()

    items = []
    for r in reviews:
        items.append(
            {
                "id": r.id,
                "product_id": r.product_id,
                "buyer_id": r.buyer_id,
                "seller_id": r.seller_id,
                "rating": r.rating,
                "comment": r.comment,
                "created_at": (r.created_at.isoformat() if r.created_at else None),
                "updated_at": (r.updated_at.isoformat() if r.updated_at else None),
            }
        )

    return jsonify({"items": items, "total": len(items)})


def _check_user_has_paid(buyer_id: int, product_id: int, seller_id: Optional[int]) -> bool:
    """Kiểm tra với payment-service xem buyer đã được admin duyệt thanh toán
    cho sản phẩm này chưa.

    Logic:
      - Gửi GET tới PAYMENT_BASE_URL + /payment
      - Query params: buyer_id, status=paid, optional seller_id
      - Trong response, duyệt các items xem có item nào trùng product_id
    """
    base_url = os.getenv("PAYMENT_BASE_URL") or os.getenv("PAYMENT_URL") or "http://payment_service:5003"

    try:
        params: dict[str, str] = {"buyer_id": str(buyer_id), "status": "paid"}
        if seller_id:
            params["seller_id"] = str(seller_id)
        resp = requests.get(f"{base_url.rstrip('/')}/payment", params=params, timeout=5)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f"Error calling payment service: {exc}")
        # Có thể chọn fail-open (cho phép) hoặc fail-closed (không cho).
        # Ở đây chọn không cho đánh giá để tránh gian lận.
        return False

    if not resp.ok:
        current_app.logger.error(
            "Payment service returned non-200 status: %s", resp.status_code
        )
        return False

    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f"Cannot decode payment JSON: {exc}")
        return False

    items = data.get("items") or []
    for p in items:
        its = p.get("items") or []
        for it in its:
            candidate = (
                it.get("item_id", None)
                if "item_id" in it
                else it.get("id", None) or it.get("itemId", None)
            )
            if candidate is not None and str(candidate) == str(product_id):
                return True

    return False


@bp.post("/api/reviews")
def create_review():
    """Tạo đánh giá mới.

    Yêu cầu:
    - body JSON: {product_id, seller_id?, rating, comment?, buyer_id}
    - rating: 1–5
    - Chỉ cho phép nếu:
        + Có giao dịch thanh toán đã được admin duyệt (status=paid) cho product_id
        + Chưa có review trước đó của buyer_id cho product_id
    """
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    seller_id = data.get("seller_id")
    rating = data.get("rating")
    comment = (data.get("comment") or "").strip()
    # Do NOT trust buyer_id from client. Prefer resolving from forwarded auth token.
    buyer_id = None
    try:
        auth_header = request.headers.get("Authorization")
        AUTH_URL = os.getenv("AUTH_URL", "http://auth_service:5001")
        if auth_header:
            ar = requests.get(f"{AUTH_URL}/auth/me", headers={"Authorization": auth_header}, timeout=4)
            if ar.ok:
                j = ar.json() or {}
                buyer_id = j.get("sub") or j.get("id")
    except Exception:
        buyer_id = None
    # fallback to client-provided buyer_id only if auth lookup failed
    if not buyer_id:
        if data.get("buyer_id"):
            try:
                buyer_id = int(data.get("buyer_id"))
            except Exception:
                buyer_id = None

    # Validate cơ bản
    if not product_id:
        return jsonify({"detail": "product_id is required"}), 400
    if not buyer_id:
        return jsonify({"detail": "buyer_id is required (must be logged in)"}), 401

    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return jsonify({"detail": "product_id must be an integer"}), 400

    try:
        buyer_id = int(buyer_id)
    except (TypeError, ValueError):
        return jsonify({"detail": "buyer_id must be an integer"}), 400

    if seller_id is not None:
        try:
            seller_id = int(seller_id)
        except (TypeError, ValueError):
            return jsonify({"detail": "seller_id must be an integer"}), 400
    else:
        # Try to resolve seller_id via listing service when not provided
        try:
            LISTING_URL = os.getenv("LISTING_URL", "http://listing_service:5002")
            lresp = requests.get(f"{LISTING_URL}/listings/{int(product_id)}", timeout=4)
            if lresp.ok:
                listing = lresp.json() or {}
                owner = listing.get("owner") or listing.get("owner_username") or listing.get("user")
                if owner:
                    # resolve username -> id
                    AUTH_URL = os.getenv("AUTH_URL", "http://auth_service:5001")
                    aresp = requests.get(f"{AUTH_URL}/auth/users/{owner}", timeout=4)
                    if aresp.ok:
                        seller_id = aresp.json().get("id")
        except Exception:
            seller_id = None

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"detail": "rating must be an integer between 1 and 5"}), 400

    if not (1 <= rating <= 5):
        return jsonify({"detail": "rating must be between 1 and 5"}), 400

    # Kiểm tra đã từng review sản phẩm này chưa (1 user / 1 listing)
    existing = Review.query.filter(
        Review.product_id == product_id,
        Review.buyer_id == buyer_id,
    ).first()
    if existing:
        return (
            jsonify(
                {
                    "detail": "Bạn đã gửi đánh giá cho sản phẩm này rồi.",
                    "code": "already_reviewed",
                }
            ),
            400,
        )

    # Kiểm tra với payment-service: chỉ người MUA đã thanh toán (admin duyệt) mới được đánh giá
    # Cho phép bật chế độ dev để bỏ check bằng biến môi trường REVIEWS_DEV_ALLOW=1
    if os.getenv("REVIEWS_DEV_ALLOW", "0") != "1":
        if not _check_user_has_paid(buyer_id=buyer_id, product_id=product_id, seller_id=seller_id):
            return (
                jsonify(
                    {
                        "detail": "Bạn chưa có thanh toán đã được admin duyệt cho sản phẩm này.",
                        "code": "payment_required",
                    }
                ),
                403,
            )
    else:
        current_app.logger.info(
            "DEV bypass: REVIEWS_DEV_ALLOW=1 set, skipping payment check for product %s by buyer %s",
            product_id,
            buyer_id,
        )

    # Tạo review
    now = datetime.utcnow()
    review = Review(
        product_id=product_id,
        buyer_id=buyer_id,
        seller_id=seller_id,
        rating=rating,
        comment=comment or None,
        created_at=now,
        updated_at=now,
    )

    try:
        db.session.add(review)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error(f"Error saving review: {exc}")
        return jsonify({"detail": "Internal server error"}), 500

    return (
        jsonify(
            {
                "id": review.id,
                "product_id": review.product_id,
                "buyer_id": review.buyer_id,
                "seller_id": review.seller_id,
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.isoformat(),
            }
        ),
        201,
    )


# -------------------------------------------------------------------
# API: CREATE REPLY (PHẢN HỒI NGƯỜI BÁN)
# -------------------------------------------------------------------


@bp.post("/reply/<int:review_id>")
def create_reply(review_id: int):
    """Tạo phản hồi cho một review.

    Body (form-encoded):
      - seller_id
      - message

    Logic:
      - Chỉ cho phép nếu seller_id không rỗng.
      - (Tuỳ hệ thống) có thể bổ sung kiểm tra seller_id là chủ của listing tương ứng.
    """
    seller_id = request.form.get("seller_id")
    message = (request.form.get("message") or "").strip()

    if not seller_id:
        return jsonify({"detail": "seller_id is required"}), 400
    try:
        seller_id_int = int(seller_id)
    except (TypeError, ValueError):
        return jsonify({"detail": "seller_id must be an integer"}), 400

    if not message:
        # Cho phép bỏ trống hay không tuỳ yêu cầu; ở đây yêu cầu phải có nội dung
        return jsonify({"detail": "message is required"}), 400

    rv: Optional[Review] = Review.query.get(review_id)
    if not rv:
        return jsonify({"detail": "Review not found"}), 404

    reply = Reply(
        review_id=review_id,
        seller_id=seller_id_int,
        message=message,
        created_at=datetime.utcnow(),
    )

    try:
        db.session.add(reply)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error(f"Error saving reply: {exc}")
        return jsonify({"detail": "Internal server error"}), 500

    # Redirect lại trang phù hợp (sản phẩm hoặc người bán)
    if rv.seller_id:
        return redirect(
            url_for("reviews.seller_page", seller_id=rv.seller_id, product_id=rv.product_id)
        )
    if rv.product_id:
        return redirect(url_for("reviews.product_page", product_id=rv.product_id))

    return redirect(url_for("reviews.idx"))
