"""Фаза луны — считается локально, без обращений к API (значит, бесплатно).

Алгоритм: возраст луны в днях от известного новолуния, приведённый к
синодическому месяцу (29.53 суток). Точности хватает для рыболовного
контекста — нам важна фаза и примерная освещённость, а не астрономическая
эфемерида.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone

_SYNODIC_MONTH = 29.530588853
# Опорное новолуние: 2000-01-06 18:14 UTC (Юлианская дата 2451550.1).
_KNOWN_NEW_MOON_JD = 2451550.1


@dataclass(frozen=True)
class MoonInfo:
    phase_name: str
    emoji: str
    illumination: float  # доля освещённости диска, 0..1
    age_days: float      # возраст луны в сутках


def _to_julian(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = dt.timestamp()
    return ts / 86400.0 + 2440587.5


def moon_for(on: date | datetime) -> MoonInfo:
    if isinstance(on, datetime):
        dt = on
    else:
        dt = datetime(on.year, on.month, on.day, 12, 0, tzinfo=timezone.utc)

    jd = _to_julian(dt)
    age = (jd - _KNOWN_NEW_MOON_JD) % _SYNODIC_MONTH
    # Освещённость через фазовый угол.
    phase_angle = 2.0 * math.pi * age / _SYNODIC_MONTH
    illumination = (1.0 - math.cos(phase_angle)) / 2.0

    name, emoji = _classify(age)
    return MoonInfo(
        phase_name=name,
        emoji=emoji,
        illumination=round(illumination, 2),
        age_days=round(age, 1),
    )


def _classify(age: float) -> tuple[str, str]:
    # Восемь фаз по возрасту луны.
    slot = _SYNODIC_MONTH / 8.0
    idx = int((age + slot / 2) // slot) % 8
    table = [
        ("Новолуние", "🌑"),
        ("Растущий серп", "🌒"),
        ("Первая четверть", "🌓"),
        ("Растущая луна", "🌔"),
        ("Полнолуние", "🌕"),
        ("Убывающая луна", "🌖"),
        ("Последняя четверть", "🌗"),
        ("Убывающий серп", "🌘"),
    ]
    return table[idx]
