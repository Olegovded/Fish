"""Слой данных на SQLite (через aiosqlite).

Единая база отчётов — фундамент из брифа: поверх неё живут и бот, и
мини-приложение, и будущая агрегированная статистика. При портировании на MAX
структура данных не меняется, меняется только слой мессенджера.

SQLite выбран осознанно: для MVP это ноль инфраструктурных затрат и ноль
стоимости на клиента. Схема совместима с Postgres — миграция на него делается
без изменения бизнес-логики, когда/если вырастет нагрузка.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    caught        INTEGER NOT NULL,           -- 1 = с уловом, 0 = без
    species       TEXT,                       -- вид рыбы (NULL если не поймал)
    bait          TEXT,                       -- наживка/снасть, что сработало
    comment       TEXT,
    photo_file_id TEXT,                       -- file_id фото в Telegram
    zone_id       TEXT NOT NULL,              -- ячейка сетки, НЕ точный пин
    zone_lat      REAL NOT NULL,              -- центр ячейки
    zone_lon      REAL NOT NULL,
    weather_text  TEXT,
    moon_text     TEXT,
    report_date   TEXT NOT NULL,              -- дата рыбалки (YYYY-MM-DD)
    created_at    TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_zone ON reports(zone_id);

-- Запоминаем последний выбор пользователя (вид/наживка), чтобы предлагать его
-- первым и экономить тапы (UX-принцип из брифа).
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id    INTEGER PRIMARY KEY,
    last_species TEXT,
    last_bait    TEXT
);
"""


@dataclass
class Report:
    id: int
    user_id: int
    caught: bool
    species: str | None
    bait: str | None
    comment: str | None
    photo_file_id: str | None
    zone_id: str
    zone_lat: float
    zone_lon: float
    weather_text: str | None
    moon_text: str | None
    report_date: str
    created_at: str


@dataclass
class ZoneStats:
    total: int
    with_catch: int
    top_species: list[tuple[str, int]]

    @property
    def catch_ratio(self) -> float:
        return (self.with_catch / self.total) if self.total else 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        self._path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def ensure_user(self, user_id: int, username: str | None) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO users(user_id, username, created_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                (user_id, username, _now_iso()),
            )
            await db.commit()

    async def add_report(self, **fields) -> int:
        cols = (
            "user_id", "caught", "species", "bait", "comment", "photo_file_id",
            "zone_id", "zone_lat", "zone_lon", "weather_text", "moon_text",
            "report_date", "created_at",
        )
        fields.setdefault("created_at", _now_iso())
        values = [fields.get(c) for c in cols]
        placeholders = ",".join("?" for _ in cols)
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                f"INSERT INTO reports ({','.join(cols)}) VALUES ({placeholders})",
                values,
            )
            await db.commit()
            return cur.lastrowid or 0

    async def list_user_reports(self, user_id: int, limit: int = 20) -> list[Report]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM reports WHERE user_id=? "
                "ORDER BY report_date DESC, id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cur.fetchall()
        return [_row_to_report(r) for r in rows]

    async def user_report_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM reports WHERE user_id=?", (user_id,)
            )
            (count,) = await cur.fetchone()
        return int(count)

    async def get_report(self, report_id: int) -> Report | None:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM reports WHERE id=?", (report_id,))
            row = await cur.fetchone()
        return _row_to_report(row) if row else None

    async def zone_stats(self, zone_id: str, days: int = 14) -> ZoneStats:
        """Сырая статистика по зоне за период — без алгоритма доверия (по брифу)."""
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT COUNT(*), COALESCE(SUM(caught),0) FROM reports "
                "WHERE zone_id=? AND report_date >= date('now', ?)",
                (zone_id, f"-{days} days"),
            )
            total, with_catch = await cur.fetchone()
            cur = await db.execute(
                "SELECT species, COUNT(*) c FROM reports "
                "WHERE zone_id=? AND caught=1 AND species IS NOT NULL "
                "AND report_date >= date('now', ?) "
                "GROUP BY species ORDER BY c DESC LIMIT 3",
                (zone_id, f"-{days} days"),
            )
            top = [(row[0], int(row[1])) for row in await cur.fetchall()]
        return ZoneStats(total=int(total), with_catch=int(with_catch), top_species=top)

    async def get_prefs(self, user_id: int) -> tuple[str | None, str | None]:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT last_species, last_bait FROM user_prefs WHERE user_id=?",
                (user_id,),
            )
            row = await cur.fetchone()
        return (row[0], row[1]) if row else (None, None)

    async def set_prefs(
        self, user_id: int, species: str | None, bait: str | None
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO user_prefs(user_id, last_species, last_bait) "
                "VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "last_species=COALESCE(excluded.last_species, user_prefs.last_species),"
                "last_bait=COALESCE(excluded.last_bait, user_prefs.last_bait)",
                (user_id, species, bait),
            )
            await db.commit()


def _row_to_report(r: aiosqlite.Row) -> Report:
    return Report(
        id=r["id"],
        user_id=r["user_id"],
        caught=bool(r["caught"]),
        species=r["species"],
        bait=r["bait"],
        comment=r["comment"],
        photo_file_id=r["photo_file_id"],
        zone_id=r["zone_id"],
        zone_lat=r["zone_lat"],
        zone_lon=r["zone_lon"],
        weather_text=r["weather_text"],
        moon_text=r["moon_text"],
        report_date=r["report_date"],
        created_at=r["created_at"],
    )
