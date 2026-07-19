"""Слой данных мини-приложения (SQLite через aiosqlite).

Модель под утверждённый отчёт: одна поездка (report) содержит несколько
позиций (item) — по одной на вид рыбы, у каждой количество, общий вес, вес
самой крупной особи и список наживок. Личный рекорд по виду считается как
максимум по «самой крупной особи» из всех позиций пользователя.

Это и есть наша база уловов: её можно выгружать, агрегировать и использовать
(инсайты, прогнозы) — при этом наружу отдаётся только зона сетки, не точный пин.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS w_users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS w_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    zone_id     TEXT,
    lat         REAL,
    lon         REAL,
    report_date TEXT NOT NULL,
    weather     TEXT,
    moon        TEXT,
    bite_score  REAL,
    note        TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS w_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    species     TEXT NOT NULL,
    qty         INTEGER NOT NULL DEFAULT 1,
    total_kg    REAL,
    biggest_kg  REAL,
    baits       TEXT,
    report_date TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_user ON w_items(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_user ON w_reports(user_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Item:
    species: str
    qty: int
    total_kg: float | None
    biggest_kg: float | None
    baits: list[str]


class Store:
    def __init__(self, path: str) -> None:
        self._path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def ensure_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO w_users(user_id, username, first_name, created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
                (user_id, username, first_name, _now()),
            )
            await db.commit()

    async def _best_before(self, db: aiosqlite.Connection, user_id: int, species: str) -> float:
        cur = await db.execute(
            "SELECT COALESCE(MAX(biggest_kg),0) FROM w_items WHERE user_id=? AND species=?",
            (user_id, species),
        )
        (v,) = await cur.fetchone()
        return float(v or 0)

    async def add_report(
        self, user_id: int, items: list[Item], zone_id: str | None,
        lat: float | None, lon: float | None, weather: str | None,
        moon: str | None, note: str | None, report_date: str,
        bite_score: float | None = None,
    ) -> dict:
        """Сохраняет поездку и позиции. Возвращает id и список новых рекордов."""
        new_records: list[dict] = []
        async with aiosqlite.connect(self._path) as db:
            # какие позиции бьют прежний рекорд по виду
            for it in items:
                if it.biggest_kg and it.biggest_kg > 0:
                    prev = await self._best_before(db, user_id, it.species)
                    if it.biggest_kg > prev:
                        new_records.append(
                            {"species": it.species, "kg": it.biggest_kg, "prev": prev}
                        )
            cur = await db.execute(
                "INSERT INTO w_reports(user_id, zone_id, lat, lon, report_date, weather, moon, bite_score, note, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (user_id, zone_id, lat, lon, report_date, weather, moon, bite_score, note, _now()),
            )
            report_id = cur.lastrowid
            for it in items:
                await db.execute(
                    "INSERT INTO w_items(report_id, user_id, species, qty, total_kg, biggest_kg, baits, report_date, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (report_id, user_id, it.species, it.qty, it.total_kg,
                     it.biggest_kg, ", ".join(it.baits), report_date, _now()),
                )
            await db.commit()
        return {"report_id": report_id, "new_records": new_records}

    async def user_summary(self, user_id: int) -> dict:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                "SELECT COALESCE(SUM(qty),0), COALESCE(SUM(COALESCE(total_kg, biggest_kg, 0)),0) "
                "FROM w_items WHERE user_id=?",
                (user_id,),
            )
            fish, kg = await cur.fetchone()
            cur = await db.execute(
                "SELECT COUNT(*) FROM w_reports WHERE user_id=?", (user_id,)
            )
            (trips,) = await cur.fetchone()
        return {"fish": int(fish or 0), "kg": round(float(kg or 0), 1), "trips": int(trips or 0)}

    async def user_records(self, user_id: int) -> list[dict]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT species, MAX(biggest_kg) best, MAX(report_date) at_date "
                "FROM w_items WHERE user_id=? AND biggest_kg > 0 "
                "GROUP BY species ORDER BY best DESC",
                (user_id,),
            )
            rows = await cur.fetchall()
        return [{"species": r["species"], "kg": round(r["best"], 2), "date": r["at_date"]} for r in rows]

    async def diary(self, user_id: int, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT r.id, r.report_date, r.weather, r.moon, "
                "GROUP_CONCAT(i.species || ' ×' || i.qty, ', ') species_list, "
                "COALESCE(SUM(i.qty),0) fish, COALESCE(SUM(COALESCE(i.total_kg,i.biggest_kg,0)),0) kg "
                "FROM w_reports r LEFT JOIN w_items i ON i.report_id=r.id "
                "WHERE r.user_id=? GROUP BY r.id ORDER BY r.id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def feed(self, limit: int = 30) -> list[dict]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT r.id, r.user_id, r.report_date, r.weather, r.moon, r.created_at, "
                "u.username, u.first_name, "
                "GROUP_CONCAT(i.species || ' ×' || i.qty, ', ') species_list, "
                "COALESCE(SUM(i.qty),0) fish, COALESCE(SUM(COALESCE(i.total_kg,i.biggest_kg,0)),0) kg, "
                "MAX(i.biggest_kg) biggest, "
                "GROUP_CONCAT(DISTINCT i.baits) baits "
                "FROM w_reports r JOIN w_users u ON u.user_id=r.user_id "
                "LEFT JOIN w_items i ON i.report_id=r.id "
                "GROUP BY r.id ORDER BY r.id DESC LIMIT ?",
                (limit,),
            )
            rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["kg"] = round(float(d["kg"] or 0), 1)
            d["name"] = d.get("first_name") or d.get("username") or "Рыбак"
            out.append(d)
        return out

    async def rank(self, user_id: int, limit: int = 20) -> dict:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT u.user_id, u.username, u.first_name, "
                "COALESCE(SUM(i.qty),0) fish, "
                "COALESCE(SUM(COALESCE(i.total_kg,i.biggest_kg,0)),0) kg "
                "FROM w_users u LEFT JOIN w_items i ON i.user_id=u.user_id "
                "GROUP BY u.user_id ORDER BY kg DESC",
            )
            rows = await cur.fetchall()
        board = []
        me = None
        for pos, r in enumerate(rows, start=1):
            entry = {
                "pos": pos,
                "user_id": r["user_id"],
                "name": r["first_name"] or r["username"] or "Рыбак",
                "fish": int(r["fish"] or 0),
                "kg": round(float(r["kg"] or 0), 1),
            }
            if r["user_id"] == user_id:
                me = entry
            if pos <= limit:
                board.append(entry)
        return {"board": board, "me": me}
