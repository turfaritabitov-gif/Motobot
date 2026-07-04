import os

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import Config
from bot.db import Database
from bot.keyboards import ik, main_menu
from bot.texts import ABOUT, DISCLAIMER

router = Router()


async def is_admin_user(db: Database, user_id: int) -> bool:
    ids_raw = await db.get_setting("admin_chat_ids")
    admin_ids = {int(chunk) for chunk in ids_raw.replace(";", ",").split(",") if chunk.strip().lstrip("-").isdigit()}
    legacy_id = await db.get_setting("admin_chat_id")
    if legacy_id.lstrip("-").isdigit():
        admin_ids.add(int(legacy_id))
    if user_id in admin_ids:
        return True
    row = await db.fetchone("SELECT role FROM users WHERE telegram_id = ?", user_id)
    return bool(row and row["role"] == "admin")


async def send_main_menu(message: Message, db: Database, config: Config) -> None:
    is_admin = await is_admin_user(db, message.from_user.id)
    text = (
        "Привет! Это бот мотосообщества Казани.\n\n"
        "Здесь можно оставить заявку на мотопрогулку по городу или подать анкету райдера, "
        "если ты хочешь присоединиться к проекту.\n\n"
        "Выберите нужный раздел:"
    )
    if os.path.exists(config.welcome_photo_path):
        await message.answer_photo(FSInputFile(config.welcome_photo_path), caption=text, reply_markup=main_menu(is_admin))
    else:
        await message.answer(text, reply_markup=main_menu(is_admin))


@router.message(CommandStart())
async def start(message: Message, db: Database, config: Config) -> None:
    username = (message.from_user.username or "").lower()
    admin_username = config.admin_username.lower()
    role = "admin" if (admin_username and username == admin_username) or message.from_user.id in config.admin_chat_ids else None
    await db.upsert_user(message.from_user, role=role)
    if role == "admin":
        rows = await db.fetchall("SELECT telegram_id FROM users WHERE role='admin'")
        admin_ids = {row["telegram_id"] for row in rows}
        admin_ids.update(config.admin_chat_ids)
        await db.set_setting("admin_chat_ids", ",".join(str(admin_id) for admin_id in sorted(admin_ids)))
        if admin_username and username == admin_username:
            await db.set_setting("admin_chat_id", str(message.from_user.id))
    await send_main_menu(message, db, config)


@router.callback_query(F.data == "common:menu")
async def menu(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await callback.answer()
    await state.clear()
    await send_main_menu(callback.message, db, config)


@router.callback_query(F.data == "common:about")
async def about(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        ABOUT,
        reply_markup=ik([[("Хочу мотопрогулку", "client:start")], [("Назад", "common:menu"), ("Главное меню", "common:menu")]]),
    )


@router.callback_query(F.data == "common:disclaimer")
async def disclaimer(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        DISCLAIMER,
        reply_markup=ik([[("Понятно", "common:menu")], [("Назад", "common:menu"), ("Главное меню", "common:menu")]]),
    )
