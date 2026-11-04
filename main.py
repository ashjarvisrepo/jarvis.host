import asyncio
import logging
from core.bot import create_bot
from core.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

async def main():
    print("Starting JARVIS SHOP EXTREME...", flush=True)
    cfg = load_config()
    print("Configuration loaded. Connecting to Discord...", flush=True)
    bot = create_bot(cfg)
    async with bot:
        try:
            await bot.start(cfg["discord"]["token"])
        finally:
            await bot.sellauth_notifications.close()
            await bot.verify_portal.close()
            await bot.local_dashboard.close()
            if getattr(bot.db, "conn", None):
                await bot.db.close()

if __name__ == "__main__":
    asyncio.run(main())
