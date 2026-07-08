import pytest


MISSING = object()


def make_review_payload(**overrides):
    """
    Tạo payload mặc định cho POST /reviews/api/reviews.
    Muốn bỏ field nào thì truyền field=MISSING.
    """
    payload = {
        "product_id": 101,
        "buyer_id": 301,
        "seller_id": 2,
        "rating": 5,
        "comment": "Pin tốt",
    }

    for key, value in overrides.items():
        if value is MISSING:
            payload.pop(key, None)
        else:
            payload[key] = value

    return payload


def post_review(client, **overrides):
    return client.post(
        "/reviews/api/reviews",
        json=make_review_payload(**overrides),
    )


# =========================================================
# A. WHITE-BOX TEST: create_review()
# Endpoint: POST /reviews/api/reviews
# =========================================================

def test_create_review_comment_too_long(client):
    response = post_review(client, comment="c" * 1001)

    assert response.status_code == 400
    assert response.get_json()["detail"] == "comment must not exceed 1000 characters"


def test_create_review_missing_product_id(client):
    response = post_review(client, product_id=MISSING)

    assert response.status_code == 400
    assert response.get_json()["detail"] == "product_id is required"


def test_create_review_product_id_not_integer(client):
    response = post_review(client, product_id="abc")

    assert response.status_code == 400
    assert response.get_json()["detail"] == "product_id must be an integer"


def test_create_review_product_id_less_than_one(client):
    response = post_review(client, product_id=-1)

    assert response.status_code == 400
    assert response.get_json()["detail"] == "product_id must be greater than 0"


def test_create_review_missing_buyer_id_and_no_token(client):
    response = post_review(client, buyer_id=MISSING)

    assert response.status_code == 401
    assert response.get_json()["detail"] == "buyer_id is required (must be logged in)"


def test_create_review_buyer_id_not_integer(client):
    response = post_review(client, buyer_id="abc")

    assert response.status_code == 400
    assert response.get_json()["detail"] == "buyer_id must be an integer"


def test_create_review_buyer_id_less_than_one(client):
    response = post_review(client, buyer_id=0)

    assert response.status_code == 400
    assert response.get_json()["detail"] == "buyer_id must be greater than 0"


def test_create_review_seller_id_not_integer(client):
    response = post_review(client, seller_id="abc")

    assert response.status_code == 400
    assert response.get_json()["detail"] == "seller_id must be an integer"


def test_create_review_seller_id_less_than_one(client):
    response = post_review(client, seller_id=-1)

    assert response.status_code == 400
    assert response.get_json()["detail"] == "seller_id must be greater than 0"


def test_create_review_rating_not_integer(client):
    response = post_review(client, rating="abc")

    assert response.status_code == 400
    assert response.get_json()["detail"] == "rating must be an integer between 1 and 5"


def test_create_review_rating_below_min(client):
    response = post_review(client, rating=0)

    assert response.status_code == 400
    assert response.get_json()["detail"] == "rating must be between 1 and 5"


def test_create_review_rating_above_max(client):
    response = post_review(client, rating=6)

    assert response.status_code == 400
    assert response.get_json()["detail"] == "rating must be between 1 and 5"


def test_create_review_success_with_dev_bypass(client):
    response = post_review(
        client,
        product_id=1001,
        buyer_id=2001,
        seller_id=2,
        rating=5,
        comment="Sản phẩm tốt",
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["product_id"] == 1001
    assert data["buyer_id"] == 2001
    assert data["seller_id"] == 2
    assert data["rating"] == 5
    assert data["comment"] == "Sản phẩm tốt"


def test_create_review_duplicate_product_and_buyer(client):
    first = post_review(
        client,
        product_id=1101,
        buyer_id=2101,
        seller_id=2,
        rating=4,
    )
    assert first.status_code == 201

    second = post_review(
        client,
        product_id=1101,
        buyer_id=2101,
        seller_id=2,
        rating=5,
    )

    assert second.status_code == 400
    data = second.get_json()
    assert data["code"] == "already_reviewed"


def test_create_review_payment_required_when_payment_check_fails(client, monkeypatch):
    import routes

    monkeypatch.setenv("REVIEWS_DEV_ALLOW", "0")
    monkeypatch.setattr(
        routes,
        "_check_user_has_paid",
        lambda buyer_id, product_id, seller_id: False,
    )

    response = post_review(
        client,
        product_id=1201,
        buyer_id=2201,
        seller_id=2,
        rating=5,
        force_payment_check=True,
    )

    assert response.status_code == 403
    assert response.get_json()["code"] == "payment_required"


def test_create_review_success_when_payment_check_passes(client, monkeypatch):
    import routes

    monkeypatch.setenv("REVIEWS_DEV_ALLOW", "0")
    monkeypatch.setattr(
        routes,
        "_check_user_has_paid",
        lambda buyer_id, product_id, seller_id: True,
    )

    response = post_review(
        client,
        product_id=1301,
        buyer_id=2301,
        seller_id=2,
        rating=5,
        force_payment_check=True,
    )

    assert response.status_code == 201
    assert response.get_json()["product_id"] == 1301


def test_create_review_without_seller_id_resolve_success(client, monkeypatch):
    """
    Bao phủ nhánh không truyền seller_id,
    listing-service trả owner, auth-service resolve owner thành id.
    """
    import routes

    class FakeResponse:
        def __init__(self, payload, ok=True):
            self._payload = payload
            self.ok = ok
            self.status_code = 200 if ok else 500

        def json(self):
            return self._payload

    def fake_get(url, *args, **kwargs):
        if "/listings/" in url:
            return FakeResponse({"owner": "seller_user"})
        if "/auth/users/" in url:
            return FakeResponse({"id": 88})
        return FakeResponse({}, ok=False)

    monkeypatch.setattr(routes.requests, "get", fake_get)

    response = post_review(
        client,
        product_id=1401,
        buyer_id=2401,
        seller_id=MISSING,
        rating=5,
    )

    assert response.status_code == 201
    assert response.get_json()["seller_id"] == 88


def test_create_review_without_seller_id_resolve_fail(client, monkeypatch):
    """
    Bao phủ nhánh không truyền seller_id nhưng resolve thất bại.
    Theo code hiện tại vẫn cho tạo review với seller_id=None.
    """
    import routes

    def fake_get(*args, **kwargs):
        raise RuntimeError("listing service down")

    monkeypatch.setattr(routes.requests, "get", fake_get)

    response = post_review(
        client,
        product_id=1501,
        buyer_id=2501,
        seller_id=MISSING,
        rating=5,
    )

    assert response.status_code == 201
    assert response.get_json()["seller_id"] is None


def test_create_review_db_error_returns_500(client, monkeypatch):
    import routes

    def raise_commit():
        raise RuntimeError("database error")

    with monkeypatch.context() as m:
        m.setattr(routes.db.session, "commit", raise_commit)

        response = post_review(
            client,
            product_id=1601,
            buyer_id=2601,
            seller_id=2,
            rating=5,
        )

    assert response.status_code == 500
    assert response.get_json()["detail"] == "Internal server error"


# =========================================================
# B. WHITE-BOX TEST: create_reply()
# Endpoint: POST /reviews/reply/<review_id>
# =========================================================

def test_reply_missing_seller_id(client, seed_review):
    review_id = seed_review()

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"message": "OK"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.get_json()["detail"] == "seller_id is required"


def test_reply_seller_id_not_integer(client, seed_review):
    review_id = seed_review()

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"seller_id": "abc", "message": "OK"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.get_json()["detail"] == "seller_id must be an integer"


def test_reply_seller_id_less_than_one(client, seed_review):
    review_id = seed_review()

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"seller_id": "0", "message": "OK"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.get_json()["detail"] == "seller_id must be greater than 0"


def test_reply_missing_message(client, seed_review):
    review_id = seed_review()

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"seller_id": "2"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.get_json()["detail"] == "message is required"


def test_reply_message_only_spaces(client, seed_review):
    review_id = seed_review()

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"seller_id": "2", "message": "   "},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.get_json()["detail"] == "message is required"


def test_reply_message_too_long(client, seed_review):
    review_id = seed_review()

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"seller_id": "2", "message": "m" * 1001},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.get_json()["detail"] == "message must not exceed 1000 characters"


def test_reply_review_not_found(client):
    response = client.post(
        "/reviews/reply/999999",
        data={"seller_id": "2", "message": "OK"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.get_json()["detail"] == "Review not found"


def test_reply_success_redirect_to_seller_page(client, seed_review):
    review_id = seed_review(product_id=10, seller_id=2)

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"seller_id": "2", "message": "Cảm ơn bạn"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/reviews/seller/2" in response.headers["Location"]
    assert "product_id=10" in response.headers["Location"]


def test_reply_success_redirect_to_product_page(client, seed_review):
    review_id = seed_review(product_id=11, seller_id=None)

    response = client.post(
        f"/reviews/reply/{review_id}",
        data={"seller_id": "2", "message": "Cảm ơn bạn"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/reviews/product/11" in response.headers["Location"]


def test_reply_success_redirect_to_index_with_mocked_review(client, monkeypatch):
    """
    Bao phủ nhánh cuối: review không có seller_id và không có product_id.
    Nhánh này phải mock vì model Review.product_id đang nullable=False.
    """
    import routes

    class FakeReview:
        seller_id = None
        product_id = None

    class FakeQuery:
        @staticmethod
        def get(review_id):
            return FakeReview()

    class FakeReviewModel:
        query = FakeQuery()

    monkeypatch.setattr(routes, "Review", FakeReviewModel)

    response = client.post(
        "/reviews/reply/123",
        data={"seller_id": "2", "message": "Cảm ơn bạn"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/reviews/")


def test_reply_db_error_returns_500(client, seed_review, monkeypatch):
    import routes

    review_id = seed_review(product_id=12, seller_id=2)

    def raise_commit():
        raise RuntimeError("database error")

    with monkeypatch.context() as m:
        m.setattr(routes.db.session, "commit", raise_commit)

        response = client.post(
            f"/reviews/reply/{review_id}",
            data={"seller_id": "2", "message": "Cảm ơn bạn"},
            follow_redirects=False,
        )

    assert response.status_code == 500
    assert response.get_json()["detail"] == "Internal server error"


# =========================================================
# C. WHITE-BOX TEST: list_reviews()
# Endpoint: GET /reviews/api/reviews
# =========================================================

def test_list_reviews_no_filter(client, seed_review):
    seed_review(product_id=1, buyer_id=10, seller_id=2)
    seed_review(product_id=2, buyer_id=11, seller_id=3)

    response = client.get("/reviews/api/reviews")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 2
    assert isinstance(data["items"], list)


def test_list_reviews_filter_by_product_id(client, seed_review):
    seed_review(product_id=1, buyer_id=10, seller_id=2)
    seed_review(product_id=2, buyer_id=11, seller_id=2)

    response = client.get("/reviews/api/reviews?product_id=1")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["items"][0]["product_id"] == 1


def test_list_reviews_filter_by_seller_id(client, seed_review):
    seed_review(product_id=1, buyer_id=10, seller_id=2)
    seed_review(product_id=2, buyer_id=11, seller_id=3)

    response = client.get("/reviews/api/reviews?seller_id=2")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["items"][0]["seller_id"] == 2


def test_list_reviews_filter_by_buyer_id(client, seed_review):
    seed_review(product_id=1, buyer_id=10, seller_id=2)
    seed_review(product_id=2, buyer_id=11, seller_id=3)

    response = client.get("/reviews/api/reviews?buyer_id=11")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["items"][0]["buyer_id"] == 11


def test_list_reviews_combined_filters(client, seed_review):
    seed_review(product_id=1, buyer_id=10, seller_id=2)
    seed_review(product_id=1, buyer_id=11, seller_id=2)
    seed_review(product_id=2, buyer_id=10, seller_id=2)

    response = client.get(
        "/reviews/api/reviews?product_id=1&seller_id=2&buyer_id=10"
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["product_id"] == 1
    assert item["seller_id"] == 2
    assert item["buyer_id"] == 10


def test_list_reviews_no_matching_result(client, seed_review):
    seed_review(product_id=1, buyer_id=10, seller_id=2)

    response = client.get("/reviews/api/reviews?product_id=999999")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 0
    assert data["items"] == []


def test_list_reviews_has_created_and_updated_datetime(client, seed_review):
    seed_review(product_id=1, buyer_id=10, seller_id=2)

    response = client.get("/reviews/api/reviews?product_id=1")

    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["created_at"] is not None
    assert item["updated_at"] is not None
    assert "T" in item["created_at"]
    assert "T" in item["updated_at"]


def test_list_reviews_invalid_query_param_is_ignored_by_flask_type_int(client, seed_review):
    """
    Theo code hiện tại, request.args.get('product_id', type=int)
    sẽ biến product_id=abc thành None, nên filter bị bỏ qua và vẫn trả 200.
    """
    seed_review(product_id=1, buyer_id=10, seller_id=2)

    response = client.get("/reviews/api/reviews?product_id=abc")

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1