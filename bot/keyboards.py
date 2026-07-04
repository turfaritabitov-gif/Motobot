from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove


def ik(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [("Хочу мотопрогулку", "client:start"), ("Я райдер", "rider:start")],
        [("О проекте", "common:about"), ("Отказ от ответственности", "common:disclaimer")],
    ]
    if is_admin:
        rows.append([("Админ-панель", "admin:panel")])
    return ik(rows)


def nav(back: str | None = None, menu: bool = True) -> InlineKeyboardMarkup:
    row = []
    if back:
        row.append(("Назад", back))
    if menu:
        row.append(("Главное меню", "common:menu"))
    return ik([row] if row else [[("Главное меню", "common:menu")]])


def yes_no(prefix: str) -> InlineKeyboardMarkup:
    return ik([[("Да", f"{prefix}:yes"), ("Нет", f"{prefix}:no")]])


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить мои координаты", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


remove_keyboard = ReplyKeyboardRemove()
