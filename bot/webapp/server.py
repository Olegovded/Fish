"""Веб-сервер мини-приложения: раздаёт HTML и обслуживает API.

Личность пользователя берётся из подписанного Telegram initData и проверяется
по HMAC на каждом запросе — доверять данным из запроса напрямую нельзя.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from bot.webapp.store import Item, Store

_STATIC = Path(__file__).resolve().parent / "static"


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Проверяет подпись Telegram WebApp initData. Возвращает поля или None."""
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None
    received = pairs.pop("hash", None)
    if not received:
        return None
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    return pairs


def _user_from(fields: dict) -> dict | None:
    try:
        u = json.loads(fields.get("user", "{}"))
        int(u["id"])
        return u
    except (ValueError, KeyError, TypeError):
        return None


def build_app(store: Store, bot_token: str, dev_mode: bool = False,
              bot_username: str = "") -> web.Application:
    app = web.Application()

    async def _auth(request: web.Request, init_data: str) -> dict | None:
        # dev_mode позволяет тестировать без Telegram (только при DEV=1).
        if dev_mode and init_data.startswith("dev:"):
            uid = int(init_data.split(":", 1)[1] or "1")
            return {"id": uid, "first_name": f"Dev{uid}", "username": f"dev{uid}"}
        fields = validate_init_data(init_data, bot_token)
        if fields is None:
            return None
        return _user_from(fields)

    async def index(_r: web.Request) -> web.Response:
        return web.FileResponse(_STATIC / "index.html")

    async def health(_r: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def api_me(request: web.Request) -> web.Response:
        user = await _auth(request, request.query.get("initData", ""))
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)
        uid = int(user["id"])
        await store.ensure_user(uid, user.get("username"), user.get("first_name"))
        return web.json_response({
            "user": {"name": user.get("first_name") or user.get("username") or "Рыбак"},
            "bot": bot_username,
            "summary": await store.user_summary(uid),
            "records": await store.user_records(uid),
            "diary": await store.diary(uid, 15),
        })

    async def api_feed(request: web.Request) -> web.Response:
        user = await _auth(request, request.query.get("initData", ""))
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"feed": await store.feed(30)})

    async def api_rank(request: web.Request) -> web.Response:
        user = await _auth(request, request.query.get("initData", ""))
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(await store.rank(int(user["id"]), 20))

    async def api_forecast(request: web.Request) -> web.Response:
        user = await _auth(request, request.query.get("initData", ""))
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)
        lat, lon = _num(request.query.get("lat")), _num(request.query.get("lon"))
        if lat is None or lon is None:
            return web.json_response({"error": "no location"}, status=400)
        from bot.services.moon import moon_for
        from bot.services.solunar import forecast_for
        f = forecast_for(lat, lon, date.today())
        m = moon_for(date.today())
        resp = {
            "score": f.score, "label": f.label, "windows": f.windows,
            "moon": f"{m.emoji} {m.phase_name}",
        }
        try:
            from bot.services.weather import fetch_weather
            w = await fetch_weather(lat, lon, date.today())
            resp["weather"] = w.as_text()
        except Exception:  # noqa: BLE001
            resp["weather"] = None
        return web.json_response(resp)

    async def api_report(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "bad json"}, status=400)
        user = await _auth(request, body.get("initData", ""))
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)
        uid = int(user["id"])
        await store.ensure_user(uid, user.get("username"), user.get("first_name"))

        items = []
        for raw in body.get("items", []):
            sp = (raw.get("species") or "").strip()[:64]
            if not sp:
                continue
            items.append(Item(
                species=sp,
                qty=max(1, int(raw.get("qty") or 1)),
                total_kg=_num(raw.get("total")),
                biggest_kg=_num(raw.get("biggest")),
                baits=[str(b)[:40] for b in (raw.get("baits") or [])][:8],
            ))

        lat, lon = _num(body.get("lat")), _num(body.get("lon"))
        zone_id, weather_txt, moon_txt, bite = None, None, None, None
        if lat is not None and lon is not None:
            try:
                from bot.services.geo import snap_to_zone
                from bot.services.moon import moon_for
                from bot.services.solunar import forecast_for
                from bot.services.weather import fetch_weather
                z = snap_to_zone(lat, lon)
                zone_id = z.zone_id
                # прогноз клёва считаем по фактической точке, храним зону
                bite = forecast_for(lat, lon, date.today()).score
                lat, lon = z.lat, z.lon  # храним центр зоны, не точный пин
                w = await fetch_weather(z.lat, z.lon, date.today())
                weather_txt = w.as_text()
                m = moon_for(date.today())
                moon_txt = f"{m.emoji} {m.phase_name}"
            except Exception:  # noqa: BLE001 — обогащение необязательно
                pass

        res = await store.add_report(
            user_id=uid, items=items, zone_id=zone_id, lat=lat, lon=lon,
            weather=weather_txt, moon=moon_txt, bite_score=bite,
            note=(body.get("note") or "").strip()[:500] or None,
            report_date=date.today().isoformat(),
        )
        return web.json_response({"ok": True, **res})

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/feed", api_feed)
    app.router.add_get("/api/rank", api_rank)
    app.router.add_get("/api/forecast", api_forecast)
    app.router.add_post("/api/report", api_report)
    app.router.add_static("/static/", _STATIC)
    return app


def _num(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
