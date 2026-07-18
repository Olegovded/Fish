"""Личный дневник рыбака — история своих отчётов.

Работает и без чужих данных — решает проблему холодного старта (по брифу).
Карта живёт в мини-приложении; здесь — компактный список в чате.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot.db import Database

router = Router(name="diary")


@router.message(F.text == "📖 Мой дневник")
@router.message(F.text.startswith("/diary"))
async def show_diary(message: Message, db: Database) -> None:
    reports = await db.list_user_reports(message.from_user.id, limit=15)
    if not reports:
        await message.answer(
            "В дневнике пока пусто. Запишите первый отчёт — 🎣 Новый отчёт."
        )
        return

    total = await db.user_report_count(message.from_user.id)
    with_catch = sum(1 for r in reports if r.caught)
    lines = [f"📖 <b>Ваш дневник</b> — всего отчётов: {total}\n"]
    for r in reports:
        mark = "✅" if r.caught else "▫️"
        bits = [f"{mark} {r.report_date}"]
        if r.caught and r.species:
            bits.append(r.species)
        if r.bait:
            bits.append(f"на {r.bait}")
        bits.append(f"· зона {r.zone_lat:.3f},{r.zone_lon:.3f}")
        lines.append(" ".join(bits))
    lines.append(
        f"\nПоказаны последние {len(reports)}. С уловом из них: {with_catch}."
    )
    await message.answer("\n".join(lines))
