"""
api.py — FastAPI backend for VocabLearn Telegram Mini App
Railway da bot bilan birga ishga tushadi.

Ishga tushirish uchun main.py ichiga qo'shing:
    import threading
    import uvicorn
    from api import app as fastapi_app

    def run_api():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

    threading.Thread(target=run_api, daemon=True).start()

Yoki alohida Procfile:
    web: python api.py
    worker: python Boot.py
"""

import os
import hmac
import hashlib
import json
import time
from urllib.parse import unquote, parse_qs

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# db.py dan import — Bot bilan bir xil DB ishlatadi
from db import (
    get_conn,
    get_user,
    get_top_scores,
    get_top_referrals,
    get_or_create_user,
    add_score,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_PORT  = int(os.getenv("API_PORT", os.getenv("PORT", 8000)))

app = FastAPI(title="VocabLearn API", version="1.0.0")

# CORS — Telegram Web App va Railway domeniga ruxsat
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Railway + Telegram
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Telegram initData tekshirish (xavfsizlik)
# ──────────────────────────────────────────────
def verify_telegram_init_data(init_data: str) -> dict | None:
    """
    Telegram initData ni HMAC-SHA256 bilan tekshiradi.
    Muvaffaqiyatli bo'lsa user dict qaytaradi, aks holda None.
    """
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        hash_val = parsed.pop("hash", [None])[0]
        if not hash_val:
            return None

        # Data string yasash
        data_check = "\n".join(
            f"{k}={v[0]}" for k, v in sorted(parsed.items())
        )
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed, hash_val):
            return None

        # auth_date: 1 soatdan eski bo'lsa rad et
        auth_date = int(parsed.get("auth_date", [0])[0])
        if time.time() - auth_date > 3600:
            return None

        user_str = parsed.get("user", ["{}"])[0]
        return json.loads(unquote(user_str))
    except Exception:
        return None


def get_uid_from_request(request: Request) -> int | None:
    """
    Request headerlaridan user_id oladi.
    X-User-Id header yoki initData verificatsiyasi orqali.
    """
    # 1) X-User-Id header (development uchun)
    uid_header = request.headers.get("X-User-Id", "").strip()
    if uid_header and uid_header.isdigit():
        uid = int(uid_header)
        # Production: initData ham tekshiriladi
        init_data = request.headers.get("X-Init-Data", "")
        if init_data:
            user = verify_telegram_init_data(init_data)
            if user and user.get("id") == uid:
                return uid
            # initData noto'g'ri — lekin development rejimda o'tkazib yuborish
            if os.getenv("DEBUG", "false").lower() == "true":
                return uid
            return None
        # initData yo'q — development rejim
        if os.getenv("DEBUG", "false").lower() == "true":
            return uid
        return None
    return None


# ──────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "VocabLearn API"}


@app.get("/api/user/{user_id}")
async def get_user_data(user_id: int, request: Request):
    """
    Foydalanuvchi ma'lumotlarini qaytaradi.
    """
    # Xavfsizlik: faqat o'z ma'lumotiga kirish
    req_uid = get_uid_from_request(request)
    debug = os.getenv("DEBUG", "false").lower() == "true"
    if not debug and req_uid != user_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")

    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # Xavfsiz maydonlar
    return {
        "user_id":                   user_id,
        "name":                      user.get("name", "Foydalanuvchi"),
        "username":                  user.get("username", ""),
        "score":                     user.get("score", 0),
        "streak":                    user.get("streak", 0),
        "best_streak":               user.get("best_streak", 0),
        "referral_count":            user.get("referral_count", 0),
        "level":                     user.get("level", "beginner"),
        "current_group":             user.get("current_group", 1),
        "is_vip":                    bool(user.get("is_vip", False)),
        "battles_won":               user.get("battles_won", 0),
        "battles_lost":              user.get("battles_lost", 0),
        "battles_draw":              user.get("battles_draw", 0),
        "learned_words_list":        _parse_json_field(user.get("learned_words_list", "[]")),
        "current_group_words":       _parse_json_field(user.get("current_group_words", "[]")),
        "current_group_learned_count": user.get("current_group_learned_count", 0),
        "current_group_total":       user.get("current_group_total", 20),
        "total_groups":              user.get("total_groups", 40),
    }


@app.get("/api/rating")
async def get_rating(limit: int = Query(default=10, le=50)):
    """
    Top foydalanuvchilar reytingini qaytaradi (real DB dan).
    """
    try:
        top = get_top_scores(limit)
        result = []
        for i, u in enumerate(top):
            result.append({
                "rank":    i + 1,
                "user_id": u.get("user_id") or u.get("id"),
                "name":    u.get("name", "Noma'lum"),
                "username": u.get("username", ""),
                "score":   u.get("score", 0),
                "is_me":   False,   # frontend o'zi solishtiради
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rating/me/{user_id}")
async def get_my_rank(user_id: int, request: Request):
    """
    Berilgan foydalanuvchining reyting o'rnini qaytaradi.
    """
    req_uid = get_uid_from_request(request)
    debug = os.getenv("DEBUG", "false").lower() == "true"
    if not debug and req_uid != user_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")

    try:
        conn = get_conn()
        cur  = conn.cursor()
        # Nechta odam bu userdan ko'p ball olgan
        cur.execute(
            "SELECT COUNT(*)+1 as rank FROM users WHERE score > (SELECT score FROM users WHERE user_id=%s)",
            (user_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        rank = row[0] if row else "?"
        return {"user_id": user_id, "rank": rank}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/battles/{user_id}")
async def get_battles(user_id: int, request: Request):
    """
    Foydalanuvchining duel tarixini qaytaradi.
    """
    req_uid = get_uid_from_request(request)
    debug = os.getenv("DEBUG", "false").lower() == "true"
    if not debug and req_uid != user_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")

    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """SELECT opponent_name, result, my_score, opp_score,
                      played_at
               FROM battles
               WHERE user_id = %s
               ORDER BY played_at DESC
               LIMIT 20""",
            (user_id,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = []
        for r in rows:
            opp, res, ms, os_, ts = r
            result.append({
                "opp":    opp or "Noma'lum",
                "result": res or "draw",
                "s":      ms or 0,
                "o":      os_ or 0,
                "time":   _format_time(ts),
            })
        return result
    except Exception as e:
        # battles jadvali bo'lmasa — bo'sh qaytaramiz
        return []


@app.post("/api/score/add")
async def add_score_endpoint(request: Request):
    """
    Quiz natijasidan ball qo'shish.
    Body: { "user_id": int, "score": int, "reason": str }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON xato")

    user_id = body.get("user_id")
    score   = body.get("score", 0)
    reason  = body.get("reason", "quiz")

    req_uid = get_uid_from_request(request)
    debug = os.getenv("DEBUG", "false").lower() == "true"
    if not debug and req_uid != user_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")

    if not user_id or score <= 0 or score > 500:
        raise HTTPException(status_code=400, detail="Noto'g'ri ma'lumot")

    try:
        add_score(user_id, score)
        user = get_user(user_id)
        return {
            "ok": True,
            "new_score": user.get("score", 0) if user else 0,
            "added": score,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/leaderboard/referrals")
async def get_referral_leaderboard(limit: int = Query(default=10, le=50)):
    """Referal reytingi"""
    try:
        top = get_top_referrals(limit)
        return [
            {
                "rank":     i + 1,
                "user_id":  u.get("user_id") or u.get("id"),
                "name":     u.get("name", "Noma'lum"),
                "referrals": u.get("referral_count", 0),
            }
            for i, u in enumerate(top)
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# Yordamchi funksiyalar
# ──────────────────────────────────────────────

def _parse_json_field(val):
    if isinstance(val, (list, dict)):
        return val
    if not val:
        return []
    try:
        return json.loads(val)
    except Exception:
        return []


def _format_time(ts) -> str:
    """Timestamp ni o'qimli formatga o'tkazish"""
    if not ts:
        return "—"
    try:
        from datetime import datetime, timezone
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            dt = ts
        now = datetime.now(tz=timezone.utc)
        diff = (now - dt).total_seconds()
        if diff < 86400:
            return "Bugun " + dt.strftime("%H:%M")
        elif diff < 172800:
            return "Kecha " + dt.strftime("%H:%M")
        else:
            days = int(diff / 86400)
            return f"{days} kun oldin"
    except Exception:
        return str(ts)


# ──────────────────────────────────────────────
# Ishga tushirish (alohida server sifatida)
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print(f"🚀 VocabLearn API starting on port {API_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
