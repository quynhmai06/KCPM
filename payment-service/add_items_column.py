from flask import Flask
from models import db
import os
from sqlalchemy import text

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///payment.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE payments ADD COLUMN items JSON'))
        db.session.commit()
        print('✅ Added items column successfully')
    except Exception as e:
        print(f'⚠️  Column may already exist or error: {e}')
