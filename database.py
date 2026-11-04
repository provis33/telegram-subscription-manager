from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_CANCELLED = "cancelled"


@dataclass
class Subscription:
    id: int
    user_id: int
    title: str
    next_charge_date: date
    amount: float
    currency: str
    status: str


class Database:
    def __init__(self, db_path: str | Path = "data/bot.db") -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                next_charge_date TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )
        await self._conn.commit()
        logger.info("SQLite ready: %s", self.db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def ensure_user(self, tg_id: int) -> int:
        cursor = await self.conn.execute(
            "SELECT id FROM users WHERE tg_id = ?",
            (tg_id,),
        )
        row = await cursor.fetchone()
        if row:
            return int(row["id"])
        cursor = await self.conn.execute(
            "INSERT INTO users (tg_id) VALUES (?)",
            (tg_id,),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def add_subscription(
        self,
        user_id: int,
        title: str,
        next_charge_date: date,
        amount: float,
        currency: str,
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO subscriptions
                (user_id, title, next_charge_date, amount, currency, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, title, next_charge_date.isoformat(), amount, currency.upper(), STATUS_ACTIVE),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    def _row_to_sub(self, row: aiosqlite.Row) -> Subscription:
        return Subscription(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            next_charge_date=date.fromisoformat(row["next_charge_date"]),
            amount=float(row["amount"]),
            currency=row["currency"],
            status=row["status"],
        )

    async def list_active(self, user_id: int) -> list[Subscription]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE user_id = ? AND status = ?
            ORDER BY next_charge_date ASC
            """,
            (user_id, STATUS_ACTIVE),
        )
        rows = await cursor.fetchall()
        return [self._row_to_sub(r) for r in rows]

    async def get_subscription(self, sub_id: int) -> Subscription | None:
        cursor = await self.conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?",
            (sub_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_sub(row) if row else None

    async def cancel_subscription(self, sub_id: int, user_id: int | None = None) -> bool:
        if user_id is None:
            cursor = await self.conn.execute(
                "UPDATE subscriptions SET status = ? WHERE id = ? AND status = ?",
                (STATUS_CANCELLED, sub_id, STATUS_ACTIVE),
            )
        else:
            cursor = await self.conn.execute(
                """
                UPDATE subscriptions SET status = ?
                WHERE id = ? AND user_id = ? AND status = ?
                """,
                (STATUS_CANCELLED, sub_id, user_id, STATUS_ACTIVE),
            )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def shift_charge_date(self, sub_id: int, new_date: date) -> None:
        await self.conn.execute(
            "UPDATE subscriptions SET next_charge_date = ? WHERE id = ?",
            (new_date.isoformat(), sub_id),
        )
        await self.conn.commit()

    async def mark_paid(self, sub_id: int) -> date | None:
        """Сдвиг next_charge_date на +1 месяц / shift +1 month."""
        sub = await self.get_subscription(sub_id)
        if sub is None or sub.status != STATUS_ACTIVE:
            return None
        new_date = _add_one_month(sub.next_charge_date)
        await self.shift_charge_date(sub_id, new_date)
        return new_date

    async def postpone(self, sub_id: int, days: int = 3) -> date | None:
        sub = await self.get_subscription(sub_id)
        if sub is None or sub.status != STATUS_ACTIVE:
            return None
        new_date = sub.next_charge_date + timedelta(days=days)
        await self.shift_charge_date(sub_id, new_date)
        return new_date

    async def due_for_reminder(self, target_date: date) -> list[tuple[int, Subscription]]:
        """Активные подписки с next_charge_date == target_date + tg_id владельца."""
        cursor = await self.conn.execute(
            """
            SELECT s.*, u.tg_id
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            WHERE s.status = ? AND s.next_charge_date = ?
            """,
            (STATUS_ACTIVE, target_date.isoformat()),
        )
        rows = await cursor.fetchall()
        result: list[tuple[int, Subscription]] = []
        for row in rows:
            result.append((int(row["tg_id"]), self._row_to_sub(row)))
        return result


def _add_one_month(d: date) -> date:
    year, month = d.year, d.month + 1
    if month > 12:
        year += 1
        month = 1
    # последний день месяца, если день «не влезает» / clamp day
    for day in range(d.day, 0, -1):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, 1)
