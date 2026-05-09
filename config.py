import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_IDS  = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))

DATABASE_URL = os.getenv("DATABASE_URL")   # Railway PostgreSQL URL

CARD_NUMBER = os.getenv("CARD_NUMBER", "0000 0000 0000 0000")
CARD_OWNER  = os.getenv("CARD_OWNER",  "Karta egasi")
VIP_PRICE   = int(os.getenv("VIP_PRICE", "5000"))

# Majburiy kanal — Railway Variables dan o'rnatiladi
# CHANNEL_ID=-1001234567890  (bot kanal admin bo'lishi shart)
# CHANNEL_USERNAME=@kanalim  (foydalanuvchiga ko'rsatish uchun)
CHANNEL_ID       = os.getenv("CHANNEL_ID", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")

# Haftalik referal bonus uchun minimal taklif soni
MIN_REFERRALS_FOR_BONUS = int(os.getenv("MIN_REFERRALS_FOR_BONUS", "5"))
