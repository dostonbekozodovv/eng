import os
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════
# BOT ASOSIY SOZLAMALAR
# ══════════════════════════════════════════════════
BOT_TOKEN    = os.getenv("BOT_TOKEN")
ADMIN_IDS    = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))
DATABASE_URL = os.getenv("DATABASE_URL")

# ══════════════════════════════════════════════════
# TO'LOV VA VIP SOZLAMALAR
# ══════════════════════════════════════════════════
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000 0000 0000 0000")
CARD_OWNER  = os.getenv("CARD_OWNER",  "Karta egasi")

# VIP narxi (so'mda)
VIP_PRICE = int(os.getenv("VIP_PRICE", "20000"))

# Bepul VIP uchun kerakli referal soni
VIP_REF_COUNT = int(os.getenv("VIP_REF_COUNT", "7"))

# VIP muddati (oyda)
VIP_MONTHS = int(os.getenv("VIP_MONTHS", "1"))

# ══════════════════════════════════════════════════
# MAJBURIY KANAL
# ══════════════════════════════════════════════════
CHANNEL_ID       = os.getenv("CHANNEL_ID", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")

# ══════════════════════════════════════════════════
# BALL TIZIMI
# ══════════════════════════════════════════════════
REFERRAL_BONUS   = int(os.getenv("REFERRAL_BONUS",   "200"))
WORD_LEARN_BONUS = int(os.getenv("WORD_LEARN_BONUS",  "2"))
TEST_SCORE_BONUS = int(os.getenv("TEST_SCORE_BONUS",  "10"))
SURVEY_BONUS     = int(os.getenv("SURVEY_BONUS",      "500"))

_lvl = os.getenv("LEVEL_TEST_BONUS", "5,20,35").split(",")
LEVEL_TEST_BONUS = {
    "beginner":     int(_lvl[0]),
    "intermediate": int(_lvl[1]),
    "advanced":     int(_lvl[2]),
}

# ══════════════════════════════════════════════════
# PUL YUTUG'I SOZLAMALAR
# ══════════════════════════════════════════════════
PRIZE_BALL_TARGET  = int(os.getenv("PRIZE_BALL_TARGET",  "10000"))
PRIZE_SCORE_AMOUNT = int(os.getenv("PRIZE_SCORE_AMOUNT", "10000"))
PRIZE_MIN_REFERRAL = int(os.getenv("PRIZE_MIN_REFERRAL", "1"))

# ══════════════════════════════════════════════════
# HAFTALIK REFERAL O'YINI
# ══════════════════════════════════════════════════
PRIZE_REF_AMOUNT        = int(os.getenv("PRIZE_REF_AMOUNT",        "10000"))
MIN_REFERRALS_FOR_BONUS = int(os.getenv("MIN_REFERRALS_FOR_BONUS", "5"))
WEEKLY_BONUS_PRICE      = int(os.getenv("WEEKLY_BONUS_PRICE",      "10000"))

# ══════════════════════════════════════════════════
# BELLASHUV (DUEL) SOZLAMALAR
# ══════════════════════════════════════════════════
BATTLE_QUESTION_COUNT = int(os.getenv("BATTLE_QUESTION_COUNT", "20"))
BATTLE_TIMEOUT        = int(os.getenv("BATTLE_TIMEOUT",        "20"))
BATTLE_WIN_BALL       = int(os.getenv("BATTLE_WIN_BALL",       "50"))
BATTLE_LOSE_BALL      = -abs(int(os.getenv("BATTLE_LOSE_BALL",  "50")))
BATTLE_LEAVE_BALL     = -abs(int(os.getenv("BATTLE_LEAVE_BALL", "100")))
BATTLE_FRIEND_LEAVE   = int(os.getenv("BATTLE_FRIEND_LEAVE",   "0"))
