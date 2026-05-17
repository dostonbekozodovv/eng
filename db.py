import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta
from config import DATABASE_URL

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            username TEXT DEFAULT '',
            level TEXT,
            score INT DEFAULT 0,
            streak INT DEFAULT 0,
            last_active DATE,
            is_vip BOOLEAN DEFAULT FALSE,
            vip_since TIMESTAMP,
            vip_expires TIMESTAMP,
            referred_by BIGINT,
            referral_count INT DEFAULT 0,
            referral_earnings BIGINT DEFAULT 0,
            learned_words TEXT[] DEFAULT '{}',
            current_group INT DEFAULT 1,
            referral_notified BOOLEAN DEFAULT FALSE,
            prize_claimed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id SERIAL PRIMARY KEY,
            referrer_id BIGINT REFERENCES users(user_id),
            referred_id BIGINT REFERENCES users(user_id),
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS vip_requests (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            full_name TEXT,
            amount INT,
            check_file_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    for col_sql in [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS current_group INT DEFAULT 1;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_expires TIMESTAMP;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_notified BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS prize_claimed BOOLEAN DEFAULT FALSE;",
    ]:
        cur.execute(col_sql)
    conn.commit()
    cur.close()
    conn.close()

def get_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def get_or_create_user(user_id: int, name: str, username: str, referrer_id: int = None):
    user = get_user(user_id)
    if not user:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (user_id, name, username, referred_by, last_active, streak, current_group)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id, name, username or '', referrer_id, str(date.today()), 1, 1))

        if referrer_id and referrer_id != user_id:
            cur.execute(
                "UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s",
                (referrer_id,)
            )
            cur.execute(
                "INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s)",
                (referrer_id, user_id)
            )
        conn.commit()
        cur.close()
        conn.close()
        return get_user(user_id)
    return user

def update_user_level(user_id: int, level: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET level = %s WHERE user_id = %s", (level, user_id))
    conn.commit()
    cur.close()
    conn.close()

def update_user_group(user_id: int, new_group: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET current_group = %s WHERE user_id = %s", (new_group, user_id))
    conn.commit()
    cur.close()
    conn.close()

def update_streak(user_id: int):
    user = get_user(user_id)
    if not user:
        return
    today  = date.today()
    last   = user.get("last_active")
    streak = user.get("streak", 0)
    if last:
        if isinstance(last, str):
            last = datetime.strptime(last, "%Y-%m-%d").date()
        diff = (today - last).days
        if diff == 1:
            streak += 1
        elif diff > 1:
            streak = 1
    else:
        streak = 1
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET streak = %s, last_active = %s WHERE user_id = %s",
        (streak, str(today), user_id)
    )
    conn.commit()
    cur.close()
    conn.close()

def add_score(user_id: int, points: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET score = score + %s WHERE user_id = %s", (points, user_id))
    conn.commit()
    cur.close()
    conn.close()

def add_referral_earnings(user_id: int, amount: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET referral_earnings = referral_earnings + %s WHERE user_id = %s",
        (amount, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()

def add_learned_word(user_id: int, word: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users SET learned_words = array_append(learned_words, %s)
        WHERE user_id = %s AND NOT (%s = ANY(learned_words))
    """, (word, user_id, word))
    conn.commit()
    cur.close()
    conn.close()

def set_vip(user_id: int, is_vip_val: bool = True, months: int = 1):
    conn = get_conn()
    cur = conn.cursor()
    if is_vip_val:
        now     = datetime.now()
        expires = now + timedelta(days=30 * months)
        cur.execute(
            "UPDATE users SET is_vip = TRUE, vip_since = %s, vip_expires = %s WHERE user_id = %s",
            (now, expires, user_id)
        )
    else:
        cur.execute(
            "UPDATE users SET is_vip = FALSE, vip_expires = NULL WHERE user_id = %s",
            (user_id,)
        )
    conn.commit()
    cur.close()
    conn.close()

def is_vip(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user.get("is_vip"):
        return False
    expires = user.get("vip_expires")
    if expires is None:
        return True
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    return datetime.now() < expires

def get_expired_vip_users() -> list:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT user_id, name, vip_expires
        FROM users
        WHERE is_vip = TRUE AND vip_expires IS NOT NULL AND vip_expires < NOW()
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def get_expiring_soon_vip_users(hours: int = 24) -> list:
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT user_id, name, vip_expires
        FROM users
        WHERE is_vip = TRUE
          AND vip_expires IS NOT NULL
          AND vip_expires BETWEEN NOW() AND NOW() + INTERVAL '%s hours'
    """, (hours,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def create_vip_request(user_id: int, full_name: str, amount: int, check_file_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO vip_requests (user_id, full_name, amount, check_file_id) VALUES (%s, %s, %s, %s)",
        (user_id, full_name, amount, check_file_id)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_pending_vip_requests():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM vip_requests WHERE status = 'pending' ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def update_vip_request_status(request_id: int, status: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE vip_requests SET status = %s WHERE id = %s", (status, request_id))
    conn.commit()
    cur.close()
    conn.close()

def get_top_scores(limit=10):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT user_id, name, username, score, is_vip FROM users ORDER BY score DESC LIMIT %s",
        (limit,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def get_top_referrals(limit=10):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT user_id, name, username, referral_count, referral_earnings "
        "FROM users ORDER BY referral_count DESC LIMIT %s",
        (limit,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def get_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE is_vip = TRUE")
    vip = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM vip_requests WHERE status = 'pending'")
    pending = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"total": total, "vip": vip, "pending_vip": pending}

def get_all_user_ids():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    ids = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return ids

def get_all_vip_users() -> list:
    """Barcha aktiv VIP foydalanuvchilar ro'yxati (muddati o'tmagan)"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT user_id, name, username, vip_since, vip_expires
        FROM users
        WHERE is_vip = TRUE
        ORDER BY vip_expires ASC NULLS LAST
    """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows
