import os
from flask import Flask
from db import db
from routes import bp as payment_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "sqlite:///payment.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_AS_ASCII"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    app.register_blueprint(payment_bp)

    @app.get("/")
    def index():
        return {"service": "payment", "status": "ok", "prefix": "/payment"}

    return app


app = create_app()


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "5003"))
    app.run(host="0.0.0.0", port=port)


