from flask import Flask, jsonify
from models import db
from routes import bp
import os

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///favorites.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
app.register_blueprint(bp)

@app.get("/")
def root():
    return jsonify(service="favorites", status="ok", prefix="/favorites")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5004)), debug=True)
