"""Карточка шеринга улова — встроенный канал роста с первого дня.

Реализуем оба механизма из брифа:
1. Водяной знак бота на карточке (подпись @bot внизу).
2. Гейтинг по ссылке: детали открываются только через бота — в карточке
   deep-link `https://t.me/<bot>?start=r<id>`, по которому новый пользователь
   попадает в бота и видит отчёт.

Локация в карточке — только зона (округлённые координаты), никогда точный пин.
"""
from __future__ import annotations

from bot.db import Report


def build_share_card(report: Report, bot_username: str) -> str:
    head = "🎣 Улов!" if report.caught else "🐟 Рыбалка (без улова)"
    lines = [f"<b>{head}</b>", ""]

    if report.caught and report.species:
        lines.append(f"🐠 Рыба: <b>{report.species}</b>")
    if report.bait:
        lines.append(f"🪝 Сработало: {report.bait}")
    lines.append(f"📍 Зона: {report.zone_lat:.3f}, {report.zone_lon:.3f}")
    lines.append(f"📅 Дата: {report.report_date}")
    if report.weather_text:
        lines.append(f"🌤 Погода: {report.weather_text}")
    if report.moon_text:
        lines.append(f"🌙 Луна: {report.moon_text}")
    if report.comment:
        lines.append("")
        lines.append(f"💬 {report.comment}")

    deep_link = f"https://t.me/{bot_username}?start=r{report.id}"
    lines.append("")
    lines.append(f'👉 <a href="{deep_link}">Открыть в боте и вести свой дневник</a>')
    lines.append(f"<i>@{bot_username} — дневник рыбака</i>")
    return "\n".join(lines)
