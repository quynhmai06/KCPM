from flask import Blueprint, request
from auth_mw import require_admin
from db import db
from models import FeeConfig

bp_cfg = Blueprint("admin_config", __name__, url_prefix="/admin/config")

@bp_cfg.get("/fees")
@require_admin
def get_fees():
    cfg = FeeConfig.query.order_by(FeeConfig.id.desc()).first()
    if not cfg:
        cfg = FeeConfig(); db.session.add(cfg); db.session.commit()
    return {"tx_fee_pct": cfg.tx_fee_pct, "seller_commission_pct": cfg.seller_commission_pct}

@bp_cfg.put("/fees")
@require_admin
def update_fees():
    d = request.get_json(force=True)
    cfg = FeeConfig.query.order_by(FeeConfig.id.desc()).first() or FeeConfig()
    if "tx_fee_pct" in d: cfg.tx_fee_pct = float(d["tx_fee_pct"])
    if "seller_commission_pct" in d: cfg.seller_commission_pct = float(d["seller_commission_pct"])
    db.session.add(cfg); db.session.commit()
    return {"ok": True}
