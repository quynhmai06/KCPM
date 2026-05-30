from flask import Flask, jsonify
from models import db
from routes import bp
import os

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///listings.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.register_blueprint(bp)

    @app.get("/")
    def root():
        return jsonify(service="search", status="ok", prefix="/listings")

    return app

app = create_app()

if __name__ == "__main__":
    # Không tạo bảng ở đây vì dùng chung database với listing-service
    # db.create_all() sẽ được gọi từ listing-service
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5003)), debug=False)
