"""Пошаговый отчёт — ядро MVP.

Сценарий (минимум тапов): поймал/не поймал → вид → наживка → комментарий →
фото → локация. Погода и фаза луны подтягиваются автоматически на шаге локации.
Свободный текст — только там, где выбран пункт «Своё» или комментарий.
"""
from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database
from bot.handlers.states import ReportFlow
from bot.services import keyboards as kb
from bot.services.catalog import BAITS, SPECIES
from bot.services.geo import snap_to_zone
from bot.services.moon import moon_for
from bot.services.share import build_share_card
from bot.services.weather import fetch_weather

router = Router(name="report")


@router.message(F.text == "🎣 Новый отчёт")
@router.message(F.text.startswith("/report"))
async def start_report(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ReportFlow.caught)
    await message.answer(
        "Как порыбачили? 🎣", reply_markup=kb.caught_kb()
    )


@router.callback_query(ReportFlow.caught, F.data.startswith("caught:"))
async def on_caught(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    caught = call.data.split(":", 1)[1] == "1"
    await state.update_data(caught=caught)
    await call.answer()

    if not caught:
        # Без улова — вид и наживку не спрашиваем, сразу к комментарию.
        await state.update_data(species=None, bait=None)
        await _ask_comment(call.message, state)
        return

    last_species, _ = await db.get_prefs(call.from_user.id)
    markup, ordered = kb.species_kb(last_species)
    await state.update_data(species_order=ordered)
    await state.set_state(ReportFlow.species)
    await call.message.edit_text("Какая рыба? 🐠", reply_markup=markup)


@router.callback_query(ReportFlow.species, F.data.startswith("sp:"))
async def on_species(call: CallbackQuery, state: FSMContext) -> None:
    token = call.data.split(":", 1)[1]
    await call.answer()
    if token == "own":
        await state.set_state(ReportFlow.species_custom)
        await call.message.edit_text("Напишите вид рыбы:")
        return
    data = await state.get_data()
    ordered = data.get("species_order", SPECIES)
    species = ordered[int(token)]
    await state.update_data(species=species)
    await _ask_bait(call, state, species)


@router.message(ReportFlow.species_custom, F.text)
async def on_species_custom(message: Message, state: FSMContext) -> None:
    await state.update_data(species=message.text.strip()[:64])
    await _ask_bait_msg(message, state)


@router.callback_query(ReportFlow.bait, F.data.startswith("ba:"))
async def on_bait(call: CallbackQuery, state: FSMContext) -> None:
    token = call.data.split(":", 1)[1]
    await call.answer()
    if token == "own":
        await state.set_state(ReportFlow.bait_custom)
        await call.message.edit_text("Напишите наживку/снасть:")
        return
    data = await state.get_data()
    ordered = data.get("bait_order", BAITS)
    bait = ordered[int(token)]
    await state.update_data(bait=bait)
    await _ask_comment(call.message, state)


@router.message(ReportFlow.bait_custom, F.text)
async def on_bait_custom(message: Message, state: FSMContext) -> None:
    await state.update_data(bait=message.text.strip()[:64])
    await _ask_comment(message, state)


@router.callback_query(ReportFlow.comment, F.data == "skip:comment")
async def skip_comment(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(comment=None)
    await _ask_photo(call.message, state)


@router.message(ReportFlow.comment, F.text)
async def on_comment(message: Message, state: FSMContext) -> None:
    await state.update_data(comment=message.text.strip()[:500])
    await _ask_photo(message, state)


@router.callback_query(ReportFlow.photo, F.data == "skip:photo")
async def skip_photo(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(photo_file_id=None)
    await _ask_location(call.message, state)


@router.message(ReportFlow.photo, F.photo)
async def on_photo(message: Message, state: FSMContext) -> None:
    # Берём самое крупное превью.
    file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=file_id)
    await _ask_location(message, state)


@router.message(ReportFlow.location, F.location)
async def on_location(
    message: Message, state: FSMContext, db: Database, config: Config
) -> None:
    loc = message.location
    zone = snap_to_zone(loc.latitude, loc.longitude, config.grid_size_m)

    today = date.today()
    weather = await fetch_weather(zone.lat, zone.lon, today)
    moon = moon_for(today)
    moon_text = f"{moon.emoji} {moon.phase_name} ({int(moon.illumination * 100)}%)"

    data = await state.get_data()
    report_id = await db.add_report(
        user_id=message.from_user.id,
        caught=1 if data.get("caught") else 0,
        species=data.get("species"),
        bait=data.get("bait"),
        comment=data.get("comment"),
        photo_file_id=data.get("photo_file_id"),
        zone_id=zone.zone_id,
        zone_lat=zone.lat,
        zone_lon=zone.lon,
        weather_text=weather.as_text(),
        moon_text=moon_text,
        report_date=today.isoformat(),
    )
    await db.set_prefs(message.from_user.id, data.get("species"), data.get("bait"))
    await state.clear()

    stats = await db.zone_stats(zone.zone_id)
    summary = _build_summary(data, zone, weather.as_text(), moon_text, stats)
    await message.answer(
        summary,
        reply_markup=kb.main_menu(config.webapp_url or None),
    )

    report = await db.get_report(report_id)
    if report:
        card = build_share_card(report, config.bot_username)
        await message.answer(
            "Готовая карточка для друзей 👇 (перешлите в чат)\n\n" + card,
            disable_web_page_preview=False,
        )


# ---- вспомогательные шаги -------------------------------------------------


async def _ask_bait(call: CallbackQuery, state: FSMContext, _species: str) -> None:
    markup, ordered = kb.bait_kb(None)
    await state.update_data(bait_order=ordered)
    await state.set_state(ReportFlow.bait)
    await call.message.edit_text("Что сработало? 🪝", reply_markup=markup)


async def _ask_bait_msg(message: Message, state: FSMContext) -> None:
    markup, ordered = kb.bait_kb(None)
    await state.update_data(bait_order=ordered)
    await state.set_state(ReportFlow.bait)
    await message.answer("Что сработало? 🪝", reply_markup=markup)


async def _ask_comment(message: Message, state: FSMContext) -> None:
    await state.set_state(ReportFlow.comment)
    await message.answer(
        "Комментарий? (или пропустите)",
        reply_markup=kb.skip_kb("comment"),
    )


async def _ask_photo(message: Message, state: FSMContext) -> None:
    await state.set_state(ReportFlow.photo)
    await message.answer(
        "Фото улова? (или пропустите)",
        reply_markup=kb.skip_kb("photo"),
    )


async def _ask_location(message: Message, state: FSMContext) -> None:
    await state.set_state(ReportFlow.location)
    await message.answer(
        "Последний шаг — где рыбачили? Локация округлится до зоны ~1 км, "
        "точную точку бот не сохраняет. 📍",
        reply_markup=kb.location_kb(),
    )


def _build_summary(data, zone, weather_text, moon_text, stats) -> str:
    head = "✅ Отчёт сохранён!" if data.get("caught") else "📝 Отчёт сохранён (без улова)"
    lines = [head, ""]
    if data.get("caught") and data.get("species"):
        lines.append(f"🐠 {data['species']}")
    if data.get("bait"):
        lines.append(f"🪝 {data['bait']}")
    lines.append(f"📍 Зона {zone.label}")
    lines.append(f"🌤 {weather_text}")
    lines.append(f"🌙 {moon_text}")
    lines.append("")
    if stats.total:
        pct = int(stats.catch_ratio * 100)
        lines.append(
            f"📊 В этой зоне за 2 недели: {stats.total} отчётов, "
            f"{pct}% с уловом."
        )
        if stats.top_species:
            top = ", ".join(f"{s} ({c})" for s, c in stats.top_species)
            lines.append(f"🏆 Чаще ловят: {top}")
    else:
        lines.append("📊 По этой зоне пока нет других отчётов — вы первый!")
    return "\n".join(lines)
