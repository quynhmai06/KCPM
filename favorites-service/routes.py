from flask import Blueprint, request
from models import db, Favorite

bp = Blueprint("favorites", __name__, url_prefix="/favorites")


@bp.get("/")
def health():
    return {"service": "favorites", "status": "ok"}


@bp.get("/me")
def list_my_favorites():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return {"error": "missing_user_id"}, 400
    favs = Favorite.query.filter_by(user_id=user_id).order_by(Favorite.created_at.desc()).all()
    data = [{
        "id": f.id,
        "item_type": f.item_type,
        "item_id": f.item_id,
        "created_at": f.created_at.isoformat(),
    } for f in favs]
    return {"data": data}


@bp.post("")
def add_favorite():
    d = request.get_json(force=True)
    # Debug log to verify payload
    try:
        print("[favorites] add_favorite raw payload:", d, flush=True)
    except Exception:
        pass
    user_id = d.get("user_id")
    item_type = d.get("item_type")
    item_id = d.get("item_id")
    if not user_id or not item_type or not item_id:
        print(f"[favorites] missing_fields user_id={user_id} item_type={item_type} item_id={item_id}", flush=True)
        return {"error": "missing_fields", "received": {"user_id": user_id, "item_type": item_type, "item_id": item_id}}, 400
    f = Favorite(user_id=user_id, item_type=item_type, item_id=item_id)
    db.session.add(f)
    try:
        db.session.commit()
        print(f"[favorites] created favorite id={f.id} user={f.user_id} type={f.item_type} item={f.item_id}", flush=True)
    except Exception as e:
        db.session.rollback()
        print(f"[favorites] unique/commit error: {e}", flush=True)
        return {"error": "exists"}, 409
    return {"id": f.id}, 201


@bp.delete("/<int:fav_id>")
def delete_favorite(fav_id: int):
    f = Favorite.query.get_or_404(fav_id)
    db.session.delete(f)
    db.session.commit()
    return {"ok": True}
