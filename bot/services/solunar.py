"""Прогноз клёва по солнечно-лунной теории (solunar) — считается локально.

Идея solunar-теории: рыба активнее, когда Луна в верхней/нижней кульминации
(«большие периоды») и на восходе/заходе Луны («малые периоды»). Балл дня выше
у новолуния и полнолуния. Всё это считается из положения Луны для места и даты
— без нейросетей, без внешних сервисов, бесплатно.

Положение Луны — по компактным формулам Пола Шлютера (точность в несколько
угловых минут), чего с запасом хватает для окон клёва.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

_RAD = math.pi / 180.0
_SYN = 29.530588853


def _rev(x: float) -> float:
    return x - 360.0 * math.floor(x / 360.0)


def _moon_radec(dt: datetime) -> tuple[float, float, float]:
    """Возвращает (RA°, Dec°, Ls°) Луны на момент UTC. Ls — для звёздного времени."""
    d = (
        367 * dt.year
        - (7 * (dt.year + (dt.month + 9) // 12)) // 4
        + (275 * dt.month) // 9
        + dt.day
        - 730530
        + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24.0
    )
    ecl = 23.4393 - 3.563e-7 * d

    # Элементы орбиты Луны
    N = _rev(125.1228 - 0.0529538083 * d)
    i = 5.1454
    w = _rev(318.0634 + 0.1643573223 * d)
    e = 0.054900
    M = _rev(115.3654 + 13.0649929509 * d)

    # Солнце — для возмущений и звёздного времени
    ws = 282.9404 + 4.70935e-5 * d
    Ms = _rev(356.0470 + 0.9856002585 * d)
    Ls = _rev(ws + Ms)

    # Уравнение Кеплера
    E = M + (180 / math.pi) * e * math.sin(M * _RAD) * (1 + e * math.cos(M * _RAD))
    for _ in range(3):
        E = E - (E - (180 / math.pi) * e * math.sin(E * _RAD) - M) / (
            1 - e * math.cos(E * _RAD)
        )

    x = math.cos(E * _RAD) - e
    y = math.sqrt(1 - e * e) * math.sin(E * _RAD)
    r = math.hypot(x, y)
    v = _rev(math.degrees(math.atan2(y, x)))

    xh = r * (
        math.cos(N * _RAD) * math.cos((v + w) * _RAD)
        - math.sin(N * _RAD) * math.sin((v + w) * _RAD) * math.cos(i * _RAD)
    )
    yh = r * (
        math.sin(N * _RAD) * math.cos((v + w) * _RAD)
        + math.cos(N * _RAD) * math.sin((v + w) * _RAD) * math.cos(i * _RAD)
    )
    zh = r * (math.sin((v + w) * _RAD) * math.sin(i * _RAD))

    lon = _rev(math.degrees(math.atan2(yh, xh)))
    lat = math.degrees(math.atan2(zh, math.hypot(xh, yh)))

    # Основные возмущения Луны
    Lm = _rev(N + w + M)
    D = _rev(Lm - Ls)
    F = _rev(Lm - N)
    lon += (
        -1.274 * math.sin((M - 2 * D) * _RAD)
        + 0.658 * math.sin((2 * D) * _RAD)
        - 0.186 * math.sin((Ms) * _RAD)
        - 0.059 * math.sin((2 * M - 2 * D) * _RAD)
        - 0.057 * math.sin((M - 2 * D + Ms) * _RAD)
        + 0.053 * math.sin((M + 2 * D) * _RAD)
        + 0.046 * math.sin((2 * D - Ms) * _RAD)
        + 0.041 * math.sin((M - Ms) * _RAD)
        - 0.035 * math.sin((D) * _RAD)
        - 0.031 * math.sin((M + Ms) * _RAD)
        - 0.015 * math.sin((2 * F - 2 * D) * _RAD)
        + 0.011 * math.sin((M - 4 * D) * _RAD)
    )
    lat += (
        -0.173 * math.sin((F - 2 * D) * _RAD)
        - 0.055 * math.sin((M - F - 2 * D) * _RAD)
        - 0.046 * math.sin((M + F - 2 * D) * _RAD)
        + 0.033 * math.sin((F + 2 * D) * _RAD)
        + 0.017 * math.sin((2 * M + F) * _RAD)
    )

    # Эклиптика -> экватор
    xe = math.cos(lon * _RAD) * math.cos(lat * _RAD)
    ye = math.sin(lon * _RAD) * math.cos(lat * _RAD)
    ze = math.sin(lat * _RAD)
    xq = xe
    yq = ye * math.cos(ecl * _RAD) - ze * math.sin(ecl * _RAD)
    zq = ye * math.sin(ecl * _RAD) + ze * math.cos(ecl * _RAD)
    ra = _rev(math.degrees(math.atan2(yq, xq)))
    dec = math.degrees(math.atan2(zq, math.hypot(xq, yq)))
    return ra, dec, Ls


def _altitude(dt: datetime, lat: float, lon: float) -> float:
    ra, dec, Ls = _moon_radec(dt)
    ut = dt.hour + dt.minute / 60 + dt.second / 3600
    gmst0 = (Ls + 180.0) / 15.0
    lst = _rev((gmst0 + ut + lon / 15.0) * 15.0)  # градусы
    ha = (lst - ra + 180) % 360 - 180
    sin_alt = (
        math.sin(lat * _RAD) * math.sin(dec * _RAD)
        + math.cos(lat * _RAD) * math.cos(dec * _RAD) * math.cos(ha * _RAD)
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


@dataclass
class Forecast:
    score: int              # 1..10
    label: str
    windows: list[dict] = field(default_factory=list)  # {start,end,kind,title}

    def as_text(self) -> str:
        best = ", ".join(f"{w['start']}–{w['end']}" for w in self.windows[:3])
        line = f"🎣 Прогноз клёва: {self.score}/10 ({self.label})"
        return line + (f"\nЛучшие часы: {best}" if best else "")


def _moon_age(dt: datetime) -> float:
    # Возраст Луны в сутках через известное новолуние 2000-01-06.
    known = 2451550.1
    jd = dt.timestamp() / 86400.0 + 2440587.5
    return (jd - known) % _SYN


def _fmt(dt_local: datetime) -> str:
    return dt_local.strftime("%H:%M")


def forecast_for(lat: float, lon: float, on: date | None = None) -> Forecast:
    on = on or datetime.now(timezone.utc).date()
    offset = lon / 15.0  # приблизительное местное солнечное время по долготе

    # Локальная полночь в UTC
    midnight_utc = datetime(on.year, on.month, on.day, tzinfo=timezone.utc) - timedelta(
        hours=offset
    )
    step = timedelta(minutes=10)
    samples = []  # (utc_dt, altitude)
    t = midnight_utc
    for _ in range(24 * 6 + 1):
        samples.append((t, _altitude(t, lat, lon)))
        t += step

    def to_local(u: datetime) -> datetime:
        return u + timedelta(hours=offset)

    def window(center_utc: datetime, half_min: int, kind: str, title: str) -> dict:
        c = to_local(center_utc)
        s = c - timedelta(minutes=half_min)
        e = c + timedelta(minutes=half_min)
        return {"start": _fmt(s), "end": _fmt(e), "kind": kind, "title": title,
                "_sort": c.hour * 60 + c.minute}

    windows: list[dict] = []

    # Кульминации: макс (верхняя) и мин (нижняя) высота -> большие периоды
    hi = max(samples, key=lambda s: s[1])
    lo = min(samples, key=lambda s: s[1])
    windows.append(window(hi[0], 60, "major", "Луна в зените"))
    windows.append(window(lo[0], 60, "major", "Луна в надире"))

    # Восход/заход Луны (пересечение высотой 0) -> малые периоды
    for (t0, a0), (t1, a1) in zip(samples, samples[1:]):
        if a0 == 0 or (a0 < 0 <= a1) or (a0 > 0 >= a1):
            frac = 0 if a1 == a0 else (0 - a0) / (a1 - a0)
            cross = t0 + step * frac
            kind_title = "Восход Луны" if a1 > a0 else "Заход Луны"
            windows.append(window(cross, 45, "minor", kind_title))

    windows.sort(key=lambda w: w["_sort"])
    for w in windows:
        w.pop("_sort", None)

    # Балл дня: максимум у новолуния и полнолуния, минимум в четвертях.
    p = _moon_age(midnight_utc + timedelta(hours=12)) / _SYN
    bestness = abs(math.cos(2 * math.pi * p))  # 1 у ново-/полнолуния, 0 в четвертях
    score = max(1, min(10, round(3 + 7 * bestness)))
    if score >= 8:
        label = "отличный"
    elif score >= 6:
        label = "хороший"
    elif score >= 4:
        label = "средний"
    else:
        label = "слабый"

    return Forecast(score=score, label=label, windows=windows)
