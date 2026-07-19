"""Слой данных мини-приложения. Работает на двух движках:

- SQLite (по умолчанию, локально) — файл на диске;
- PostgreSQL (когда задан DATABASE_URL, напр. Supabase) — постоянная база,
  данные не теряются между перезапусками/передеплоями.

Движок выбирается по строке подключения: postgres:// -> Postgres, иначе SQLite.
SQL написан в нейтральном виде (без диалектных функций), фильтр по датам и
склейка списков делаются на стороне Python — поэтому один код работает на обоих.

Это и есть наша база уловов: её можно выгружать, агрегировать и использовать.
Наружу отдаётся только зона сетки, не точный пин.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import aiosqlite


def _is_pg(dsn: str) -> bool:
    return dsn.startswith("postgres://") or dsn.startswith("postgresql://")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cutoff(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS w_users (
    user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS w_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, zone_id TEXT,
    lat REAL, lon REAL, report_date TEXT NOT NULL, weather TEXT, moon TEXT,
    bite_score REAL, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS w_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    species TEXT NOT NULL, qty INTEGER NOT NULL DEFAULT 1, total_kg REAL, biggest_kg REAL,
    baits TEXT, report_date TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_items_user ON w_items(user_id);
CREATE INDEX IF NOT EXISTS idx_items_report ON w_items(report_id);
CREATE INDEX IF NOT EXISTS idx_reports_user ON w_reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_zone ON w_reports(zone_id);
"""

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS w_users (
    user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS w_reports (
    id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, zone_id TEXT,
    lat DOUBLE PRECISION, lon DOUBLE PRECISION, report_date TEXT NOT NULL, weather TEXT, moon TEXT,
    bite_score DOUBLE PRECISION, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS w_items (
    id BIGSERIAL PRIMARY KEY, report_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    species TEXT NOT NULL, qty INTEGER NOT NULL DEFAULT 1, total_kg DOUBLE PRECISION, biggest_kg DOUBLE PRECISION,
    baits TEXT, report_date TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_items_user ON w_items(user_id);
CREATE INDEX IF NOT EXISTS idx_items_report ON w_items(report_id);
CREATE INDEX IF NOT EXISTS idx_reports_user ON w_reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_zone ON w_reports(zone_id);
"""


@dataclass
class Item:
    species: str
    qty: int
    total_kg: float | None
    biggest_kg: float | None
    baits: list[str]


class Store:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pg = _is_pg(dsn)
        self._pool = None

    # ── подключение / схема ──────────────────────────────────
    async def init(self) -> None:
        if self._pg:
            import asyncpg
            local = ("localhost" in self._dsn) or ("127.0.0.1" in self._dsn)
            kwargs = {"statement_cache_size": 0}  # совместимость с пулером Supabase
            if not local and "sslmode" not in self._dsn:
                kwargs["ssl"] = "require"
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5, **kwargs)
            for stmt in filter(str.strip, _PG_SCHEMA.split(";")):
                await self._exec(stmt)
        else:
            async with aiosqlite.connect(self._dsn) as db:
                await db.executescript(_SQLITE_SCHEMA)
                await db.commit()

    def _conv(self, sql: str) -> str:
        if not self._pg:
            return sql
        out, i = [], 0
        for ch in sql:
            if ch == "?":
                i += 1
                out.append(f"${i}")
            else:
                out.append(ch)
        return "".join(out)

    async def _exec(self, sql: str, params: tuple = ()) -> None:
        if self._pg:
            async with self._pool.acquire() as c:
                await c.execute(self._conv(sql), *params)
        else:
            async with aiosqlite.connect(self._dsn) as db:
                await db.execute(sql, params)
                await db.commit()

    async def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        if self._pg:
            async with self._pool.acquire() as c:
                res = await c.fetch(self._conv(sql), *params)
                return [dict(r) for r in res]
        async with aiosqlite.connect(self._dsn) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            return [dict(r) for r in await cur.fetchall()]

    async def _row(self, sql: str, params: tuple = ()) -> dict | None:
        rows = await self._rows(sql, params)
        return rows[0] if rows else None

    async def _insert_id(self, sql: str, params: tuple) -> int:
        if self._pg:
            async with self._pool.acquire() as c:
                val = await c.fetchval(self._conv(sql) + " RETURNING id", *params)
                return int(val)
        async with aiosqlite.connect(self._dsn) as db:
            cur = await db.execute(sql, params)
            await db.commit()
            return int(cur.lastrowid or 0)

    # ── операции ─────────────────────────────────────────────
    async def ensure_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        await self._exec(
            "INSERT INTO w_users(user_id, username, first_name, created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
            (user_id, username, first_name, _now()),
        )

    async def add_report(
        self, user_id: int, items: list[Item], zone_id: str | None,
        lat: float | None, lon: float | None, weather: str | None,
        moon: str | None, note: str | None, report_date: str,
        bite_score: float | None = None,
    ) -> dict:
        new_records: list[dict] = []
        for it in items:
            if it.biggest_kg and it.biggest_kg > 0:
                r = await self._row(
                    "SELECT COALESCE(MAX(biggest_kg),0) AS v FROM w_items WHERE user_id=? AND species=?",
                    (user_id, it.species),
                )
                prev = float(r["v"] or 0)
                if it.biggest_kg > prev:
                    new_records.append({"species": it.species, "kg": it.biggest_kg, "prev": prev})

        report_id = await self._insert_id(
            "INSERT INTO w_reports(user_id, zone_id, lat, lon, report_date, weather, moon, bite_score, note, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user_id, zone_id, lat, lon, report_date, weather, moon, bite_score, note, _now()),
        )
        for it in items:
            await self._exec(
                "INSERT INTO w_items(report_id, user_id, species, qty, total_kg, biggest_kg, baits, report_date, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (report_id, user_id, it.species, it.qty, it.total_kg, it.biggest_kg,
                 ", ".join(it.baits), report_date, _now()),
            )
        return {"report_id": report_id, "new_records": new_records}

    async def user_summary(self, user_id: int) -> dict:
        r = await self._row(
            "SELECT COALESCE(SUM(qty),0) AS fish, COALESCE(SUM(COALESCE(total_kg, biggest_kg, 0)),0) AS kg "
            "FROM w_items WHERE user_id=?", (user_id,))
        t = await self._row("SELECT COUNT(*) AS c FROM w_reports WHERE user_id=?", (user_id,))
        return {"fish": int(r["fish"] or 0), "kg": round(float(r["kg"] or 0), 1), "trips": int(t["c"] or 0)}

    async def user_records(self, user_id: int) -> list[dict]:
        rows = await self._rows(
            "SELECT species, MAX(biggest_kg) AS best, MAX(report_date) AS at_date "
            "FROM w_items WHERE user_id=? AND biggest_kg > 0 GROUP BY species ORDER BY best DESC",
            (user_id,))
        return [{"species": r["species"], "kg": round(float(r["best"]), 2), "date": r["at_date"]} for r in rows]

    async def _items_of(self, report_id: int) -> list[dict]:
        return await self._rows(
            "SELECT species, qty, total_kg, biggest_kg, baits FROM w_items WHERE report_id=?",
            (report_id,))

    @staticmethod
    def _summarize(items: list[dict]) -> dict:
        species = ", ".join(f"{i['species']} ×{i['qty']}" for i in items)
        fish = sum(int(i["qty"] or 0) for i in items)
        kg = sum(float(i["total_kg"] or i["biggest_kg"] or 0) for i in items)
        biggest = max([float(i["biggest_kg"] or 0) for i in items], default=0.0)
        baits = ", ".join(dict.fromkeys(b.strip() for i in items for b in (i["baits"] or "").split(",") if b.strip()))
        return {"species_list": species, "fish": fish, "kg": round(kg, 1),
                "biggest": round(biggest, 2) if biggest else None, "baits": baits}

    async def diary(self, user_id: int, limit: int = 20) -> list[dict]:
        reports = await self._rows(
            "SELECT id, report_date, weather, moon FROM w_reports WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit))
        out = []
        for r in reports:
            r.update(self._summarize(await self._items_of(r["id"])))
            out.append(r)
        return out

    async def feed(self, limit: int = 30) -> list[dict]:
        reports = await self._rows(
            "SELECT r.id, r.user_id, r.report_date, r.weather, r.moon, u.username, u.first_name "
            "FROM w_reports r JOIN w_users u ON u.user_id=r.user_id ORDER BY r.id DESC LIMIT ?",
            (limit,))
        out = []
        for r in reports:
            r.update(self._summarize(await self._items_of(r["id"])))
            r["name"] = r.get("first_name") or r.get("username") or "Рыбак"
            out.append(r)
        return out

    async def zone_stats(self, zone_id: str, days: int = 30) -> dict:
        cutoff = _cutoff(days)
        tot = await self._row(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN EXISTS(SELECT 1 FROM w_items i WHERE i.report_id=r.id) THEN 1 ELSE 0 END),0) AS with_catch "
            "FROM w_reports r WHERE r.zone_id=? AND r.report_date >= ?",
            (zone_id, cutoff))
        total = int(tot["total"] or 0)
        with_catch = int(tot["with_catch"] or 0)
        top_rows = await self._rows(
            "SELECT i.species AS species, COALESCE(SUM(i.qty),0) AS c FROM w_items i "
            "JOIN w_reports r ON r.id=i.report_id WHERE r.zone_id=? AND r.report_date >= ? "
            "GROUP BY i.species ORDER BY c DESC LIMIT 3",
            (zone_id, cutoff))
        top = [{"species": t["species"], "count": int(t["c"])} for t in top_rows]
        pct = round(with_catch / total * 100) if total else 0
        return {"total": total, "catch_pct": pct, "top": top, "days": days}

    async def rank(self, user_id: int, limit: int = 20) -> dict:
        rows = await self._rows(
            "SELECT u.user_id AS user_id, u.username AS username, u.first_name AS first_name, "
            "COALESCE(SUM(i.qty),0) AS fish, COALESCE(SUM(COALESCE(i.total_kg,i.biggest_kg,0)),0) AS kg "
            "FROM w_users u LEFT JOIN w_items i ON i.user_id=u.user_id "
            "GROUP BY u.user_id, u.username, u.first_name ORDER BY kg DESC")
        board, me = [], None
        for pos, r in enumerate(rows, start=1):
            entry = {"pos": pos, "user_id": int(r["user_id"]),
                     "name": r["first_name"] or r["username"] or "Рыбак",
                     "fish": int(r["fish"] or 0), "kg": round(float(r["kg"] or 0), 1)}
            if int(r["user_id"]) == user_id:
                me = entry
            if pos <= limit:
                board.append(entry)
        return {"board": board, "me": me}
