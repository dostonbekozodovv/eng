"""
run.py — Railway da bot + API birga ishga tushirish
Bot fayli: bot.py
"""

import asyncio
import os
import threading
import uvicorn

from api import app as fastapi_app

API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", 8000)))


def start_api():
    """FastAPI ni alohida threadda ishga tushirish"""
    print(f"🌐 API server starting on port {API_PORT}...")
    uvicorn.run(
        fastapi_app,
        host="0.0.0.0",
        port=API_PORT,
        log_level="info",
    )


async def start_bot():
    """bot.py dagi bot ni ishga tushirish"""
    from db import init_db
    init_db()
    print("🤖 Bot starting...")

    # bot.py dan import (Boot.py emas!)
    from bot import dp, bot
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

    # bot.py da mavjud bo'lsa weekly_bonus_task va vip_expiry_task ni ham ishga tushir
    try:
        from bot import weekly_bonus_task, vip_expiry_task
        asyncio.create_task(weekly_bonus_task())
        asyncio.create_task(vip_expiry_task())
        print("✅ Background tasks started")
    except ImportError:
        print("⚠️  weekly_bonus_task / vip_expiry_task topilmadi, o'tkazildi")

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    # API ni background thread da ishga tushir
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()

    # Botni asosiy asyncio loop da ishga tushir
    asyncio.run(start_bot())
