import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import Config, load_config
from bot.db import Database
from bot.handlers import admin, client, common, rider


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config: Config = load_config()
    db = Database(config.db_path)
    await db.connect()

    bot = Bot(config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["config"] = config
    dp.include_router(common.router)
    dp.include_router(client.router)
    dp.include_router(rider.router)
    dp.include_router(admin.router)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
