from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Enum, Index
from db import db


class PaymentMethod(PyEnum):
    E_WALLET = "e-wallet"
    BANKING = "banking"
    CASH = "cash"


class PaymentStatus(PyEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class ContractType(PyEnum):
    INVOICE = "invoice"
    DIGITAL_SALE = "digital-sale"


class ContractStatus(PyEnum):
    DRAFT = "draft"
    PENDING_SIGNATURE = "pending_signature"
    SIGNED = "signed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SignatureType(PyEnum):
    TEXT = "text"
    IMAGE = "image"


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), nullable=False, index=True)  # Changed to String for order IDs like "ORD-123-456"
    buyer_id = db.Column(db.Integer, nullable=False, index=True)
    seller_id = db.Column(db.Integer, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)  # Changed to Float for decimal amounts
    items = db.Column(db.JSON, nullable=True)

    method = db.Column(
        Enum(PaymentMethod, name="payment_method"),
        nullable=False,
        default=PaymentMethod.E_WALLET,
    )
    provider = db.Column(db.String(50), nullable=False, default="DemoPay")

    status = db.Column(
        Enum(PaymentStatus, name="payment_status"),
        nullable=False,
        default=PaymentStatus.PENDING,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_payment_status_created", "status", "created_at"),
    )

    contracts = db.relationship(
        "Contract",
        back_populates="payment",
        lazy=True,
        cascade="all, delete-orphan",
    )


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    contract_type = db.Column(
        Enum(ContractType, name="contract_type"),
        nullable=False,
        default=ContractType.INVOICE,
    )
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    
    # Contract status
    contract_status = db.Column(
        Enum(ContractStatus, name="contract_status"),
        nullable=False,
        default=ContractStatus.DRAFT,
    )
    
    # Buyer signature
    buyer_signature_type = db.Column(Enum(SignatureType, name="signature_type"), nullable=True)
    buyer_signature_data = db.Column(db.Text, nullable=True)  # Text name or base64 image
    buyer_signed_at = db.Column(db.DateTime, nullable=True)
    
    # Seller signature
    seller_signature_type = db.Column(Enum(SignatureType, name="signature_type_seller"), nullable=True)
    seller_signature_data = db.Column(db.Text, nullable=True)
    seller_signed_at = db.Column(db.DateTime, nullable=True)
    
    # Legacy fields
    signer_name = db.Column(db.String(120))
    signed_at = db.Column(db.DateTime)
    signature_jwt = db.Column(db.Text)
    extra_data = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payment = db.relationship("Payment", back_populates="contracts")


__all__ = [
    "db",
    "Payment",
    "Contract",
    "PaymentMethod",
    "PaymentStatus",
    "ContractType",
    "ContractStatus",
    "SignatureType",
]
