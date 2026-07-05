import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot

from bot.db import Database, now
from bot.keyboards import ik

MOSCOW = ZoneInfo("Europe/Moscow")

SLOT_TIMES = {
    "Утро - 06:00-12:00": ((6, 0), (12, 0), 0),
    "День - 12:00-18:00": ((12, 0), (18, 0), 0),
    "Вечер - 18:00-00:00": ((18, 0), (0, 0), 1),
    "Ночь - 00:00-06:00": ((0, 0), (6, 0), 0),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def trip_datetimes(date_text: str, time_slot: str) -> tuple[datetime, datetime]:
    date_value = datetime.strptime(date_text, "%d.%m.%Y").date()
    start_parts, end_parts, end_day_offset = SLOT_TIMES.get(time_slot, SLOT_TIMES["День - 12:00-18:00"])
    start = datetime(date_value.year, date_value.month, date_value.day, *start_parts, tzinfo=MOSCOW)
    end_date = date_value + timedelta(days=end_day_offset)
    end = datetime(end_date.year, end_date.month, end_date.day, *end_parts, tzinfo=MOSCOW)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


async def schedule_trip_notifications(db: Database, request_id: int) -> None:
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=?", request_id)
    if not req or not req["assigned_rider_id"]:
        return
    rider = await db.fetchone("SELECT telegram_id FROM riders WHERE id=?", req["assigned_rider_id"])
    if not rider or not rider["telegram_id"]:
        return
    start_at, end_at = trip_datetimes(req["date"], req["time_slot"])
    tasks = [
        ("client", req["telegram_id"], "reminder_2h", start_at - timedelta(hours=2)),
        ("rider", rider["telegram_id"], "reminder_2h", start_at - timedelta(hours=2)),
        ("client", req["telegram_id"], "reminder_30m", start_at - timedelta(minutes=30)),
        ("rider", rider["telegram_id"], "reminder_30m", start_at - timedelta(minutes=30)),
        ("client", req["telegram_id"], "client_feedback", end_at + timedelta(hours=1)),
        ("rider", rider["telegram_id"], "rider_feedback", end_at + timedelta(hours=1)),
    ]
    for target_role, target_id, kind, due_at in tasks:
        await db.execute(
            """
            INSERT OR IGNORE INTO scheduled_notifications(request_id, target_role, target_telegram_id, kind, due_at, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            request_id,
            target_role,
            target_id,
            kind,
            due_at.isoformat(timespec="seconds"),
            now(),
        )
    await db.commit()


async def scheduler_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            rows = await db.fetchall(
                "SELECT * FROM scheduled_notifications WHERE sent_at IS NULL AND due_at<=? ORDER BY due_at LIMIT 20",
                utc_now(),
            )
            for row in rows:
                await send_notification(bot, db, row)
                await db.execute("UPDATE scheduled_notifications SET sent_at=? WHERE id=?", now(), row["id"])
                await db.commit()
        except Exception:
            pass
        await asyncio.sleep(60)


async def send_notification(bot: Bot, db: Database, row) -> None:
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=?", row["request_id"])
    if not req or req["status"] != "trip_confirmed":
        return
    if row["kind"].startswith("reminder"):
        when = "за 2 часа" if row["kind"] == "reminder_2h" else "за 30 минут"
        await bot.send_message(
            row["target_telegram_id"],
            f"Напоминание {when}: мотопрогулка №{req['id']} запланирована на {req['date']}, {req['time_slot']}.",
        )
        return
    if row["kind"] == "client_feedback":
        await bot.send_message(
            row["target_telegram_id"],
            "Состоялась ли поездка?",
            reply_markup=ik([[("Да", f"trip:client:yes:{req['id']}"), ("Нет", f"trip:client:no:{req['id']}")]]),
        )
        return
    if row["kind"] == "rider_feedback":
        await bot.send_message(
            row["target_telegram_id"],
            "Состоялась ли поездка?",
            reply_markup=ik([[("Да", f"trip:rider:yes:{req['id']}"), ("Нет", f"trip:rider:no:{req['id']}")]]),
        )
