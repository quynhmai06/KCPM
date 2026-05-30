# listing-service/app.py
from flask import Flask, jsonify
from models import db
from routes import bp
import os

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///listing.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    app.register_blueprint(bp)

    @app.get("/")
    def health():
        return jsonify(service="listing", status="ok", prefix="/listings")

    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    print("🚀 listing-service:", app.config["SQLALCHEMY_DATABASE_URI"])
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5002)), debug=True)
