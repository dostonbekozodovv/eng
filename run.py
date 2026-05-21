import asyncio
import os
import threading
import uvicorn
from api import app as fastapi_app

PORT = int(os.getenv("PORT", 8000))

def start_api():
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT, log_level="info")

async def main():
    # API ni thread da ishga tushir (daemon=False — muhim!)
    t = threading.Thread(target=start_api, daemon=False)
    t.start()
    print(f"🌐 API started on port {PORT}")

    # bot.py dagi main() ni chaqir — u o'zi polling qiladi
    from bot import main as bot_main
    await bot_main()

if __name__ == "__main__":
    asyncio.run(main())
