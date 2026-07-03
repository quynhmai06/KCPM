from models import db, Product, BlockedUser, ItemType


def post_listing(client, auth_header, payload, username="member1", role="member"):
    return client.post("/listings/", json=payload, headers=auth_header(username, role))


def patch_listing(client, auth_header, pid, payload, username="member1", role="member"):
    return client.patch(f"/listings/{pid}", json=payload, headers=auth_header(username, role))


# =========================
# CREATE WHITE-BOX TESTS
# =========================

def test_create_tc01_no_token(client, valid_create_payload):
    res = client.post("/listings/", json=valid_create_payload)
    assert res.status_code == 401


def test_create_tc02_blocked_user(client, app, auth_header, valid_create_payload):
    with app.app_context():
        db.session.add(BlockedUser(username="member1", reason="spam"))
        db.session.commit()

    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 403


def test_create_tc03_empty_name(client, auth_header, valid_create_payload):
    valid_create_payload["name"] = ""
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_name"


def test_create_tc04_name_too_long(client, auth_header, valid_create_payload):
    valid_create_payload["name"] = "a" * 181
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_name"


def test_create_tc05_price_not_integer(client, auth_header, valid_create_payload):
    valid_create_payload["price"] = "abc"
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_price"


def test_create_tc06_price_less_than_min(client, auth_header, valid_create_payload):
    valid_create_payload["price"] = 0
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_price"


def test_create_tc07_price_greater_than_max(client, auth_header, valid_create_payload):
    valid_create_payload["price"] = 10000000001
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_price"


def test_create_tc08_invalid_item_type(client, auth_header, valid_create_payload):
    valid_create_payload["item_type"] = "phone"
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_item_type"


def test_create_tc09_invalid_main_image_url(client, auth_header, valid_create_payload):
    valid_create_payload["main_image_url"] = "car.txt"
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_main_image_url"


def test_create_tc10_invalid_province(client, auth_header, valid_create_payload):
    valid_create_payload["province"] = "Da Nang"
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_province"


def test_create_tc11_year_less_than_min(client, auth_header, valid_create_payload):
    valid_create_payload["year"] = 1989
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_year"


def test_create_tc12_year_greater_than_max(client, auth_header, valid_create_payload):
    valid_create_payload["year"] = 2027
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_year"


def test_create_tc13_negative_mileage(client, auth_header, valid_create_payload):
    valid_create_payload["mileage"] = -1
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_mileage"


def test_create_tc14_sub_images_not_list(client, auth_header, valid_create_payload):
    valid_create_payload["sub_image_urls"] = "a.jpg"
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "sub_image_urls_must_be_list"


def test_create_tc15_too_many_sub_images(client, auth_header, valid_create_payload):
    valid_create_payload["sub_image_urls"] = ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg", "6.jpg"]
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "too_many_sub_images"


def test_create_tc16_invalid_sub_image_url(client, auth_header, valid_create_payload):
    valid_create_payload["sub_image_urls"] = ["ok.jpg", "bad.txt"]
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_sub_image_url"


def test_create_tc17_valid_without_sub_images(client, auth_header, valid_create_payload):
    valid_create_payload["sub_image_urls"] = []
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 201
    assert res.get_json()["item"]["name"] == valid_create_payload["name"]


def test_create_tc18_valid_with_sub_images(client, auth_header, valid_create_payload):
    valid_create_payload["sub_image_urls"] = ["a.jpg", "b.png"]
    res = post_listing(client, auth_header, valid_create_payload)
    assert res.status_code == 201
    assert res.get_json()["item"]["sub_image_urls"]


# =========================
# UPDATE WHITE-BOX TESTS
# =========================

def test_update_tc01_no_token(client, make_product):
    pid = make_product()
    res = client.patch(f"/listings/{pid}", json={"name": "Update"})
    assert res.status_code == 401


def test_update_tc02_not_found(client, auth_header):
    res = patch_listing(client, auth_header, 999999, {"name": "Update"})
    assert res.status_code == 404


def test_update_tc03_wrong_owner(client, auth_header, make_product):
    pid = make_product(owner="member1")
    res = patch_listing(client, auth_header, pid, {"name": "Update"}, username="member2")
    assert res.status_code == 403


def test_update_tc04_member_edit_approved_listing(client, auth_header, make_product):
    pid = make_product(owner="member1", approved=True)
    res = patch_listing(client, auth_header, pid, {"name": "Update"}, username="member1")
    assert res.status_code == 400


def test_update_tc05_admin_edit_approved_listing(client, auth_header, make_product):
    pid = make_product(owner="member1", approved=True)
    res = patch_listing(client, auth_header, pid, {"name": "Admin updated"}, username="admin", role="admin")
    assert res.status_code == 200
    assert res.get_json()["item"]["name"] == "Admin updated"


def test_update_tc06_empty_name(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"name": ""})
    assert res.status_code == 400


def test_update_tc07_name_too_long(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"name": "a" * 181})
    assert res.status_code == 400


def test_update_tc08_valid_name(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"name": "VinFast VF9"})
    assert res.status_code == 200
    assert res.get_json()["item"]["name"] == "VinFast VF9"


def test_update_tc09_valid_description(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"description": "Xe con moi"})
    assert res.status_code == 200
    assert res.get_json()["item"]["description"] == "Xe con moi"


def test_update_tc10_invalid_price(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"price": "abc"})
    assert res.status_code == 400


def test_update_tc11_valid_price(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"price": 450000000})
    assert res.status_code == 200
    assert res.get_json()["item"]["price"] == 450000000


def test_update_tc12_valid_brand(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"brand": "VinFast"})
    assert res.status_code == 200
    assert res.get_json()["item"]["brand"] == "VinFast"


def test_update_tc13_invalid_province(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"province": "Da Nang"})
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_province"


def test_update_tc14_valid_province(client, auth_header, make_product, allowed_province):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"province": allowed_province})
    assert res.status_code == 200
    assert res.get_json()["item"]["province"] == allowed_province


def test_update_tc15_invalid_item_type(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"item_type": "phone"})
    assert res.status_code == 400


def test_update_tc16_valid_item_type(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"item_type": "vehicle"})
    assert res.status_code == 200
    assert res.get_json()["item"]["item_type"] == "vehicle"


def test_update_tc17_invalid_year(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"year": "abc"})
    assert res.status_code == 400


def test_update_tc18_valid_year(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"year": 2024})
    assert res.status_code == 200
    assert res.get_json()["item"]["year"] == 2024


def test_update_tc19_invalid_mileage(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"mileage": -1})
    assert res.status_code == 400


def test_update_tc20_valid_mileage(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"mileage": 15000})
    assert res.status_code == 200
    assert res.get_json()["item"]["mileage"] == 15000


def test_update_tc21_valid_battery_capacity(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"battery_capacity": "60 kWh"})
    assert res.status_code == 200
    assert res.get_json()["item"]["battery_capacity"] == "60 kWh"


def test_update_tc22_invalid_main_image_url(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"main_image_url": "bad.txt"})
    assert res.status_code == 400


def test_update_tc23_valid_main_image_url(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"main_image_url": "/static/uploads/car.jpg"})
    assert res.status_code == 200
    assert res.get_json()["item"]["main_image_url"] == "/static/uploads/car.jpg"


def test_update_tc24_sub_images_not_list(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"sub_image_urls": "a.jpg"})
    assert res.status_code == 400


def test_update_tc25_too_many_sub_images(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"sub_image_urls": ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg", "6.jpg"]})
    assert res.status_code == 400


def test_update_tc26_invalid_sub_image_url(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"sub_image_urls": ["bad.txt"]})
    assert res.status_code == 400


def test_update_tc27_valid_sub_image_urls(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {"sub_image_urls": ["/static/uploads/a.jpg", "/static/uploads/b.png"]})
    assert res.status_code == 200
    assert len(res.get_json()["item"]["sub_image_urls"]) == 2


def test_update_tc28_empty_body(client, auth_header, make_product):
    pid = make_product()
    res = patch_listing(client, auth_header, pid, {})
    assert res.status_code == 200


def test_update_tc29_multiple_valid_fields(client, auth_header, make_product, allowed_province):
    pid = make_product()
    payload = {
        "name": "VinFast VF9",
        "description": "Updated",
        "price": 600000000,
        "brand": "VinFast",
        "province": allowed_province,
        "item_type": "battery",
        "year": 2025,
        "mileage": 2000,
        "battery_capacity": "90 kWh",
        "main_image_url": "vf9.jpg",
        "sub_image_urls": ["a.jpg", "b.png"],
    }

    res = patch_listing(client, auth_header, pid, payload)

    assert res.status_code == 200
    item = res.get_json()["item"]
    assert item["name"] == payload["name"]
    assert item["item_type"] == "battery"
    assert item["price"] == payload["price"]