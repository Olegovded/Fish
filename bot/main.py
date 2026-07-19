"""Точка входа: бот + веб-сервер мини-приложения в одном процессе.

Бот при старте сам привязывает кнопку меню к мини-приложению (self-bind): как
только процесс поднят там, где доступен Telegram, @Ribaku_bot начинает открывать
приложение — отдельная настройка через BotFather не нужна.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from aiohttp import web

from bot.config import Config
from bot.webapp.server import build_app
from bot.webapp.store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fishing-bot")


def _open_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎣 Открыть приложение", web_app=WebAppInfo(url=url))
    ]])


async def main() -> None:
    config = Config.load()
    store = Store(config.db_path)
    await store.init()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(message: Message) -> None:
        if config.webapp_url:
            await message.answer(
                "🎣 <b>Рыбаки</b> — дневник улова.\n\n"
                "Записывай уловы, следи за рекордами, смотри прогноз клёва и "
                "соревнуйся с друзьями. Жми кнопку ниже 👇",
                reply_markup=_open_kb(config.webapp_url),
            )
        else:
            await message.answer(
                "Приложение ещё не развёрнуто (не задан WEBAPP_URL). "
                "После деплоя здесь появится кнопка «Открыть приложение»."
            )

    @dp.message(F.web_app_data)
    async def _wad(message: Message) -> None:
        await message.answer("Принято ✅")

    # Раздаём мини-апп и API
    app = build_app(store, config.bot_token, dev_mode=False, bot_username=config.bot_username)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.web_host, config.web_port)
    await site.start()
    log.info("Мини-приложение слушает %s:%s", config.web_host, config.web_port)

    # Self-bind: кнопка меню -> мини-приложение
    if config.webapp_url:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="🎣 Открыть", web_app=WebAppInfo(url=config.webapp_url))
            )
            log.info("Кнопка меню привязана к %s", config.webapp_url)
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось привязать кнопку меню: %s", e)
    else:
        log.warning("WEBAPP_URL не задан — кнопка меню не привязана.")

    try:
        log.info("Бот запущен.")
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановка.")
