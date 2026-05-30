from flask import Flask
from db import db
from routes import bp as reviews_bp
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///reviews.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_AS_ASCII"] = False

    db.init_app(app)
    with app.app_context():
        db.create_all()

    app.register_blueprint(reviews_bp)

    @app.get("/")
    def index():
        return {"service": "reviews", "status": "ok", "prefix": "/reviews"}

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5010"))
    app.run(host="0.0.0.0", port=port)
