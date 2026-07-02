import unittest

from flask import Flask
from models import db, User, UserProfile
from routes import bp, _make_token, _validate_profile_update
from werkzeug.security import generate_password_hash


class ProfileValidationTests(unittest.TestCase):
    def assert_invalid(self, payload, expected_error):
        validated, error = _validate_profile_update(payload)

        self.assertIsNone(validated)
        self.assertEqual(error, ({"error": expected_error}, 400))

    def test_rejects_empty_full_name(self):
        self.assert_invalid({"full_name": ""}, "invalid_full_name")

    def test_rejects_nine_digit_phone(self):
        self.assert_invalid({"phone": "901234567"}, "invalid_phone")

    def test_rejects_eleven_digit_phone(self):
        self.assert_invalid({"phone": "09012345678"}, "invalid_phone")

    def test_rejects_empty_address(self):
        self.assert_invalid({"address": ""}, "invalid_address")

    def test_rejects_birthdate_before_minimum(self):
        self.assert_invalid({"birthdate": "1899-12-31"}, "invalid_birthdate_range")

    def test_rejects_birthdate_after_maximum(self):
        self.assert_invalid({"birthdate": "2026-07-01"}, "invalid_birthdate_range")

    def test_accepts_documented_boundaries(self):
        payload = {
            "full_name": "n" * 120,
            "phone": "0901234567",
            "address": "a" * 255,
            "birthdate": "2026-06-30",
        }

        validated, error = _validate_profile_update(payload)

        self.assertIsNone(error)
        self.assertEqual(validated["full_name"], payload["full_name"])
        self.assertEqual(validated["phone"], payload["phone"])
        self.assertEqual(validated["address"], payload["address"])
        self.assertEqual(validated["birthdate"].isoformat(), payload["birthdate"])


class ProfileEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask("profile-endpoint-tests")
        cls.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        cls.app.register_blueprint(bp)

        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        db.create_all()

        cls.user = User(
            username="profile_test_user",
            email="profile-test@example.com",
            password=generate_password_hash("TestPassword123"),
            role="member",
            approved=True,
            locked=False,
            phone="0901234567",
        )
        db.session.add(cls.user)
        db.session.flush()
        db.session.add(UserProfile(
            user_id=cls.user.id,
            full_name="Original Name",
            address="Original Address",
        ))
        db.session.commit()

        cls.client = cls.app.test_client()
        cls.headers = {"Authorization": f"Bearer {_make_token(cls.user)}"}

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.app_context.pop()

    def test_six_reported_cases_return_400_without_persisting_changes(self):
        base_payload = {
            "full_name": "Nguyen Van A",
            "phone": "0901234567",
            "address": "Ha Noi",
            "birthdate": "2000-01-01",
        }
        cases = (
            ("PROF_TC06", "full_name", "", "invalid_full_name"),
            ("PROF_TC09", "phone", "901234567", "invalid_phone"),
            ("PROF_TC10", "phone", "09012345678", "invalid_phone"),
            ("PROF_TC13", "address", "", "invalid_address"),
            ("PROF_TC21", "birthdate", "1899-12-31", "invalid_birthdate_range"),
            ("PROF_TC22", "birthdate", "2026-07-01", "invalid_birthdate_range"),
        )

        for test_case, field, value, expected_error in cases:
            with self.subTest(test_case=test_case):
                payload = {**base_payload, field: value}
                response = self.client.put(
                    "/auth/profile",
                    json=payload,
                    headers=self.headers,
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": expected_error})

        profile = UserProfile.query.filter_by(user_id=self.user.id).one()
        db.session.refresh(self.user)
        self.assertEqual(profile.full_name, "Original Name")
        self.assertEqual(profile.address, "Original Address")
        self.assertEqual(self.user.phone, "0901234567")


if __name__ == "__main__":
    unittest.main()
