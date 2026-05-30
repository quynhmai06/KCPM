# pricing-service/app.py
from flask import Flask, request, jsonify
import os, json, re, time, threading, concurrent.futures, hashlib
from datetime import datetime

# ---------- Config ----------
VERSION = "2025-11-04-pin-hardlock+normalize-robust"
PROVIDER = os.getenv("PROVIDER", "auto").strip().lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SOFT_TIMEOUT = int(os.getenv("SOFT_TIMEOUT", "8"))
HARD_TIMEOUT = int(os.getenv("HARD_TIMEOUT", "15"))
CACHE_TTL    = int(os.getenv("CACHE_TTL", "600"))
STRICT_AI    = os.getenv("STRICT_AI", "0").lower() in ("1","true","yes")

AI_WEIGHT = float(os.getenv("AI_WEIGHT", "0.70"))
MAX_AI_DEV_BASE = float(os.getenv("MAX_AI_DEVIATION_PCT", "0.20"))

THIS_YEAR = datetime.now().year

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# --- CORS thuần Flask: luôn chèn header cho 8000 (Django) ---
from flask import request

ALLOWED_ORIGINS = {"http://127.0.0.1:8000", "http://localhost:8000"}

@app.after_request
def add_cors_headers(resp):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "false"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Max-Age"] = "86400"
    return resp

# Cho phép preflight OPTIONS (khỏi 403)
@app.route("/predict", methods=["OPTIONS"])
def predict_options():
    return ("", 204)



# ---------- Seeds & maps ----------
SEGMENT_BASES = {
    "motorbike":       35_000_000,
    "mini-ev":        350_000_000,
    "b-ev-hatch":     650_000_000,
    "c-ev-suv":       820_000_000,
    "d-ev-suv":     1_100_000_000,
    "e-ev-suv-3row": 1_500_000_000,
    "lux-ev":       2_600_000_000,
    "e-batt-small":    3_500_000,
    "e-batt-mid":      6_500_000,
    "e-batt-large":    9_500_000,
}
POPULARITY = {
    "vinfast":1.00,"tesla":1.07,"mg":0.98,"byd":1.02,"nissan":0.99,
    "porsche":1.15,"bmw":1.08,"mercedes":1.10,"audi":1.06,
    "yadea":1.00,"dat bike":1.12,"datbike":1.12,"gogoro":1.15,"pega":0.95,
    "dibao":0.90,"dkbike":0.92,"dk bike":0.92,"honda":1.05,"yamaha":1.05,
    "wuling":0.98,
}
PRICE_SEED_MOTO = {
    "vinfast vero x": 34_900_000, "vinfast feliz s": 29_900_000,
    "vinfast klara s": 38_900_000, "vinfast evo200": 22_900_000,
    "vinfast evo x": 29_000_000, "vinfast evo grand": 27_900_000,
    "yadea g5": 35_000_000, "yadea u-like": 19_000_000,
    "yadea voltguard p": 40_000_000, "yadea x-men": 17_000_000,
    "dat bike weaver 200": 55_000_000, "dat bike weaver s": 68_000_000,
    "dat bike ebuddy": 36_000_000,
    "honda em1 e": 40_000_000, "yamaha neo": 50_000_000,
    "pega aura": 17_000_000, "dibao pansy": 17_000_000, "dkbike e": 16_000_000,
}
PRICE_SEED_CAR = {
    "vinfast vf3": 350_000_000, "vinfast vf5": 650_000_000, "vinfast vf6": 820_000_000,
    "vinfast vf8": 1_100_000_000, "vinfast vf9": 1_500_000_000, "vinfast vf e34": 790_000_000,
    "tesla model 3": 1_400_000_000, "tesla model y": 1_600_000_000,
    "mg zs ev": 650_000_000, "byd atto 3": 820_000_000, "nissan leaf": 900_000_000,
    "porsche taycan": 5_500_000_000, "porsche taycan 4s": 6_200_000_000,
    "bmw ix3": 2_000_000_000, "bmw i4 edrive40": 2_700_000_000,
    "bmw ix xdrive40": 5_000_000_000, "bmw i7": 8_500_000_000,
    "wuling mini ev": 330_000_000,
    "byd dolphin": 520_000_000, "byd seal": 1_050_000_000,
    "byd song plus ev": 900_000_000, "byd han": 1_400_000_000,
}
SEED_TO_SEGMENT = {
    "vinfast vf3":"mini-ev","vinfast vf5":"b-ev-hatch","vinfast vf6":"c-ev-suv",
    "vinfast vf8":"d-ev-suv","vinfast vf9":"e-ev-suv-3row","vinfast vf e34":"c-ev-suv",
    "tesla model 3":"c-ev-suv","tesla model y":"d-ev-suv","mg zs ev":"c-ev-suv",
    "byd atto 3":"c-ev-suv","nissan leaf":"c-ev-suv","wuling mini ev":"mini-ev",
    "porsche taycan":"lux-ev","porsche taycan 4s":"lux-ev",
    "bmw ix3":"c-ev-suv","bmw i4 edrive40":"lux-ev","bmw ix xdrive40":"lux-ev","bmw i7":"lux-ev",
    "vinfast vero x":"motorbike","vinfast feliz s":"motorbike","vinfast klara s":"motorbike",
    "vinfast evo200":"motorbike","vinfast evo x":"motorbike","vinfast evo grand":"motorbike",
    "yadea g5":"motorbike","yadea u-like":"motorbike","yadea voltguard p":"motorbike","yadea x-men":"motorbike",
    "dat bike weaver 200":"motorbike","dat bike weaver s":"motorbike","dat bike ebuddy":"motorbike",
    "honda em1 e":"motorbike","yamaha neo":"motorbike","pega aura":"motorbike","dibao pansy":"motorbike","dkbike e":"motorbike",
    "byd dolphin": "b-ev-hatch","byd seal": "c-ev-suv","byd song plus ev": "c-ev-suv","byd han": "lux-ev",
}
MODEL_TO_SEGMENT_REGEX = [
    (r"\bvinfast\s*vf\s*3\b","mini-ev"),(r"\bvinfast\s*vf\s*5\b","b-ev-hatch"),
    (r"\bvinfast\s*vf\s*6\b","c-ev-suv"),(r"\bvinfast\s*vf\s*8\b","d-ev-suv"),
    (r"\bvinfast\s*vf\s*9\b","e-ev-suv-3row"),(r"\bvinfast\s*vf\s*e?\s*34\b","c-ev-suv"),
    (r"\btesla\s*model\s*3\b","c-ev-suv"),(r"\btesla\s*model\s*y\b","d-ev-suv"),
    (r"\bmg\s*zs\s*ev\b","c-ev-suv"),(r"\bbyd\s*atto\s*3\b","c-ev-suv"),(r"\bnissan\s*leaf\b","c-ev-suv"),
    (r"\bvinfast\s+(vero\s*x|feliz\s*s|klara\s*s|evo\s*200|evo\s*x|evo\s*grand)\b","motorbike"),
    (r"\byadea\b","motorbike"),(r"\bgogoro\b","motorbike"),
    (r"\bwuling\s+(hongguang\s+)?mini\s*ev\b","mini-ev"),
    (r"\b(pin|battery|batt|pack|ắc\s*quy)\b","e-battery"),
    (r"\b(48|50|52|54|60|64|72|84|96)\s*v\b","e-battery"),
    (r"\bbyd\s+dolphin\b","b-ev-hatch"),(r"\bbyd\s+seal\b","c-ev-suv"),
    (r"\bbyd\s+song\s+plus\s*ev\b","c-ev-suv"),(r"\bbyd\s+han\b","lux-ev"),
]
ALIASES = {
    "evo grand":"vinfast evo grand","vinfast grand":"vinfast evo grand",
    "evo200 grand":"vinfast evo grand","evo 200 grand":"vinfast evo grand",
    "vf e34":"vinfast vf e34","vf e-34":"vinfast vf e34","hongguang mini ev":"wuling mini ev",
    "vf 3":"vinfast vf3","vf-3":"vinfast vf3","vf 5":"vinfast vf5","vf-5":"vinfast vf5",
    "vf 6":"vinfast vf6","vf-6":"vinfast vf6","vf 8":"vinfast vf8","vf-8":"vinfast vf8",
    "vf 9":"vinfast vf9","vf-9":"vinfast vf9","song plus":"byd song plus ev",
}
BRAND_FIX = {
    "porscher":"porsche","porcher":"porsche","bwm":"bmw","bnw":"bmw",
    "teslla":"tesla","mercedez":"mercedes","mescedes":"mercedes",
    "dk bike":"dkbike","datbike":"dat bike",
}
MODEL_MARKET_ADJ = {
    "vinfast vf8": 1.06, "vinfast vf9": 1.08,
    "byd dolphin": 1.03, "byd seal": 1.04, "byd song plus ev": 0.98, "byd han": 1.02,
}

# ---------- Helpers ----------
def _nk(s): return re.sub(r"[\s\-_/]+"," ",(s or "").lower()).strip()
def _flat(s: str) -> str: return re.sub(r"\s+|-|_", "", (s or "").lower())
def _num(x):
    if x is None: return None
    m = re.search(r"\d+(?:\.\d+)?", str(x)); return float(m.group(0)) if m else None
def _apply_alias(k):
    for a,c in ALIASES.items():
        if a in k: return c
    return k
def _seg_label(seg):
    return {
        "motorbike":"xe máy điện","mini-ev":"ô tô mini điện","b-ev-hatch":"ô tô điện hạng B (hatch)",
        "c-ev-suv":"ô tô điện hạng C (SUV)","d-ev-suv":"ô tô điện hạng D (SUV)","e-ev-suv-3row":"ô tô điện 3 hàng ghế",
        "lux-ev":"ô tô điện hạng sang","unknown":"không rõ phân khúc",
        "e-battery":"pin xe điện","e-batt-small":"pin xe điện (nhỏ)","e-batt-mid":"pin xe điện (trung)","e-batt-large":"pin xe điện (lớn)",
    }.get(seg, seg)
def _key(d): return hashlib.sha256(json.dumps(d,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def _fmt_vnd(n):
    try:
        s=f"{int(n):,}".replace(",","."); return f"{s} đ"
    except:
        return f"{n} đ"

ROUND_STEPS = {
    "motorbike": 100_000, "mini-ev": 5_000_000, "b-ev-hatch": 5_000_000,
    "c-ev-suv": 5_000_000, "d-ev-suv": 5_000_000, "e-ev-suv-3row": 10_000_000,
    "lux-ev": 10_000_000, "e-battery": 50_000, "unknown": 5_000_000,
}
def round_nice(n: int, seg: str) -> int:
    step = ROUND_STEPS.get(seg, 5_000_000)
    if step <= 0: return int(n)
    q = int(round(n / step)) * step
    return max(step, q)

_CACHE={}
def cache_get(p):
    it=_CACHE.get(_key(p)); return it[1] if it and it[0]>time.time() else None
def cache_set(p,res): _CACHE[_key(p)]=(time.time()+CACHE_TTL,res)

# ---------- Friendly text ----------
def build_friendly_text(price:int, rng:dict, segment:str, diag:dict, source:str, clamp_pct:float)->tuple[str,str]:
    seg_lbl = _seg_label(segment)
    age = diag.get("age",0); km = diag.get("mileage",0)
    region_adj = diag.get("region_adj",1.0)
    region_txt = "HN/HCM (nhỉnh hơn nhẹ)" if region_adj>1.0 else ("tỉnh (giảm nhẹ)" if region_adj<1.0 else "không điều chỉnh")
    src = "AI" if source in ("openai","gemini") else "baseline"
    expl = f"Phân khúc: {seg_lbl}; xe {age} năm, chạy ~{km:,} km, vùng {region_txt}. Căn cứ {src} với độ lệch an toàn ±{int(clamp_pct*100)}% quanh khung thị trường."
    advice = (f"Nếu xe còn đẹp, đăng gần {_fmt_vnd(rng['high'])}; cần bán nhanh, chọn khoảng {_fmt_vnd(rng['low'])}."
              if segment!="e-battery" else
              "Pin nên nêu rõ dung lượng/thông số và bảo hành; thương lượng quanh mức đề xuất.")
    return expl, advice

# ---------- Normalize ----------
def normalize(payload):
    # nhận nhiều key loại sản phẩm để tránh miss từ UI
    pt = (payload.get("product_type")
          or payload.get("type")
          or payload.get("category")
          or payload.get("productCategory")
          or "").strip().lower()

    batt_text = (payload.get("battery_capacity")
                 or payload.get("battery_text")
                 or payload.get("battery")
                 or payload.get("capacity_text")
                 or "")

    return {
        "name": (payload.get("name") or "").strip(),
        "brand": (payload.get("brand") or "").strip(),
        "province": (payload.get("province") or "").strip(),
        "year": int(_num(payload.get("year")) or 0) or None,
        "mileage": int(_num(payload.get("mileage")) or 0) or None,
        # có thể bị parse nhầm 60 (từ 60V) -> sẽ neutralize trong PIN mode
        "battery_capacity_kwh": float(_num(payload.get("battery_capacity_kwh") or payload.get("battery_capacity")) or 0) or None,
        "battery_text": batt_text,
        "description": (payload.get("description") or "").strip(),
        "product_type": pt,  # "xe" | "pin"
    }

# ---------- Battery parsing ----------
def parse_battery_kwh(text:str):
    t=_nk(text)
    m = re.search(r"(\d{2,3})\s*v[^0-9]{0,3}(\d{1,3})\s*ah", t)
    if m: v=int(m.group(1)); ah=int(m.group(2)); return max(0.4, (v*ah)/1000.0)
    m = re.search(r"(\d{3,5})\s*wh", t)
    if m: wh=int(m.group(1)); return max(0.4, wh/1000.0)
    m = re.search(r"(\d+(?:\.\d+)?)\s*kwh", t)
    if m: return float(m.group(1))
    return None

_BATTERY_KW_RE = re.compile(r"\b(pin|battery|batt|pack|ắc\s*quy)\b", re.I)
_VOLT_RE = re.compile(r"\b(48|50|52|54|60|64|72|84|96)\s*v\b", re.I)
_AH_RE = re.compile(r"\b\d{1,3}\s*ah\b", re.I)
_PIN_RENT_RE = re.compile(r"\b(bản\s*thu[eê]\s*pin|thu[eê]\s*pin|pin\s*thu[eê]|gói\s*thu[eê]\s*pin|thu[eê]\s*gói\s*pin)\b", re.I)
_SELL_BATT_RE = re.compile(r"\b(bán\s*pin|pin\s*rời|pack\s*rời|bộ\s*pin|ắc\s*quy\s*rời|thanh\s*lý\s*pin)\b", re.I)
_CAR_CUES_RE = re.compile(r"\b(vf\s*\d|vf\s*e?\s*34|model\s*[3y]|mini\s*ev|zs\s*ev|leaf|dolphin|seal|song\s*plus|han|ix3|i4|taycan)\b", re.I)

def is_battery_item(name: str, brand: str, desc: str, product_type: str) -> bool:
    pt = (product_type or "").lower()
    if pt in ("xe","xe điện"):
        return False
    if pt in ("pin","pin xe điện"):
        s = _nk(f"{name} {brand} {desc}")
        if _PIN_RENT_RE.search(s) and not _SELL_BATT_RE.search(s):
            return False
        if _SELL_BATT_RE.search(s): return True
        if _VOLT_RE.search(s) and _AH_RE.search(s): return True
        if _CAR_CUES_RE.search(s): return False
        return bool(_BATTERY_KW_RE.search(s) or _VOLT_RE.search(s))
    return False

# ---------- Resolve base ----------
def resolve_base_with_conf(p):
    name = _nk(p.get("name","")); brand = _nk(p.get("brand",""))
    brand = BRAND_FIX.get(brand, brand)
    key = _apply_alias((brand+" "+name).strip())
    desc = _nk(p.get("description",""))
    product_type = (p.get("product_type") or "").lower()
    btxt = _nk(p.get("battery_text",""))
    merged = {**PRICE_SEED_CAR, **PRICE_SEED_MOTO}

    # ==== HARD-LOCK: Nếu UI chọn PIN thì luôn vào e-battery, không cho rẽ sang ô tô ====
    if product_type in ("pin", "pin xe điện"):
        # neutralize số kWh có thể bị parse nhầm (ví dụ 60 từ 60V)
        raw_kwh = p.get("battery_capacity_kwh") or 0.0
        if raw_kwh and raw_kwh > 10:
            p["battery_capacity_kwh"] = None

        nd = f"{name} {desc} {btxt}"
        kwh = parse_battery_kwh(nd) or (p.get("battery_capacity_kwh") or 0)
        if kwh and kwh > 0:
            base = int(6_000_000 * min(3.0, max(0.5, kwh)))
            return base, "e-battery", "battery_kw", "high" if kwh >= 0.8 else "medium"

        if re.search(r"\b(48|50|52|54)\s*v\b", nd): 
            return SEGMENT_BASES["e-batt-small"], "e-battery", "battery_volt", "medium"
        if re.search(r"\b(60|64)\s*v\b", nd): 
            return SEGMENT_BASES["e-batt-mid"], "e-battery", "battery_volt", "medium"
        if re.search(r"\b(72|84|96)\s*v\b", nd): 
            return SEGMENT_BASES["e-batt-large"], "e-battery", "battery_volt", "medium"

        return SEGMENT_BASES["e-batt-mid"], "e-battery", "battery_generic", "low"

    # Nếu không chọn PIN nhưng mô tả có pattern 60V/20Ah, vẫn xem là pin rời
    looks_like_pin = (
        _VOLT_RE.search(btxt) or _AH_RE.search(btxt) or
        _VOLT_RE.search(f"{name} {desc}") or _BATTERY_KW_RE.search(f"{name} {desc} {btxt}")
    )
    if looks_like_pin:
        nd = f"{name} {desc} {btxt}"
        kwh = parse_battery_kwh(nd) or (p.get("battery_capacity_kwh") or 0)
        if kwh and kwh>0:
            base = int(6_000_000 * min(3.0, max(0.5, kwh)))
            return base, "e-battery", "battery_kw", "high" if kwh>=0.8 else "medium"
        if re.search(r"\b(48|50|52|54)\s*v\b", nd):
            return SEGMENT_BASES["e-batt-small"], "e-battery", "battery_volt", "medium"
        if re.search(r"\b(60|64)\s*v\b", nd):
            return SEGMENT_BASES["e-batt-mid"], "e-battery", "battery_volt", "medium"
        if re.search(r"\b(72|84|96)\s*v\b", nd):
            return SEGMENT_BASES["e-batt-large"], "e-battery", "battery_volt", "medium"
        return SEGMENT_BASES["e-batt-mid"], "e-battery", "battery_generic", "low"

    # Map theo seed / segment cho XE
    nk_key_flat = _flat(key)
    for model, price in merged.items():
        if _flat(model) in nk_key_flat:
            seg = SEED_TO_SEGMENT.get(model,"unknown")
            base = int(price * POPULARITY.get(brand,1.0))
            base = int(base * MODEL_MARKET_ADJ.get(model, 1.0))
            return base, seg, "seed", "high"

    for pat,seg in MODEL_TO_SEGMENT_REGEX:
        if re.search(pat, key):
            base = SEGMENT_BASES.get(seg,820_000_000)
            base = int(base * POPULARITY.get(brand,1.0))
            return base, seg, "segment", "medium"

    cap = float(p.get("battery_capacity_kwh") or 0)
    if cap>0:
        if cap<=10: seg="motorbike"; base=SEGMENT_BASES["motorbike"]
        elif cap>=85: seg="e-ev-suv-3row"; base=SEGMENT_BASES["e-ev-suv-3row"]
        elif cap>=70: seg="d-ev-suv"; base=SEGMENT_BASES["d-ev-suv"]
        elif cap>=52: seg="c-ev-suv"; base=SEGMENT_BASES["c-ev-suv"]
        elif cap>=35: seg="b-ev-hatch"; base=SEGMENT_BASES["b-ev-hatch"]
        else: seg="mini-ev"; base=SEGMENT_BASES["mini-ev"]
        base = int(base * POPULARITY.get(brand,1.0))
        return base, seg, "battery_auto", "low"

    if brand in ["yadea","gogoro","dat bike","pega","dibao","dkbike","vinfast bike","honda","yamaha"]:
        base = int(SEGMENT_BASES["motorbike"] * POPULARITY.get(brand,1.0))
        return base, "motorbike", "brand", "medium"

    base = int(820_000_000 * POPULARITY.get(brand,1.0))
    return base, "unknown", "brand", "very_low"

# ---------- Baseline pricing ----------
def baseline_price(p):
    base, seg, src, conf = resolve_base_with_conf(p)
    year = p.get("year") or (THIS_YEAR-2)
    mileage = p.get("mileage") or 40_000
    province = _nk(p.get("province",""))
    cap = float(p.get("battery_capacity_kwh") or 0.0)
    age = max(0, THIS_YEAR - year)

    if seg=="e-battery":
        year_dep = min(0.60, 0.12*age)
        cyc_dep  = min(0.20, (mileage or 0)/30000 * 0.05)
        region_adj = 1.02 if any(k in province for k in ["ha noi","hà nội","ho chi minh","hcm","hn"]) else (0.98 if province else 1.0)
        total_dep = min(0.70, max(0, year_dep + cyc_dep))
        price = int(base*(1-total_dep)*region_adj)//1_000*1_000
        price = round_nice(price, seg)
        low, high = int(price*0.94), int(price*1.06)
        return {
            "suggested_price": price,
            "range": {"low":low,"high":high},
            "explanation": "Pin xe điện: khấu hao theo năm + chu kỳ sử dụng, có điều chỉnh vùng.",
            "_meta": {"segment": seg,"base_source":src,"confidence":conf,
                      "diag":{"year":year,"age":age,"mileage":mileage,"year_dep":year_dep,"mileage_dep":cyc_dep,
                              "total_dep":total_dep,"region_adj":region_adj}}
        }

    if age<=3: year_dep = 0.12*age
    elif age<=7: year_dep = 0.12*3 + 0.08*(age-3)
    else: year_dep = 0.12*3 + 0.08*4 + 0.05*(age-7)
    year_dep = min(0.70, max(0,year_dep))

    blocks = mileage//20_000
    mileage_dep = min(0.40, min(blocks,6)*0.025 + max(0,blocks-6)*0.015)
    if seg=="motorbike" and cap>10: cap=3.5

    region_adj=1.0
    if any(k in province for k in ["hà nội","ha noi","hồ chí minh","ho chi minh","hcm","hn"]):
        region_adj = 1.05 if seg!="motorbike" else 1.03
    elif province: region_adj = 0.98

    total_dep = min(0.75, max(0,year_dep+mileage_dep))
    price = int(base*(1-total_dep)*region_adj)//1_000*1_000
    price = round_nice(price, seg)
    low, high = int(price*0.94), int(price*1.06)

    return {
        "suggested_price": price,
        "range": {"low":low,"high":high},
        "explanation": f"Phân khúc: {_seg_label(seg)}; khấu hao theo tuổi+km, điều chỉnh vùng miền.",
        "_meta": {"segment": seg, "base_source": src, "confidence": conf,
                  "diag": {"year": year, "age": age, "mileage": mileage,
                           "year_dep": year_dep, "mileage_dep": mileage_dep,
                           "total_dep": total_dep, "region_adj": region_adj}}
    }

# ---------- AI providers ----------
SYSTEM_PROMPT = (
    "Bạn là trợ lý định giá chợ đồ xe điện cũ VN. "
    "Hãy ước lượng giá VNĐ hợp lý dựa trên thông tin sản phẩm (xe hoặc pin), "
    "bối cảnh thị trường Việt Nam, khấu hao theo năm, số km, dung lượng pin và khu vực. "
    "{ \"suggested_price\": int, \"range\": {\"low\": int, \"high\": int}, \"explanation\": string }. "
    "Phần giải thích ngắn gọn, thân thiện, phong cách trò chuyện; không lặp lại giá trong phần giải thích. "
    "Không nói về hình ảnh/cách đăng tin. Không thêm văn bản ngoài JSON."
)
def build_user_prompt(p):
    anchors = ("Mốc xe mới VN: mini-ev~350e6; b-ev-hatch~650e6; c-ev-suv~820e6; "
               "d-ev-suv~1.1e9; e-ev-suv-3row~1.5e9; lux-ev~2.6e9; motorbike~35e6; "
               "pin scooter ~6e6/kWh (0.7–3.0 kWh).")
    return (f"{anchors}\nKhấu hao ô tô/xe máy: 0–3y 12%/y; 4–7y 8%/y; >7y 5%/y; 20k km 2.5% (trần 40%). "
            f"Pin: 12%/năm + hao mòn theo chu kỳ. HN/HCM +5% (xe máy +3%); tỉnh −2%.\n\n"
            f"Tên: {p.get('name')} | Hãng: {p.get('brand')} | Năm: {p.get('year')} | "
            f"Km: {p.get('mileage')} | Pin kWh: {p.get('battery_capacity_kwh')} | "
            f"Khu vực: {p.get('province')} | Loại SP: {p.get('product_type')} | "
            f"Mô tả: {p.get('description')}\n"
            'Output JSON only.')

def _clean_json_text(txt):
    if not isinstance(txt,str): return json.dumps({})
    m=re.search(r"```(?:json)?\s*(\{.*?\})\s*```",txt,flags=re.S)
    if m: txt=m.group(1)
    try: json.loads(txt); return txt
    except: return json.dumps({"suggested_price":0,"range":{"low":0,"high":0},"explanation":"parse_error"})

try:
    from openai import OpenAI as OpenAIClient
    _openai = OpenAIClient()
except Exception:
    _openai = None
def call_openai(p):
    if not _openai or not os.getenv("OPENAI_API_KEY"): raise RuntimeError("openai_not_ready")
    r = _openai.chat.completions.create(
        model=OPENAI_MODEL, temperature=0.2, max_tokens=220, timeout=HARD_TIMEOUT,
        response_format={"type":"json_object"},
        messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":build_user_prompt(p)}]
    )
    return r.choices[0].message.content

try:
    from google import genai
    _gemini = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception:
    _gemini = None
def call_gemini(p):
    if not _gemini or not os.getenv("GOOGLE_API_KEY"): raise RuntimeError("gemini_not_ready")
    r = _gemini.models.generate_content(
        model=GEMINI_MODEL,
        contents=[{"role":"user","parts":[{"text":build_user_prompt(p)}]}],
        system_instruction=SYSTEM_PROMPT,
        generation_config={"response_mime_type":"application/json"},
        safety_settings=None,
        timeout=HARD_TIMEOUT,
    )
    txt = getattr(r,"text",None) or r.candidates[0].content.parts[0].text
    return _clean_json_text(txt)

def _to_int(x, default=0):
    try:
        if isinstance(x,(int,float)): return int(x)
        return int(float(str(x).replace(",","")))
    except: return default
def validate_result(d):
    if not isinstance(d,dict): return {"suggested_price":0,"range":{"low":0,"high":0},"explanation":"invalid"}
    sp=_to_int(d.get("suggested_price"),0); rng=d.get("range") or {}
    lo=_to_int(rng.get("low"),0); hi=_to_int(rng.get("high"),0)
    if lo==0 and hi==0: lo,hi=int(sp*0.92),int(sp*1.08)
    return {"suggested_price":sp,"range":{"low":lo,"high":hi},"explanation":(d.get("explanation") or "")[:300]}

def _confidence_band(conf:str)->float:
    base = MAX_AI_DEV_BASE
    return {"high": base*0.7, "medium": base*1.0, "low": base*1.25, "very_low": base*1.5}.get(conf, base)
def clamp_to_band(price:int, anchor:int, band_pct:float)->int:
    lo,hi = int(anchor*(1-band_pct)), int(anchor*(1+band_pct))
    return max(lo, min(hi, int(price)))

# ---------- Warmup ----------
def _warmup():
    try:
        dummy={"name":"VF8","brand":"Vinfast","year":THIS_YEAR-2,"mileage":20000,"battery_capacity_kwh":87,"province":"HCM","product_type":"xe"}
        if PROVIDER=="openai": _=call_openai(dummy)
        elif PROVIDER=="gemini": _=call_gemini(dummy)
        else:
            if os.getenv("GOOGLE_API_KEY"):
                try: _=call_gemini(dummy)
                except: pass
            if os.getenv("OPENAI_API_KEY"):
                try: _=call_openai(dummy)
                except: pass
    except: pass
threading.Thread(target=_warmup, daemon=True).start()

# ---------- API ----------
@app.get("/")
def health():
    return jsonify(service="pricing", version=VERSION, provider=PROVIDER,
                   keys={"openai":"present" if os.getenv("OPENAI_API_KEY") else "missing",
                         "gemini":"present" if os.getenv("GOOGLE_API_KEY") else "missing"}), 200

@app.post("/predict")
def predict():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify(error="bad_request", detail="Invalid JSON"), 400

    p = normalize(data)
    if (c := cache_get(p)): return jsonify(c), 200

    base_res = baseline_price(p)
    base_price = base_res["suggested_price"]
    segment = base_res["_meta"]["segment"]
    confidence = base_res["_meta"]["confidence"]
    diag = (base_res.get("_meta") or {}).get("diag", {}) or {}

    tasks=[]
    if PROVIDER=="openai": tasks=[("openai",call_openai)]
    elif PROVIDER=="gemini": tasks=[("gemini",call_gemini)]
    else:
        if os.getenv("GOOGLE_API_KEY"): tasks.append(("gemini",call_gemini))
        if os.getenv("OPENAI_API_KEY"): tasks.append(("openai",call_openai))

    ai_result, source = None, None
    if tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
            futs={ex.submit(fn,p): name for name,fn in tasks}
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=SOFT_TIMEOUT):
                    name=futs[fut]
                    try:
                        parsed = validate_result(json.loads(fut.result()))
                        ai_result, source = parsed, name
                        break
                    except Exception:
                        continue
            except concurrent.futures.TimeoutError:
                pass

    band = _confidence_band(confidence)
    if ai_result:
        weight = AI_WEIGHT
        if segment in ("e-ev-suv-3row","lux-ev"):
            weight = min(weight, 0.55)
        mixed = int(weight*ai_result["suggested_price"] + (1-weight)*base_price)
        sp = clamp_to_band(mixed, base_price, band)
        sp = round_nice(sp, segment)
        low = round_nice(int(sp*0.92), segment)
        high = round_nice(int(sp*1.08), segment)
        result = {"suggested_price": sp, "range": {"low": low, "high": high}, "explanation": ai_result.get("explanation","")}
    else:
        if STRICT_AI:
            return jsonify({"error":"ai_timeout","detail":"Không nhận được phản hồi AI trong thời gian cho phép."}), 504
        source="baseline"
        result = base_res
        result["suggested_price"] = round_nice(result["suggested_price"], segment)
        result["range"]["low"]  = round_nice(result["range"]["low"],  segment)
        result["range"]["high"] = round_nice(result["range"]["high"], segment)

    widen={"high":0.00,"medium":0.05,"low":0.12,"very_low":0.20}.get(confidence,0.12)
    sp=result["suggested_price"]
    half=max(sp-result["range"]["low"], result["range"]["high"]-sp)
    half=int(half*(1+widen)); result["range"]={"low":sp-half,"high":sp+half}

    expl, advice = build_friendly_text(sp, result["range"], segment, diag, source or "openai", band)
    result["explanation"] = expl
    result["advice"] = advice
    result["human_readable"] = f"AI gợi ý: {_fmt_vnd(sp)} (khung {_fmt_vnd(result['range']['low'])} – {_fmt_vnd(result['range']['high'])})."
    result["_meta"]={"source":source or "openai","segment":segment,"confidence":confidence,
                     "guards":{"ai_weight":AI_WEIGHT,"band_pct":band}}

    cache_set(p,result)
    return jsonify(result), 200

if __name__ == "__main__":
    port=int(os.getenv("PORT","5003"))
    app.run(host="0.0.0.0", port=port, debug=True)