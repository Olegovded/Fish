"""Сборка клавиатур. Логика раскладки отделена от хендлеров."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.services.catalog import BAITS, OWN, SPECIES


def main_menu(webapp_url: str | None = None) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.button(text="🎣 Новый отчёт")
    b.button(text="📖 Мой дневник")
    b.button(text="📊 Статистика зоны")
    if webapp_url:
        b.button(text="🗺 Карта", web_app=WebAppInfo(url=webapp_url))
    b.adjust(1, 2, 1)
    return b.as_markup(resize_keyboard=True)


def caught_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Поймал", callback_data="caught:1")
    b.button(text="❌ Не клевало", callback_data="caught:0")
    b.adjust(2)
    return b.as_markup()


def _choice_kb(
    items: list[str], prefix: str, last: str | None
) -> tuple[InlineKeyboardMarkup, list[str]]:
    b = InlineKeyboardBuilder()
    ordered = list(items)
    # Последний выбор — первым, чтобы повторный отчёт был в один тап.
    if last and last in ordered:
        ordered.remove(last)
        ordered.insert(0, last)
    for i, item in enumerate(ordered):
        label = f"⭐️ {item}" if item == last else item
        b.button(text=label, callback_data=f"{prefix}:{i}")
    b.button(text=OWN, callback_data=f"{prefix}:own")
    # Раскладка: по 3 в ряд, «Своё» отдельной строкой снизу.
    rows = [3] * ((len(ordered) + 2) // 3)
    b.adjust(*rows, 1)
    return b.as_markup(), ordered


def species_kb(last: str | None) -> tuple[InlineKeyboardMarkup, list[str]]:
    return _choice_kb(SPECIES, "sp", last)


def bait_kb(last: str | None) -> tuple[InlineKeyboardMarkup, list[str]]:
    return _choice_kb(BAITS, "ba", last)


def skip_kb(stage: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Пропустить", callback_data=f"skip:{stage}")
    return b.as_markup()


def location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
