from datetime import date

import jwt
import pytest

from models import db, User, UserProfile
from routes import SECRET


REGISTER_URL = "/auth/register"
PROFILE_URL = "/auth/profile"


def assert_error(response, status_code, error):
    assert response.status_code == status_code
    assert response.get_json()["error"] == error


def valid_register_payload(**overrides):
    payload = {
        "username": "validuser",
        "email": "valid@example.com",
        "password": "Password123",
        "phone": "0901234567",
    }
    payload.update(overrides)
    return payload


def valid_profile_payload(**overrides):
    payload = {
        "full_name": "Nguyen Van A",
        "address": "Ha Noi",
        "gender": "male",
        "birthdate": "2000-01-01",
        "phone": "0901234567",
    }
    payload.update(overrides)
    return payload


# ============================================================
# A. WHITE-BOX TEST: DANG KY TAI KHOAN
# ============================================================


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        pytest.param(
            valid_register_payload(username=""),
            "missing_fields",
            id="REG_WB_TC01",
        ),
        pytest.param(
            valid_register_payload(
                username="u" * 81,
                email="longuser@example.com",
                phone="0901234501",
            ),
            "username_too_long",
            id="REG_WB_TC02",
        ),
        pytest.param(
            valid_register_payload(
                username="bademail",
                email="abc",
                phone="0901234502",
            ),
            "invalid_email",
            id="REG_WB_TC03",
        ),
        pytest.param(
            valid_register_payload(
                username="shortpass",
                email="shortpass@example.com",
                password="p" * 7,
                phone="0901234503",
            ),
            "invalid_password",
            id="REG_WB_TC04",
        ),
        pytest.param(
            valid_register_payload(
                username="longpass",
                email="longpass@example.com",
                password="p" * 65,
                phone="0901234504",
            ),
            "invalid_password",
            id="REG_WB_TC05",
        ),
        pytest.param(
            valid_register_payload(
                username="phone9",
                email="phone9@example.com",
                phone="901234567",
            ),
            "invalid_phone",
            id="REG_WB_TC06",
        ),
    ],
)
def test_register_rejects_invalid_data(
    client,
    payload,
    expected_error,
):
    response = client.post(REGISTER_URL, json=payload)

    assert_error(response, 400, expected_error)
    assert User.query.count() == 0


def test_REG_WB_TC07_register_without_phone(client):
    response = client.post(
        REGISTER_URL,
        json=valid_register_payload(
            username="nophone",
            email="nophone@example.com",
            phone="",
        ),
    )

    assert response.status_code == 201
    user = User.query.filter_by(username="nophone").one()

    assert user.phone is None
    assert user.approved is False
    assert user.locked is False


def test_REG_WB_TC08_register_with_valid_phone(client):
    response = client.post(
        REGISTER_URL,
        json=valid_register_payload(
            username="phone10",
            email="phone10@example.com",
        ),
    )

    assert response.status_code == 201
    user = User.query.filter_by(username="phone10").one()

    assert user.phone == "0901234567"


@pytest.mark.parametrize(
    ("username", "email", "raw_phone"),
    [
        pytest.param(
            "phone84",
            "phone84@example.com",
            "84901234567",
            id="REG_WB_TC09",
        ),
        pytest.param(
            "phone084",
            "phone084@example.com",
            "084901234567",
            id="REG_WB_TC10",
        ),
    ],
)
def test_register_normalizes_phone_prefix(
    client,
    username,
    email,
    raw_phone,
):
    response = client.post(
        REGISTER_URL,
        json=valid_register_payload(
            username=username,
            email=email,
            phone=raw_phone,
        ),
    )

    assert response.status_code == 201
    user = User.query.filter_by(username=username).one()

    assert user.phone == "0901234567"


def test_REG_WB_TC11_rejects_duplicate_username(
    client,
    make_user,
):
    make_user(
        username="alice",
        email="alice@example.com",
        phone="0901111111",
    )

    response = client.post(
        REGISTER_URL,
        json=valid_register_payload(
            username="alice",
            email="alice2@example.com",
            phone="0901234511",
        ),
    )

    assert_error(response, 409, "username_exists")
    assert User.query.count() == 1


def test_REG_WB_TC12_rejects_duplicate_email(
    client,
    make_user,
):
    make_user(
        username="existing",
        email="used@example.com",
        phone="0901111112",
    )

    response = client.post(
        REGISTER_URL,
        json=valid_register_payload(
            username="newuser",
            email="used@example.com",
            phone="0901234512",
        ),
    )

    assert_error(response, 409, "email_exists")
    assert User.query.count() == 1


def test_REG_WB_TC13_rejects_duplicate_phone(
    client,
    make_user,
):
    make_user(
        username="existing",
        email="existing@example.com",
        phone="0909999999",
    )

    response = client.post(
        REGISTER_URL,
        json=valid_register_payload(
            username="dupphone",
            email="dupphone@example.com",
            phone="0909999999",
        ),
    )

    assert_error(response, 409, "phone_exists")
    assert User.query.count() == 1


# ============================================================
# B. WHITE-BOX TEST: CAP NHAT HO SO
# ============================================================


def test_PROF_WB_TC01_rejects_missing_token(client):
    response = client.put(
        PROFILE_URL,
        json=valid_profile_payload(),
    )

    assert_error(response, 401, "no_token")


def test_PROF_WB_TC02_rejects_invalid_token(client):
    response = client.put(
        PROFILE_URL,
        json=valid_profile_payload(),
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert_error(response, 401, "invalid_token")


def test_PROF_WB_EXTRA01_rejects_non_integer_token_subject(
    client,
):
    token = jwt.encode(
        {"sub": "abc"},
        SECRET,
        algorithm="HS256",
    )

    response = client.put(
        PROFILE_URL,
        json=valid_profile_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert_error(response, 401, "invalid_token")


def test_PROF_WB_EXTRA02_rejects_user_not_found(client):
    token = jwt.encode(
        {"sub": "999999"},
        SECRET,
        algorithm="HS256",
    )

    response = client.put(
        PROFILE_URL,
        json=valid_profile_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert_error(response, 404, "user_not_found")


def test_PROF_WB_TC03_rejects_locked_user(
    client,
    make_user,
    auth_headers,
):
    user = make_user(
        locked=True,
        approved=True,
    )

    response = client.put(
        PROFILE_URL,
        json=valid_profile_payload(),
        headers=auth_headers(user),
    )

    assert_error(response, 403, "locked")


def test_PROF_WB_TC04_rejects_unapproved_member(
    client,
    make_user,
    auth_headers,
):
    user = make_user(
        role="member",
        approved=False,
    )

    response = client.put(
        PROFILE_URL,
        json=valid_profile_payload(),
        headers=auth_headers(user),
    )

    assert_error(response, 403, "not_approved")


def test_PROF_WB_EXTRA03_allows_unapproved_admin(
    client,
    make_user,
    auth_headers,
):
    admin = make_user(
        role="admin",
        approved=False,
    )

    response = client.put(
        PROFILE_URL,
        json={"full_name": "Admin User"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    profile = UserProfile.query.filter_by(
        user_id=admin.id,
    ).one()

    assert profile.full_name == "Admin User"


def test_PROF_WB_TC05_creates_new_profile(
    client,
    make_user,
    auth_headers,
):
    user = make_user(approved=True)

    response = client.put(
        PROFILE_URL,
        json=valid_profile_payload(),
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.get_json()

    assert body["ok"] is True

    profile = UserProfile.query.filter_by(
        user_id=user.id,
    ).one()

    db.session.refresh(user)

    assert profile.full_name == "Nguyen Van A"
    assert profile.address == "Ha Noi"
    assert profile.gender == "male"
    assert profile.birthdate == date(2000, 1, 1)
    assert user.phone == "0901234567"


def test_PROF_WB_TC06_updates_existing_profile(
    client,
    make_user,
    make_profile,
    auth_headers,
):
    user = make_user(
        approved=True,
        phone="0901111111",
    )

    profile = make_profile(
        user,
        full_name="Old Name",
        address="Old Address",
        birthdate=date(1990, 1, 1),
    )

    response = client.put(
        PROFILE_URL,
        json={
            "full_name": "Tran Thi B",
            "address": "Da Nang",
            "birthdate": "1999-12-31",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200

    db.session.refresh(profile)
    db.session.refresh(user)

    assert profile.full_name == "Tran Thi B"
    assert profile.address == "Da Nang"
    assert profile.birthdate == date(1999, 12, 31)
    assert user.phone == "0901111111"


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        pytest.param(
            {"full_name": "n" * 121},
            "full_name_too_long",
            id="PROF_WB_TC07",
        ),
        pytest.param(
            {"address": "a" * 256},
            "address_too_long",
            id="PROF_WB_TC08",
        ),
        pytest.param(
            {"birthdate": "31/12/2000"},
            "invalid_birthdate_format",
            id="PROF_WB_TC09",
        ),
        pytest.param(
            {"birthdate": "2024-02-31"},
            "invalid_birthdate_format",
            id="PROF_WB_TC10",
        ),
        pytest.param(
            {"full_name": ""},
            "invalid_full_name",
            id="PROF_WB_TC15",
        ),
        pytest.param(
            {"phone": "123"},
            "invalid_phone",
            id="PROF_WB_TC16",
        ),
        pytest.param(
            {"address": ""},
            "invalid_address",
            id="PROF_WB_TC18",
        ),
        pytest.param(
            {"birthdate": "1899-12-31"},
            "invalid_birthdate_range",
            id="PROF_WB_TC19",
        ),
        pytest.param(
            {"birthdate": "2026-07-01"},
            "invalid_birthdate_range",
            id="PROF_WB_EXTRA04",
        ),
        pytest.param(
            {"full_name": 123},
            "invalid_full_name",
            id="PROF_WB_EXTRA05",
        ),
        pytest.param(
            {"phone": "09012ABCDE"},
            "invalid_phone",
            id="PROF_WB_EXTRA06",
        ),
        pytest.param(
            {"address": ["Ha Noi"]},
            "invalid_address",
            id="PROF_WB_EXTRA07",
        ),
        pytest.param(
            {"birthdate": 20000101},
            "invalid_birthdate_format",
            id="PROF_WB_EXTRA08",
        ),
    ],
)
def test_profile_rejects_invalid_fields(
    client,
    make_user,
    auth_headers,
    payload,
    expected_error,
):
    user = make_user(approved=True)

    response = client.put(
        PROFILE_URL,
        json=payload,
        headers=auth_headers(user),
    )

    assert_error(response, 400, expected_error)

    profile = UserProfile.query.filter_by(
        user_id=user.id,
    ).first()

    assert profile is None


def test_PROF_WB_TC11_clears_birthdate(
    client,
    make_user,
    make_profile,
    auth_headers,
):
    user = make_user(approved=True)

    profile = make_profile(
        user,
        full_name="Nguyen Van A",
        birthdate=date(2000, 1, 1),
    )

    response = client.put(
        PROFILE_URL,
        json={"birthdate": ""},
        headers=auth_headers(user),
    )

    assert response.status_code == 200

    db.session.refresh(profile)
    assert profile.birthdate is None


def test_PROF_WB_TC12_updates_only_gender(
    client,
    make_user,
    make_profile,
    auth_headers,
):
    user = make_user(approved=True)

    profile = make_profile(
        user,
        full_name="Original Name",
        gender="male",
    )

    response = client.put(
        PROFILE_URL,
        json={"gender": "female"},
        headers=auth_headers(user),
    )

    assert response.status_code == 200

    db.session.refresh(profile)

    assert profile.gender == "female"
    assert profile.full_name == "Original Name"


def test_PROF_WB_TC13_updates_only_phone(
    client,
    make_user,
    make_profile,
    auth_headers,
):
    user = make_user(
        approved=True,
        phone="0901111111",
    )

    make_profile(
        user,
        full_name="Original Name",
    )

    response = client.put(
        PROFILE_URL,
        json={"phone": "0908888888"},
        headers=auth_headers(user),
    )

    assert response.status_code == 200

    db.session.refresh(user)
    assert user.phone == "0908888888"


def test_PROF_WB_TC14_accepts_empty_object_without_changes(
    client,
    make_user,
    make_profile,
    auth_headers,
):
    user = make_user(
        approved=True,
        phone="0901111111",
    )

    profile = make_profile(
        user,
        full_name="Original Name",
        address="Original Address",
        gender="male",
        birthdate=date(2000, 1, 1),
    )

    response = client.put(
        PROFILE_URL,
        json={},
        headers=auth_headers(user),
    )

    assert response.status_code == 200

    db.session.refresh(profile)
    db.session.refresh(user)

    assert profile.full_name == "Original Name"
    assert profile.address == "Original Address"
    assert profile.gender == "male"
    assert profile.birthdate == date(2000, 1, 1)
    assert user.phone == "0901111111"


def test_PROF_WB_TC17_rejects_non_object_json(
    client,
    make_user,
    auth_headers,
):
    user = make_user(approved=True)

    response = client.put(
        PROFILE_URL,
        json=[],
        headers=auth_headers(user),
    )

    assert_error(response, 400, "invalid_json")


def test_PROF_WB_TC20_rejects_duplicate_phone(
    client,
    make_user,
    auth_headers,
):
    current_user = make_user(
        username="current",
        email="current@example.com",
        phone="0901111111",
        approved=True,
    )

    make_user(
        username="other",
        email="other@example.com",
        phone="0907777777",
        approved=True,
    )

    response = client.put(
        PROFILE_URL,
        json={"phone": "0907777777"},
        headers=auth_headers(current_user),
    )

    assert_error(response, 409, "phone_exists")

    db.session.refresh(current_user)
    assert current_user.phone == "0901111111"