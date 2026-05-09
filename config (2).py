import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_IDS  = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))

DATABASE_URL = os.getenv("DATABASE_URL")   # Railway PostgreSQL URL

CARD_NUMBER = os.getenv("CARD_NUMBER", "0000 0000 0000 0000")
CARD_OWNER  = os.getenv("CARD_OWNER",  "Karta egasi")
VIP_PRICE   = int(os.getenv("VIP_PRICE", "20000"))
