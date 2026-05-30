from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from enum import Enum
from sqlalchemy import Enum as SAEnum

db = SQLAlchemy()

class ProductStatus(Enum):
    pending  = "pending"
    approved = "approved"
    rejected = "rejected"
    spam     = "spam"

class ItemType(Enum):
    vehicle = "vehicle"
    battery = "battery"

class Product(db.Model):
    __tablename__ = "products"

    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(180), nullable=False, index=True)
    description      = db.Column(db.Text)
    price            = db.Column(db.Integer, nullable=False, default=0, index=True)
    brand            = db.Column(db.String(80), index=True)
    province         = db.Column(db.String(80), index=True)
    year             = db.Column(db.Integer, index=True)
    mileage          = db.Column(db.Integer)
    battery_capacity = db.Column(db.String(50))
    owner            = db.Column(db.String(80), nullable=False, index=True)

    item_type        = db.Column(SAEnum(ItemType), nullable=False, default=ItemType.vehicle, index=True)

    main_image_url   = db.Column(db.String(255))
    sub_image_urls   = db.Column(db.Text)  

    approved         = db.Column(db.Boolean, default=False, index=True) 
    approved_at      = db.Column(db.DateTime)
    approved_by      = db.Column(db.String(80))

    created_at       = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    status           = db.Column(SAEnum(ProductStatus), default=ProductStatus.pending, nullable=False)
    verified         = db.Column(db.Boolean, default=False)
    moderation_notes = db.Column(db.Text)
    sold             = db.Column(db.Boolean, default=False, index=True)  # Đánh dấu đã bán

class BlockedUser(db.Model):
    __tablename__ = "blocked_users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, index=True, nullable=False)
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

