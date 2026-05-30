import os, requests
from flask import Blueprint, request
from auth_mw import require_admin
from db import db
from models import Complaint

ORDERS_URL = os.getenv("ORDERS_URL", "http://orders_service:5006")
bp_tx = Blueprint("admin_transactions", __name__, url_prefix="/admin/transactions")

@bp_tx.get("/")
@require_admin
def list_transactions():
    try:
        r = requests.get(f"{ORDERS_URL}/orders", params=request.args, timeout=6)
        return (r.json(), r.status_code) if r.ok else ({"error":"orders_upstream","detail":r.text}, r.status_code)
    except requests.RequestException as e:
        return {"error":"upstream_unreachable","detail":str(e)}, 502

# Khiếu nại
@bp_tx.post("/complaints")
@require_admin
def create_complaint():
    d = request.get_json(force=True)
    c = Complaint(transaction_id=d.get("transaction_id"), reporter=d.get("reporter","admin"), note=d.get("note"))
    db.session.add(c); db.session.commit()
    return {"id": c.id, "status": c.status}, 201

@bp_tx.get("/complaints")
@require_admin
def list_complaints():
    q = Complaint.query.order_by(Complaint.created_at.desc()).all()
    return {"data":[{"id":x.id,"tx":x.transaction_id,"status":x.status,"note":x.note,"created_at":x.created_at.isoformat()} for x in q]}

@bp_tx.patch("/complaints/<int:cid>")
@require_admin
def update_complaint(cid: int):
    d = request.get_json(force=True)
    c = Complaint.query.get_or_404(cid)
    if "status" in d: c.status = d["status"]
    if "note" in d: c.note = d["note"]
    db.session.commit()
    return {"ok": True}
