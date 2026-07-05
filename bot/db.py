import os
from datetime import datetime
from typing import Any

import aiosqlite


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    phone TEXT,
    role TEXT NOT NULL DEFAULT 'client',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_blocked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS client_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    client_name TEXT NOT NULL,
    client_age INTEGER NOT NULL,
    client_height INTEGER NOT NULL,
    client_weight INTEGER NOT NULL,
    client_phone TEXT,
    client_username TEXT,
    ride_mode TEXT NOT NULL DEFAULT 'money',
    motorcycle_class TEXT NOT NULL,
    route_type TEXT NOT NULL,
    date TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    pickup_type TEXT NOT NULL,
    pickup_address TEXT,
    pickup_lat REAL,
    pickup_lng REAL,
    base_price INTEGER,
    pickup_markup_percent INTEGER,
    route_markup_percent INTEGER,
    final_price INTEGER,
    is_individual_price INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    assigned_rider_id INTEGER,
    admin_comment TEXT,
    consent_accepted INTEGER NOT NULL DEFAULT 1,
    consent_accepted_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS riders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    username TEXT,
    name TEXT NOT NULL,
    age INTEGER NOT NULL,
    seasons INTEGER NOT NULL,
    motorcycle_class TEXT NOT NULL,
    motorcycle_model TEXT NOT NULL,
    passenger_equipment TEXT NOT NULL,
    max_passenger_weight INTEGER NOT NULL,
    ride_for_money INTEGER NOT NULL DEFAULT 1,
    ride_by_rules INTEGER NOT NULL DEFAULT 0,
    can_pickup_client INTEGER NOT NULL DEFAULT 0,
    can_ride_night INTEGER NOT NULL DEFAULT 0,
    can_individual_route INTEGER NOT NULL DEFAULT 0,
    base_area TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    admin_comment TEXT,
    completed_trips INTEGER NOT NULL DEFAULT 0,
    rating_count INTEGER NOT NULL DEFAULT 0,
    rating_sum_total INTEGER NOT NULL DEFAULT 0,
    rating_sum_transport INTEGER NOT NULL DEFAULT 0,
    rating_sum_politeness INTEGER NOT NULL DEFAULT 0,
    rating_sum_driving INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rider_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rider_id INTEGER NOT NULL,
    telegram_file_id TEXT NOT NULL,
    file_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rider_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    rider_id INTEGER NOT NULL,
    response_status TEXT NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS request_rejected_riders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    rider_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(request_id, rider_id)
);

CREATE TABLE IF NOT EXISTS ride_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    rider_id INTEGER NOT NULL,
    client_telegram_id INTEGER NOT NULL,
    transport_score INTEGER NOT NULL,
    politeness_score INTEGER NOT NULL,
    driving_score INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trip_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    reporter_role TEXT NOT NULL,
    telegram_id INTEGER NOT NULL,
    did_happen INTEGER NOT NULL,
    payment_received INTEGER,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    target_role TEXT NOT NULL,
    target_telegram_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    due_at TEXT NOT NULL,
    sent_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(request_id, target_role, kind)
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER,
    telegram_payment_charge_id TEXT,
    provider_payment_charge_id TEXT,
    amount INTEGER,
    currency TEXT DEFAULT 'RUB',
    status TEXT NOT NULL DEFAULT 'not_required',
    payment_method TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_telegram_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    created_at TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "price_road": "2000",
    "price_classic_custom": "3000",
    "price_sport": "2500",
    "price_electric": "2000",
    "pickup_markup": "10",
    "route_small_markup": "0",
    "route_big_markup": "20",
    "route_rider_choice_markup": "20",
    "payment_enabled": "false",
    "meeting_point_lat": "55.791904",
    "meeting_point_lng": "49.112035",
    "meeting_point_address": "Точка сбора: 55.791904, 49.112035",
    "max_booking_days": "60",
}


def now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.ensure_columns()
        for key, value in DEFAULT_SETTINGS.items():
            await self.execute(
                "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES(?, ?, ?)",
                key,
                value,
                now(),
            )
        await self.conn.commit()

    async def ensure_columns(self) -> None:
        assert self.conn
        existing = {row["name"] for row in await self.fetchall("PRAGMA table_info(client_requests)")}
        if "ride_mode" not in existing:
            await self.execute("ALTER TABLE client_requests ADD COLUMN ride_mode TEXT NOT NULL DEFAULT 'money'")

        existing = {row["name"] for row in await self.fetchall("PRAGMA table_info(riders)")}
        if "ride_for_money" not in existing:
            await self.execute("ALTER TABLE riders ADD COLUMN ride_for_money INTEGER NOT NULL DEFAULT 1")
        if "ride_by_rules" not in existing:
            await self.execute("ALTER TABLE riders ADD COLUMN ride_by_rules INTEGER NOT NULL DEFAULT 0")
        for column in (
            "completed_trips",
            "rating_count",
            "rating_sum_total",
            "rating_sum_transport",
            "rating_sum_politeness",
            "rating_sum_driving",
        ):
            if column not in existing:
                await self.execute(f"ALTER TABLE riders ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def execute(self, sql: str, *params: Any) -> aiosqlite.Cursor:
        assert self.conn
        return await self.conn.execute(sql, params)

    async def commit(self) -> None:
        assert self.conn
        await self.conn.commit()

    async def fetchone(self, sql: str, *params: Any) -> aiosqlite.Row | None:
        cursor = await self.execute(sql, *params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, *params: Any) -> list[aiosqlite.Row]:
        cursor = await self.execute(sql, *params)
        return await cursor.fetchall()

    async def upsert_user(self, tg_user: Any, role: str | None = None, phone: str | None = None) -> None:
        existing = await self.fetchone("SELECT role FROM users WHERE telegram_id = ?", tg_user.id)
        final_role = role or (existing["role"] if existing else "client")
        await self.execute(
            """
            INSERT INTO users(telegram_id, username, first_name, last_name, phone, role, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                phone=COALESCE(excluded.phone, users.phone),
                role=excluded.role,
                updated_at=excluded.updated_at
            """,
            tg_user.id,
            tg_user.username,
            tg_user.first_name,
            tg_user.last_name,
            phone,
            final_role,
            now(),
            now(),
        )
        await self.commit()

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            key,
            value,
            now(),
        )
        await self.commit()

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self.fetchone("SELECT value FROM settings WHERE key = ?", key)
        return row["value"] if row else default

    async def add_admin_log(self, admin_id: int, action: str, entity_type: str | None = None, entity_id: int | None = None) -> None:
        await self.execute(
            "INSERT INTO admin_logs(admin_telegram_id, action, entity_type, entity_id, created_at) VALUES(?, ?, ?, ?, ?)",
            admin_id,
            action,
            entity_type,
            entity_id,
            now(),
        )
        await self.commit()
