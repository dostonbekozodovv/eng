"""
run.py — Railway da bot + API birga ishga tushirish

Railway environment variables:
  BOT_TOKEN = your_bot_token
  DATABASE_URL = postgresql://...
  DEBUG = false          # production da false bo'lsin
  API_PORT = 8000        # Railway o'zi beradi (PORT env)

Procfile (Railway da faqat bitta process):
  web: python run.py

Bu fayl:
  1) FastAPI serverni background thread da ishga tushiradi
  2) Aiogram botni asosiy threadda polling qiladi
"""

import asyncio
import os
import threading
import uvicorn

# API ni import qilish
from api import app as fastapi_app

API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", 8000)))


def start_api():
    """FastAPI ni alohida threadda ishga tushirish"""
    print(f"🌐 API server starting on port {API_PORT}...")
    uvicorn.run(
        fastapi_app,
        host="0.0.0.0",
        port=API_PORT,
        log_level="warning",
    )


async def start_bot():
    """Aiogram botni ishga tushirish"""
    from db import init_db
    init_db()
    print("🤖 Bot starting...")

    # Boot.py dagi main() ni chaqirish
    from Boot import dp, bot, weekly_bonus_task, vip_expiry_task
    from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats

    private_commands = [
        BotCommand(command="start",    description="🚀 Botni boshlash"),
        BotCommand(command="menu",     description="🏠 Bosh menyu"),
        BotCommand(command="restart",  description="🔄 Qayta ishga tushirish"),
        BotCommand(command="quiz",     description="🎯 Viktorina"),
        BotCommand(command="test",     description="🧠 Test"),
        BotCommand(command="learn",    description="📚 So'z o'rganish"),
        BotCommand(command="grammar",  description="📖 Grammatika"),
        BotCommand(command="streak",   description="🔥 Streak"),
        BotCommand(command="rating",   description="🏆 Reyting"),
        BotCommand(command="referral", description="👥 Referal"),
        BotCommand(command="vip",      description="💎 VIP"),
    ]
    group_commands = [
        BotCommand(command="quiz",     description="🎯 Viktorina"),
        BotCommand(command="stopquiz", description="⏹ To'xtatish"),
        BotCommand(command="restart",  description="🔄 Qayta ishga tushirish"),
    ]
    await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(group_commands,   scope=BotCommandScopeAllGroupChats())

    asyncio.create_task(weekly_bonus_task())
    asyncio.create_task(vip_expiry_task())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    # API ni thread da ishga tushir
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()

    # Botni asosiy loop da ishga tushir
    asyncio.run(start_bot())

