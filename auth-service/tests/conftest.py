import os
import sys
from itertools import count
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET"] = "devsecret"
os.environ.setdefault("FLASK_SECRET", "test-secret")

from app import app as flask_app
from models import db, User, UserProfile
from routes import _make_token


@pytest.fixture()
def app():
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )

    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    seq = count(1)

    def _make_user(
        username=None,
        email=None,
        password="Password123",
        role="member",
        approved=True,
        locked=False,
        phone=None,
    ):
        n = next(seq)
        user = User(
            username=username or f"user{n}",
            email=email or f"user{n}@example.com",
            password=generate_password_hash(password),
            role=role,
            approved=approved,
            locked=locked,
            phone=phone,
        )
        db.session.add(user)
        db.session.commit()
        return user

    return _make_user


@pytest.fixture()
def make_profile(app):
    def _make_profile(user, **kwargs):
        profile = UserProfile(user_id=user.id, **kwargs)
        db.session.add(profile)
        db.session.commit()
        return profile

    return _make_profile


@pytest.fixture()
def auth_headers():
    def _auth_headers(user):
        return {"Authorization": f"Bearer {_make_token(user)}"}

    return _auth_headers