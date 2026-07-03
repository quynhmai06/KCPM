import pytest


PAGINATION_KEYS = {"items", "page", "per_page", "total", "pages"}


def search(client, endpoint="/search/listings", **query):
    response = client.get(endpoint, query_string=query)
    return response, response.get_json()


def assert_bad_request(client, query, message, field):
    response, body = search(client, **query)

    assert response.status_code == 400
    assert body == {
        "error": message,
        "code": "invalid_query",
        "field": field,
    }


def ids(body):
    return [item["id"] for item in body["items"]]


def types(body):
    return {item["item_type"] for item in body["items"]}


class TestBasicSearchWhiteBox:
    def test_SEARCH_BASIC_WB_TC01_keyword_exceeds_limit(self, client):
        assert_bad_request(
            client,
            {"q": "q" * 181},
            "q length must be less than or equal to 180",
            "q",
        )

    def test_SEARCH_BASIC_WB_TC02_empty_keyword(self, client):
        response, body = search(client, q="")

        assert response.status_code == 200
        assert set(body) == PAGINATION_KEYS
        assert body["total"] == 4

    def test_SEARCH_BASIC_WB_TC03_valid_keyword(self, client):
        response, body = search(client, q="VinFast")

        assert response.status_code == 200
        assert set(ids(body)) == {1, 2}

    def test_SEARCH_BASIC_WB_TC04_empty_item_type(self, client):
        response, body = search(client, item_type="", product_type="")

        assert response.status_code == 200
        assert body["total"] == 4

    @pytest.mark.parametrize(
        ("query", "expected_type"),
        [
            pytest.param({"item_type": "vehicle"}, "vehicle", id="SEARCH_BASIC_WB_TC05"),
            pytest.param({"item_type": "battery"}, "battery", id="SEARCH_BASIC_WB_TC06"),
            pytest.param({"product_type": "car"}, "vehicle", id="SEARCH_BASIC_WB_TC07"),
        ],
    )
    def test_product_type_filters(self, client, query, expected_type):
        response, body = search(client, **query)

        assert response.status_code == 200
        assert body["total"] == 2
        assert types(body) == {expected_type}

    def test_SEARCH_BASIC_WB_TC08_invalid_item_type(self, client):
        assert_bad_request(
            client,
            {"item_type": "phone"},
            "item_type must be vehicle or battery",
            "item_type",
        )

    @pytest.mark.parametrize(
        ("query", "message", "field"),
        [
            pytest.param(
                {"min_price": "abc"},
                "min_price must be an integer",
                "min_price",
                id="SEARCH_BASIC_WB_TC09",
            ),
            pytest.param(
                {"min_price": -1},
                "min_price must be greater than or equal to 0",
                "min_price",
                id="SEARCH_BASIC_WB_TC10",
            ),
            pytest.param(
                {"max_price": 10_000_000_001},
                "max_price must be less than or equal to 10000000000",
                "max_price",
                id="SEARCH_BASIC_WB_TC11",
            ),
            pytest.param(
                {"min_price": 900_000_000, "max_price": 100_000_000},
                "min_price must be less than or equal to max_price",
                "price_range",
                id="SEARCH_BASIC_WB_TC12",
            ),
        ],
    )
    def test_invalid_basic_query(self, client, query, message, field):
        assert_bad_request(client, query, message, field)

    def test_SEARCH_BASIC_WB_TC13_valid_price_range(self, client):
        response, body = search(
            client,
            min_price=100_000_000,
            max_price=900_000_000,
        )

        assert response.status_code == 200
        assert set(ids(body)) == {1, 2, 3}
        assert all(
            100_000_000 <= item["price"] <= 900_000_000
            for item in body["items"]
        )

    @pytest.mark.parametrize(
        ("sort", "expected_ids"),
        [
            pytest.param("created_asc", [1, 2, 3, 4], id="SEARCH_BASIC_WB_TC14"),
            pytest.param("price_asc", [4, 2, 1, 3], id="SEARCH_BASIC_WB_TC15"),
            pytest.param("price_desc", [3, 1, 2, 4], id="SEARCH_BASIC_WB_TC16"),
        ],
    )
    def test_sort_branches(self, client, sort, expected_ids):
        response, body = search(client, sort=sort)

        assert response.status_code == 200
        assert ids(body) == expected_ids

    def test_SEARCH_BASIC_WB_TC17_default_sort(self, client):
        expected_ids = [4, 3, 2, 1]

        response_without_sort, body_without_sort = search(client)
        response_unknown_sort, body_unknown_sort = search(client, sort="unknown")

        assert response_without_sort.status_code == 200
        assert response_unknown_sort.status_code == 200
        assert ids(body_without_sort) == expected_ids
        assert ids(body_unknown_sort) == expected_ids

    def test_SEARCH_BASIC_WB_TC18_invalid_pagination(self, client):
        assert_bad_request(
            client,
            {"page": 0},
            "page must be greater than or equal to 1",
            "page",
        )
        assert_bad_request(
            client,
            {"per_page": 100},
            "per_page must be less than or equal to 50",
            "per_page",
        )

    def test_SEARCH_BASIC_WB_TC19_valid_pagination(self, client):
        response, body = search(client, page=1, per_page=12)

        assert response.status_code == 200
        assert set(body) == PAGINATION_KEYS
        assert (body["page"], body["per_page"]) == (1, 12)
        assert (body["total"], body["pages"]) == (4, 1)
        assert len(body["items"]) == 4


class TestAdvancedFilterWhiteBox:
    @pytest.mark.parametrize(
        ("query", "message", "field"),
        [
            pytest.param(
                {"year_from": "abc"},
                "year_from must be an integer",
                "year_from",
                id="SEARCH_FILTER_WB_TC01",
            ),
            pytest.param(
                {"year_from": 1989},
                "year_from must be greater than or equal to 1990",
                "year_from",
                id="SEARCH_FILTER_WB_TC02",
            ),
            pytest.param(
                {"year_from": 2025, "year_to": 2020},
                "year_from must be less than or equal to year_to",
                "year_range",
                id="SEARCH_FILTER_WB_TC03",
            ),
            pytest.param(
                {"mileage_min": "abc"},
                "mileage_min must be an integer",
                "mileage_min",
                id="SEARCH_FILTER_WB_TC04",
            ),
            pytest.param(
                {"mileage_min": 900_000, "mileage_max": 1_000},
                "mileage_min must be less than or equal to mileage_max",
                "mileage_range",
                id="SEARCH_FILTER_WB_TC05",
            ),
            pytest.param(
                {"battery_capacity_min": "abc"},
                "battery_capacity_min must be a number",
                "battery_capacity_min",
                id="SEARCH_FILTER_WB_TC06",
            ),
            pytest.param(
                {"battery_capacity_min": 90, "battery_capacity_max": 50},
                "battery_capacity_min must be less than or equal to battery_capacity_max",
                "battery_capacity_range",
                id="SEARCH_FILTER_WB_TC07",
            ),
            pytest.param(
                {"brand": "b" * 81},
                "brand length must be less than or equal to 80",
                "brand",
                id="SEARCH_FILTER_WB_TC08",
            ),
        ],
    )
    def test_invalid_advanced_filter(self, client, query, message, field):
        assert_bad_request(client, query, message, field)

    @pytest.mark.parametrize(
        ("query", "expected_ids"),
        [
            pytest.param({"brand": "VinFast"}, {1, 2}, id="SEARCH_FILTER_WB_TC09"),
            pytest.param({"province": "Hà Nội"}, {1, 2}, id="SEARCH_FILTER_WB_TC10"),
            pytest.param({"owner": "alice"}, {1, 3}, id="SEARCH_FILTER_WB_TC11"),
            pytest.param({"approved": "true"}, {1, 2}, id="SEARCH_FILTER_WB_TC12"),
            pytest.param({"approved": "false"}, {3, 4}, id="SEARCH_FILTER_WB_TC13"),
            pytest.param(
                {"year_from": 2020, "year_to": 2026},
                {1, 2},
                id="SEARCH_FILTER_WB_TC14",
            ),
            pytest.param(
                {"mileage_min": 0, "mileage_max": 50_000},
                {1, 2},
                id="SEARCH_FILTER_WB_TC15",
            ),
            pytest.param(
                {"battery_capacity_min": 50, "battery_capacity_max": 100},
                {1, 2, 3},
                id="SEARCH_FILTER_WB_TC16",
            ),
            pytest.param(
                {"battery_capacity": "kWh"},
                {1},
                id="SEARCH_FILTER_WB_TC17",
            ),
        ],
    )
    def test_valid_advanced_filter(self, client, query, expected_ids):
        response, body = search(client, **query)

        assert response.status_code == 200
        assert set(ids(body)) == expected_ids

    @pytest.mark.parametrize(
        ("endpoint", "query", "expected_type"),
        [
            pytest.param(
                "/search/vehicles",
                {"item_type": "battery"},
                "vehicle",
                id="SEARCH_FILTER_WB_TC18",
            ),
            pytest.param(
                "/search/batteries",
                {"item_type": "vehicle"},
                "battery",
                id="SEARCH_FILTER_WB_TC19",
            ),
        ],
    )
    def test_shortcut_endpoint(self, client, endpoint, query, expected_type):
        response, body = search(client, endpoint, **query)

        assert response.status_code == 200
        assert body["total"] == 2
        assert types(body) == {expected_type}

    def test_SEARCH_FILTER_WB_TC20_combined_filters(self, client):
        response, body = search(
            client,
            q="VinFast",
            brand="VinFast",
            province="Hà Nội",
            approved="true",
            year_from=2020,
            year_to=2026,
            mileage_min=0,
            mileage_max=50_000,
            min_price=100_000_000,
            max_price=900_000_000,
        )

        assert response.status_code == 200
        assert set(ids(body)) == {1, 2}

    def test_SEARCH_FILTER_WB_TC21_product_type_overrides_vehicle_shortcut(self, client):
        response, body = search(client, "/search/vehicles", product_type="battery")

        assert response.status_code == 200
        assert body["total"] == 2
        assert types(body) == {"battery"}

    def test_SEARCH_FILTER_WB_TC22_unknown_approved_value_is_false(self, client):
        response, body = search(client, approved="abc")

        assert response.status_code == 200
        assert set(ids(body)) == {3, 4}
        assert all(item["approved"] is False for item in body["items"])
