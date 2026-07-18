"""/start, помощь и обработка deep-link из карточки шеринга (гейтинг по ссылке)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import Config
from bot.db import Database
from bot.services import keyboards as kb

router = Router(name="start")

_WELCOME = (
    "🎣 <b>Дневник рыбака</b>\n\n"
    "Веди личный журнал поездок: что, где и на что клевало. Бот сам подтянет "
    "погоду и фазу луны, а со временем — покажет статистику по твоим местам.\n\n"
    "Локация всегда округляется до зоны ~1 км — точную точку бот не хранит.\n\n"
    "Жми <b>🎣 Новый отчёт</b>, чтобы начать."
)


@router.message(CommandStart(deep_link=True))
async def start_deeplink(
    message: Message, command: CommandObject, state: FSMContext,
    db: Database, config: Config,
) -> None:
    await state.clear()
    await db.ensure_user(message.from_user.id, message.from_user.username)
    payload = command.args or ""

    # Гейтинг по ссылке: r<id> — открыть конкретный отчёт из карточки.
    if payload.startswith("r") and payload[1:].isdigit():
        report = await db.get_report(int(payload[1:]))
        if report:
            from bot.services.share import build_share_card

            await message.answer(build_share_card(report, config.bot_username))
    await message.answer(_WELCOME, reply_markup=kb.main_menu(config.webapp_url or None))


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    await db.ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(_WELCOME, reply_markup=kb.main_menu(config.webapp_url or None))


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def help_cmd(message: Message, config: Config) -> None:
    await message.answer(
        "🎣 Новый отчёт — записать поездку\n"
        "📖 Мой дневник — история поездок\n"
        "📊 Статистика зоны — сводка по месту\n"
        "🗺 Карта — твои точки на карте (в мини-приложении)\n\n"
        "Данных по зоне пока может не быть — бот честно об этом скажет, "
        "а не выдумает прогноз.",
        reply_markup=kb.main_menu(config.webapp_url or None),
    )
