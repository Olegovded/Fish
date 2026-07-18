"""Состояния FSM для пошагового отчёта."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ReportFlow(StatesGroup):
    caught = State()
    species = State()
    species_custom = State()
    bait = State()
    bait_custom = State()
    comment = State()
    photo = State()
    location = State()


class StatsFlow(StatesGroup):
    location = State()
