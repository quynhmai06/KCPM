from datetime import datetime

from db import db


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)

    # Đổi từ Integer -> BigInteger
    product_id = db.Column(db.BigInteger, index=True, nullable=False)
    buyer_id = db.Column(db.BigInteger, index=True, nullable=False)
    seller_id = db.Column(db.BigInteger, index=True, nullable=True)

    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self):
        return (
            f"<Review "
            f"id={self.id} "
            f"product_id={self.product_id} "
            f"buyer_id={self.buyer_id} "
            f"seller_id={self.seller_id} "
            f"rating={self.rating}>"
        )


class Reply(db.Model):
    __tablename__ = "replies"

    id = db.Column(db.Integer, primary_key=True)

    review_id = db.Column(
        db.Integer,
        db.ForeignKey("reviews.id"),
        nullable=False,
        index=True,
    )

    # Đổi từ Integer -> BigInteger
    seller_id = db.Column(db.BigInteger, nullable=False)

    message = db.Column(db.Text, nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    review = db.relationship(
        "Review",
        backref=db.backref(
            "replies",
            lazy=True,
            cascade="all, delete-orphan",
        ),
    )

    def __repr__(self):
        return (
            f"<Reply "
            f"id={self.id} "
            f"review_id={self.review_id} "
            f"seller_id={self.seller_id}>"
        )