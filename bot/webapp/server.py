"""Веб-сервер мини-приложения (Telegram WebApp).

Отдаёт статическую карту (Leaflet + OpenStreetMap — бесплатные тайлы) и JSON с
отчётами текущего пользователя. Личность пользователя берётся из подписанного
Telegram initData и проверяется по HMAC — доверять данным из query напрямую
нельзя.

Мини-приложение — правильный фундамент для «дневника на карте» и будущих слоёв
(агрегат по зоне, фильтр по видам рыб). На MVP карта показывает только СВОИ
точки — это работает и без чужих данных (холодный старт решён).
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from bot.db import Database

_STATIC = Path(__file__).resolve().parent / "static"


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверяет подпись Telegram WebApp initData. Возвращает поля или None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(
        secret_key, check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None
    return pairs


def _extract_user_id(fields: dict) -> int | None:
    import json

    try:
        user = json.loads(fields.get("user", "{}"))
        return int(user["id"])
    except (ValueError, KeyError, TypeError):
        return None


def build_app(db: Database, bot_token: str) -> web.Application:
    app = web.Application()

    async def index(_request: web.Request) -> web.Response:
        return web.FileResponse(_STATIC / "index.html")

    async def api_reports(request: web.Request) -> web.Response:
        init_data = request.query.get("initData", "")
        fields = validate_init_data(init_data, bot_token)
        if fields is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        user_id = _extract_user_id(fields)
        if user_id is None:
            return web.json_response({"error": "no user"}, status=400)

        reports = await db.list_user_reports(user_id, limit=200)
        payload = [
            {
                "lat": r.zone_lat,
                "lon": r.zone_lon,
                "caught": r.caught,
                "species": r.species,
                "bait": r.bait,
                "date": r.report_date,
                "weather": r.weather_text,
                "moon": r.moon_text,
            }
            for r in reports
        ]
        return web.json_response({"reports": payload})

    app.router.add_get("/", index)
    app.router.add_get("/api/reports", api_reports)
    app.router.add_static("/static/", _STATIC)
    return app
