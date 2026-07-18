"""Точка входа: поднимает бота (long polling) и, при наличии WEBAPP_URL,
веб-сервер мини-приложения — в одном процессе.

Зависимости (db, config) прокидываются в хендлеры через DI aiogram: то, что
передано в start_polling как kwargs, доступно хендлерам по имени аргумента.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from bot.config import Config
from bot.db import Database
from bot.handlers import diary, report, start, stats
from bot.webapp.server import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fishing-bot")


async def _run_webapp(config: Config, db: Database) -> web.AppRunner | None:
    if not config.webapp_url:
        log.info("WEBAPP_URL не задан — мини-приложение отключено.")
        return None
    app = build_app(db, config.bot_token)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.web_host, config.web_port)
    await site.start()
    log.info("Мини-приложение слушает %s:%s", config.web_host, config.web_port)
    return runner


async def main() -> None:
    config = Config.load()
    db = Database(config.db_path)
    await db.init()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_routers(start.router, report.router, diary.router, stats.router)

    runner = await _run_webapp(config, db)
    try:
        log.info("Бот запущен.")
        await dp.start_polling(bot, db=db, config=config)
    finally:
        if runner is not None:
            await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановка.")
