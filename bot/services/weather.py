"""Погода через Open-Meteo.

Почему Open-Meteo: бесплатно, без API-ключа и без регистрации — идеально под
подход «если зайдёт — зайдёт, если нет — не жалко». Для отчёта «сейчас» берём
текущую погоду, для отчёта задним числом — архивный API.

Стоимость на клиента по погоде на MVP — фактически ноль (лимиты бесплатного
тарифа Open-Meteo с запасом покрывают тысячи отчётов в день).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone

import aiohttp

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_TIMEOUT = aiohttp.ClientTimeout(total=8)

# Коды погоды WMO → человеческое описание + эмодзи.
_WMO: dict[int, tuple[str, str]] = {
    0: ("Ясно", "☀️"),
    1: ("Преимущественно ясно", "🌤"),
    2: ("Переменная облачность", "⛅️"),
    3: ("Пасмурно", "☁️"),
    45: ("Туман", "🌫"),
    48: ("Изморозь", "🌫"),
    51: ("Морось", "🌦"),
    53: ("Морось", "🌦"),
    55: ("Сильная морось", "🌧"),
    61: ("Небольшой дождь", "🌦"),
    63: ("Дождь", "🌧"),
    65: ("Сильный дождь", "🌧"),
    71: ("Небольшой снег", "🌨"),
    73: ("Снег", "🌨"),
    75: ("Сильный снег", "❄️"),
    80: ("Ливень", "🌧"),
    81: ("Ливень", "🌧"),
    82: ("Сильный ливень", "⛈"),
    95: ("Гроза", "⛈"),
    96: ("Гроза с градом", "⛈"),
    99: ("Гроза с градом", "⛈"),
}


@dataclass(frozen=True)
class Weather:
    temp_c: float | None
    wind_ms: float | None
    pressure_hpa: float | None
    description: str
    emoji: str

    def as_text(self) -> str:
        parts = [f"{self.emoji} {self.description}"]
        if self.temp_c is not None:
            parts.append(f"{self.temp_c:+.0f}°C")
        if self.wind_ms is not None:
            parts.append(f"ветер {self.wind_ms:.0f} м/с")
        if self.pressure_hpa is not None:
            mmhg = self.pressure_hpa * 0.750062
            parts.append(f"{mmhg:.0f} мм рт.ст.")
        return ", ".join(parts)


def _describe(code: int | None) -> tuple[str, str]:
    if code is None:
        return ("Погода", "🌡")
    return _WMO.get(int(code), ("Погода", "🌡"))


async def fetch_weather(lat: float, lon: float, on: date | None = None) -> Weather:
    """Возвращает погоду для точки. Если дата в прошлом — берёт архив."""
    today = datetime.now(timezone.utc).date()
    is_past = on is not None and on < today
    try:
        if is_past:
            return await _fetch_archive(lat, lon, on)  # type: ignore[arg-type]
        return await _fetch_current(lat, lon)
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError):
        # Честность важнее «красивого ответа»: если данных нет — так и скажем.
        return Weather(None, None, None, "нет данных о погоде", "❔")


async def _fetch_current(lat: float, lon: float) -> Weather:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,wind_speed_10m,pressure_msl,weather_code",
        "wind_speed_unit": "ms",
        "timezone": "auto",
    }
    async with aiohttp.ClientSession(timeout=_TIMEOUT, trust_env=True) as session:
        async with session.get(_FORECAST_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
    cur = data["current"]
    desc, emoji = _describe(cur.get("weather_code"))
    return Weather(
        temp_c=cur.get("temperature_2m"),
        wind_ms=cur.get("wind_speed_10m"),
        pressure_hpa=cur.get("pressure_msl"),
        description=desc,
        emoji=emoji,
    )


async def _fetch_archive(lat: float, lon: float, on: date) -> Weather:
    iso = on.isoformat()
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": iso,
        "end_date": iso,
        "daily": "temperature_2m_max,wind_speed_10m_max,weather_code",
        "wind_speed_unit": "ms",
        "timezone": "auto",
    }
    async with aiohttp.ClientSession(timeout=_TIMEOUT, trust_env=True) as session:
        async with session.get(_ARCHIVE_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
    daily = data["daily"]
    code = daily["weather_code"][0] if daily.get("weather_code") else None
    desc, emoji = _describe(code)
    temp = daily["temperature_2m_max"][0] if daily.get("temperature_2m_max") else None
    wind = daily["wind_speed_10m_max"][0] if daily.get("wind_speed_10m_max") else None
    return Weather(
        temp_c=temp,
        wind_ms=wind,
        pressure_hpa=None,
        description=desc,
        emoji=emoji,
    )
