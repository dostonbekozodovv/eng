"""
api.py — FastAPI backend for VocabLearn Telegram Mini App
Real DB dan ma'lumot qaytaradi.
DEBUG=true bo'lsa auth tekshirilmaydi (development uchun).
index.html ni "/" da serve qiladi.
"""

import os
import hmac
import hashlib
import json
import time
from urllib.parse import unquote, parse_qs

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from db import (
    get_conn,
    get_user,
    get_top_scores,
    get_top_referrals,
    add_score,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEBUG     = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI(title="VocabLearn API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth ────────────────────────────────────────
def verify_init_data(init_data: str) -> dict | None:
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed   = parse_qs(init_data, keep_blank_values=True)
        hash_val = parsed.pop("hash", [None])[0]
        if not hash_val:
            return None
        data_check = "\n".join(f"{k}={v[0]}" for k, v in sorted(parsed.items()))
        secret     = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed   = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, hash_val):
            return None
        auth_date = int(parsed.get("auth_date", [0])[0])
        if time.time() - auth_date > 86400:
            return None
        user_str = parsed.get("user", ["{}"])[0]
        return json.loads(unquote(user_str))
    except Exception:
        return None


def get_uid(request: Request) -> int | None:
    uid_h = request.headers.get("X-User-Id", "").strip()
    if not uid_h or not uid_h.isdigit():
        return None
    uid = int(uid_h)
    if DEBUG:
        return uid
    init_data = request.headers.get("X-Init-Data", "")
    user = verify_init_data(init_data)
    if user and user.get("id") == uid:
        return uid
    return None


def require_uid(request: Request, target_uid: int):
    if DEBUG:
        return
    if get_uid(request) != target_uid:
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")


# ─── Endpoints ───────────────────────────────────

@app.get("/")
async def root():
    """index.html ni serve qilish"""
    if os.path.exists("index.html"):
        return FileResponse("index.html", media_type="text/html")
    return {"status": "ok", "service": "VocabLearn API", "debug": DEBUG}


@app.get("/api/user/{user_id}")
async def get_user_data(user_id: int, request: Request):
    require_uid(request, user_id)
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    learned = user.get("learned_words") or []
    if isinstance(learned, str):
        try:
            learned = json.loads(learned)
        except Exception:
            learned = []

    return {
        "user_id":        user_id,
        "name":           user.get("name", "Foydalanuvchi"),
        "username":       user.get("username", ""),
        "score":          user.get("score", 0),
        "streak":         user.get("streak", 0),
        "referral_count": user.get("referral_count", 0),
        "level":          user.get("level", "beginner"),
        "current_group":  user.get("current_group", 1),
        "is_vip":         bool(user.get("is_vip", False)),
        "learned_words":  learned,
        "learned_count":  len(learned),
    }


@app.get("/api/rating")
async def get_rating(limit: int = Query(default=10, le=50)):
    """Real DB dan top foydalanuvchilar"""
    try:
        top = get_top_scores(limit)
        return [
            {
                "rank":     i + 1,
                "user_id":  u.get("user_id"),
                "name":     u.get("name", "Noma'lum"),
                "username": u.get("username", ""),
                "score":    u.get("score", 0),
                "is_vip":   bool(u.get("is_vip", False)),
            }
            for i, u in enumerate(top)
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rating/me/{user_id}")
async def get_my_rank(user_id: int, request: Request):
    """Mening reyting o'rnim"""
    require_uid(request, user_id)
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT COUNT(*)+1 FROM users WHERE score > "
            "(SELECT score FROM users WHERE user_id=%s)",
            (user_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return {"user_id": user_id, "rank": row[0] if row else "?"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/score/add")
async def add_score_ep(request: Request):
    """Quiz natijasidan ball qo'shish"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON xato")

    user_id = body.get("user_id")
    score   = int(body.get("score", 0))
    require_uid(request, user_id)

    if not user_id or not (0 < score <= 500):
        raise HTTPException(status_code=400, detail="Noto'g'ri ma'lumot")

    try:
        add_score(user_id, score)
        user = get_user(user_id)
        return {"ok": True, "new_score": user.get("score", 0) if user else 0, "added": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/referrals")
async def get_referral_top(limit: int = Query(default=10, le=50)):
    try:
        top = get_top_referrals(limit)
        return [
            {
                "rank":      i + 1,
                "user_id":   u.get("user_id"),
                "name":      u.get("name", "Noma'lum"),
                "referrals": u.get("referral_count", 0),
            }
            for i, u in enumerate(top)
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/battles/{user_id}")
async def get_battles(user_id: int, request: Request):
    require_uid(request, user_id)
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """SELECT opponent_name, result, my_score, opp_score, played_at
               FROM battles WHERE user_id=%s ORDER BY played_at DESC LIMIT 20""",
            (user_id,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = []
        for opp, res, ms, os_, ts in rows:
            result.append({
                "opp":    opp or "Noma'lum",
                "result": res or "draw",
                "s":      ms or 0,
                "o":      os_ or 0,
                "time":   _fmt(ts),
            })
        return result
    except Exception:
        return []


def _fmt(ts) -> str:
    if not ts:
        return "—"
    try:
        from datetime import datetime, timezone
        dt  = ts if not isinstance(ts, (int, float)) else datetime.fromtimestamp(ts, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        d   = (now - dt).total_seconds()
        if d < 86400:   return "Bugun " + dt.strftime("%H:%M")
        if d < 172800:  return "Kecha "  + dt.strftime("%H:%M")
        return f"{int(d/86400)} kun oldin"
    except Exception:
        return str(ts)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 VocabLearn API v2 | port={port} | DEBUG={DEBUG}")
    uvicorn.run(app, host="0.0.0.0", port=port)
