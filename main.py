import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import BOT_TOKEN, LOG_FILE
from fitcontroller.api import start_api
from fitcontroller.db import init_db
from fitcontroller.logging_setup import setup_logging
from fitcontroller.reminders import reminder_loop
from fitcontroller.handlers import router

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Начать (Главное меню)"),
    BotCommand(command="profile", description="Мой профиль"),
    BotCommand(command="reset", description="Изменить мои данные"),
    BotCommand(command="support", description="Поддержка"),
]


async def main() -> None:
    setup_logging(LOG_FILE)
    logger.info("Logging to %s", LOG_FILE)

    await init_db()

    api_runner = await start_api()

    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands(COMMANDS)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    reminders = asyncio.create_task(reminder_loop(bot))

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        await bot.session.close()
        await api_runner.cleanup()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
