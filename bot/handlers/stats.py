"""Простая статистика по зоне: сколько отчётов за период, % с уловом.

Без алгоритма доверия — сырые цифры (по брифу). Честность важнее «красивого
ответа»: если данных по зоне нет — так и говорим.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import Config
from bot.db import Database
from bot.handlers.states import StatsFlow
from bot.services import keyboards as kb
from bot.services.geo import snap_to_zone

router = Router(name="stats")


@router.message(F.text == "📊 Статистика зоны")
@router.message(F.text.startswith("/stats"))
async def ask_zone(message: Message, state: FSMContext) -> None:
    await state.set_state(StatsFlow.location)
    await message.answer(
        "Пришлите локацию места — покажу сводку по зоне ~1 км вокруг. 📍",
        reply_markup=kb.location_kb(),
    )


@router.message(StatsFlow.location, F.location)
async def show_zone_stats(
    message: Message, state: FSMContext, db: Database, config: Config
) -> None:
    loc = message.location
    zone = snap_to_zone(loc.latitude, loc.longitude, config.grid_size_m)
    await state.clear()

    stats = await db.zone_stats(zone.zone_id)
    menu = kb.main_menu(config.webapp_url or None)
    if not stats.total:
        await message.answer(
            f"📊 Зона {zone.label}\n\n"
            "По этой зоне пока нет отчётов. Данных нет — и это честный ответ. "
            "Запишите свой отчёт первым 🎣",
            reply_markup=menu,
        )
        return

    pct = int(stats.catch_ratio * 100)
    lines = [
        f"📊 <b>Зона {zone.label}</b> (за 2 недели)",
        "",
        f"Отчётов: {stats.total}",
        f"С уловом: {pct}%",
    ]
    if stats.top_species:
        top = ", ".join(f"{s} ({c})" for s, c in stats.top_species)
        lines.append(f"🏆 Чаще ловят: {top}")
    await message.answer("\n".join(lines), reply_markup=menu)
