from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import Database, now
from bot.handlers.common import is_admin_user
from bot.keyboards import ik, nav
from bot.states import AdminFlow

router = Router()

RIDE_MODES = {
    "money": "За деньги",
    "rules": "По правилам",
}


def rider_modes_text(row_or_data) -> str:
    def value(key: str):
        if hasattr(row_or_data, "keys") and key in row_or_data.keys():
            return row_or_data[key]
        return row_or_data.get(key)

    modes = []
    if value("ride_for_money"):
        modes.append("За деньги")
    if value("ride_by_rules"):
        modes.append("По правилу")
    return ", ".join(modes) or "-"


async def require_admin(event: Message | CallbackQuery, db: Database) -> bool:
    user = event.from_user
    ok = await is_admin_user(db, user.id)
    if not ok:
        if isinstance(event, CallbackQuery):
            await event.answer("Недоступно.", show_alert=True)
        else:
            await event.answer("Эта команда доступна только администратору.")
    return ok


def request_card(row) -> str:
    price = "индивидуально" if row["is_individual_price"] else f"{row['final_price']} руб."
    return (
        f"Заявка №{row['id']}\n"
        f"Клиент: {row['client_name']}, {row['client_age']} лет\n"
        f"Параметры: {row['client_height']} см / {row['client_weight']} кг\n"
        f"Формат катания: {RIDE_MODES.get(row['ride_mode'], 'За деньги')}\n"
        f"Класс: {row['motorcycle_class']}\n"
        f"Маршрут: {row['route_type']}\n"
        f"Дата/время: {row['date']}, {row['time_slot']}\n"
        f"Посадка: {row['pickup_address']}\n"
        f"Стоимость: {price}\n"
        f"Статус: {row['status']}"
    )


def rider_card(row) -> str:
    return (
        f"Райдер №{row['id']}: {row['name']}\n"
        f"Telegram: @{row['username'] or '-'} / ID {row['telegram_id'] or '-'}\n"
        f"Возраст: {row['age']}\n"
        f"Опыт: {row['seasons']} сезонов\n"
        f"Как возит: {rider_modes_text(row)}\n"
        f"Мотоцикл: {row['motorcycle_model']}\n"
        f"Класс: {row['motorcycle_class']}\n"
        f"Экип: {row['passenger_equipment']}\n"
        f"Макс. вес: {row['max_passenger_weight']} кг"
    )


def manual_rider_summary(data: dict) -> str:
    tg_id = data.get("telegram_id")
    username = data.get("username")
    return (
        "Проверьте райдера перед добавлением:\n\n"
        f"Имя: {data.get('name')}\n"
        f"Telegram: @{username or '-'} / ID {tg_id or '-'}\n"
        f"Возраст: {data.get('age')}\n"
        f"Опыт: {data.get('seasons')} сезонов\n"
        f"Как возит: {rider_modes_text(data)}\n"
        f"Класс: {data.get('motorcycle_class')}\n"
        f"Мотоцикл: {data.get('motorcycle_model')}\n"
        f"Экип: {data.get('passenger_equipment')}\n"
        f"Макс. вес пассажира: {data.get('max_passenger_weight')} кг\n"
        f"Забор клиента: {'да' if data.get('can_pickup_client') else 'нет'}\n"
        f"Ночные поездки: {'да' if data.get('can_ride_night') else 'нет'}\n"
        f"Индивидуальные маршруты: {'да' if data.get('can_individual_route') else 'нет'}\n"
        f"Район: {data.get('base_area')}\n"
        f"Комментарий: {data.get('admin_comment') or '-'}\n"
        f"Фото: {len(data.get('photos', []))} шт."
    )


@router.callback_query(F.data == "admin:panel")
async def admin_panel(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "Админ-панель",
        reply_markup=ik([[("Новые заявки", "admin:list_requests"), ("Райдеры на проверке", "admin:list_pending_riders")], [("Добавить райдера", "admin:manual_rider")]]),
    )


@router.message(Command("admin"))
async def admin_command(message: Message, db: Database) -> None:
    if not await require_admin(message, db):
        return
    await message.answer("Админ-панель", reply_markup=ik([[("Новые заявки", "admin:list_requests"), ("Райдеры на проверке", "admin:list_pending_riders")], [("Добавить райдера", "admin:manual_rider")]]))


@router.callback_query(F.data == "admin:list_requests")
async def list_requests(callback: CallbackQuery, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    rows = await db.fetchall("SELECT * FROM client_requests ORDER BY id DESC LIMIT 10")
    if not rows:
        await callback.message.answer("Заявок пока нет.")
        return
    for row in rows:
        await callback.message.answer(
            request_card(row),
            reply_markup=ik([[("Отправить райдерам", f"admin:send_riders:{row['id']}")], [("Отказать", f"admin:reject_client:{row['id']}")]]),
        )


@router.callback_query(F.data == "admin:list_pending_riders")
async def list_pending_riders(callback: CallbackQuery, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    rows = await db.fetchall("SELECT * FROM riders WHERE status='pending' ORDER BY id DESC LIMIT 10")
    if not rows:
        await callback.message.answer("Анкет на проверке нет.")
        return
    for row in rows:
        await callback.message.answer(rider_card(row), reply_markup=ik([[("Добавить в базу", f"admin:approve_rider:{row['id']}")], [("Отказать", f"admin:reject_rider:{row['id']}")]]))


@router.callback_query(F.data.startswith("admin:approve_rider:"))
async def approve_rider(callback: CallbackQuery, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    rider_id = int(callback.data.rsplit(":", 1)[1])
    row = await db.fetchone("SELECT * FROM riders WHERE id=?", rider_id)
    if not row:
        await callback.answer("Райдер не найден.", show_alert=True)
        return
    await db.execute("UPDATE riders SET status='approved', updated_at=? WHERE id=?", now(), rider_id)
    await db.commit()
    await db.add_admin_log(callback.from_user.id, "approve_rider", "rider", rider_id)
    if row["telegram_id"]:
        await callback.bot.send_message(row["telegram_id"], "Ваша анкета одобрена. Теперь вы можете получать заявки на мотопрогулки.")
    await callback.answer("Райдер одобрен.")
    await callback.message.answer(f"Райдер №{rider_id} добавлен в базу.")


@router.callback_query(F.data.startswith("admin:reject_rider:"))
async def reject_rider_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    rider_id = int(callback.data.rsplit(":", 1)[1])
    await state.set_state(AdminFlow.reject_rider)
    await state.update_data(reject_rider_id=rider_id)
    await callback.answer()
    await callback.message.answer("Выберите причину отказа.", reply_markup=ik([[("Недостаточно данных", "admin:reject_rider_reason:Недостаточно данных")], [("Недостаточный опыт", "admin:reject_rider_reason:Недостаточный опыт")], [("Нет подходящего экипа", "admin:reject_rider_reason:Нет подходящего экипа")]]))


@router.callback_query(F.data.startswith("admin:reject_rider_reason:"))
async def reject_rider_finish(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    data = await state.get_data()
    rider_id = data["reject_rider_id"]
    reason = callback.data.removeprefix("admin:reject_rider_reason:")
    row = await db.fetchone("SELECT telegram_id FROM riders WHERE id=?", rider_id)
    await db.execute("UPDATE riders SET status='rejected', admin_comment=?, updated_at=? WHERE id=?", reason, now(), rider_id)
    await db.commit()
    await db.add_admin_log(callback.from_user.id, "reject_rider", "rider", rider_id)
    if row and row["telegram_id"]:
        await callback.bot.send_message(row["telegram_id"], f"К сожалению, анкета отклонена. Причина: {reason}.")
    await state.clear()
    await callback.answer("Отказ отправлен.")


async def matching_riders(db: Database, request_id: int):
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=?", request_id)
    if not req:
        return None, []
    rows = await db.fetchall(
        """
        SELECT * FROM riders
        WHERE status='approved'
          AND motorcycle_class=?
          AND max_passenger_weight>=?
          AND (telegram_id IS NOT NULL)
          AND (? != 'money' OR ride_for_money=1)
          AND (? != 'rules' OR ride_by_rules=1)
          AND (? != 'custom_pickup' OR can_pickup_client=1)
          AND (? != 'Ночь - 00:00-06:00' OR can_ride_night=1)
          AND (? != 'Индивидуальный маршрут' OR can_individual_route=1)
        ORDER BY id DESC
        """,
        req["motorcycle_class"],
        req["client_weight"],
        req["ride_mode"],
        req["ride_mode"],
        req["pickup_type"],
        req["time_slot"],
        req["route_type"],
    )
    return req, rows


@router.callback_query(F.data.startswith("admin:send_riders:"))
async def send_to_riders(callback: CallbackQuery, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    request_id = int(callback.data.rsplit(":", 1)[1])
    req, riders = await matching_riders(db, request_id)
    if not req:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if not riders:
        await callback.message.answer(f"По заявке №{request_id} подходящих активных райдеров не найдено.")
        return
    for rider in riders:
        await callback.bot.send_message(
            rider["telegram_id"],
            (
                f"Новая подходящая заявка №{request_id}\n\n"
                f"Формат катания: {RIDE_MODES.get(req['ride_mode'], 'За деньги')}\n"
                f"Класс: {req['motorcycle_class']}\n"
                f"Маршрут: {req['route_type']}\n"
                f"Дата: {req['date']}\n"
                f"Время: {req['time_slot']}\n"
                f"Посадка: {req['pickup_address']}\n"
                f"Пассажир: {req['client_height']} см / {req['client_weight']} кг\n\n"
                "Контакты клиента будут доступны после назначения администратором."
            ),
            reply_markup=ik([[("Готов взять", f"rresp:accept:{request_id}:{rider['id']}")], [("Отклонить", f"rresp:decline:{request_id}:{rider['id']}")]]),
        )
    await db.execute("UPDATE client_requests SET status='sent_to_riders', updated_at=? WHERE id=?", now(), request_id)
    await db.commit()
    await db.add_admin_log(callback.from_user.id, "send_to_riders", "request", request_id)
    await callback.answer("Отправлено.")
    await callback.message.answer(f"Заявка №{request_id} отправлена райдерам: {len(riders)}.")


@router.callback_query(F.data.startswith("rresp:"))
async def rider_response(callback: CallbackQuery, db: Database) -> None:
    parts = callback.data.split(":")
    action, request_id, rider_id = parts[1], int(parts[2]), int(parts[3])
    status = "accepted" if action == "accept" else "declined"
    await db.execute("INSERT INTO rider_responses(request_id, rider_id, response_status, created_at) VALUES(?, ?, ?, ?)", request_id, rider_id, status, now())
    if status == "accepted":
        await db.execute("UPDATE client_requests SET status='rider_accepted', updated_at=? WHERE id=?", now(), request_id)
    await db.commit()
    admin_id = await db.get_setting("admin_chat_id")
    rider = await db.fetchone("SELECT * FROM riders WHERE id=?", rider_id)
    if admin_id.isdigit() and status == "accepted":
        await callback.bot.send_message(
            int(admin_id),
            f"Райдер откликнулся на заявку №{request_id}\n\n{rider_card(rider)}",
            reply_markup=ik([[("Назначить этого райдера", f"admin:assign:{request_id}:{rider_id}")], [("Не назначать", f"admin:not_assign:{request_id}:{rider_id}")]]),
        )
    await callback.answer("Ответ сохранен.")
    await callback.message.answer("Спасибо, ответ передан администратору.")


@router.callback_query(F.data.startswith("admin:assign:"))
async def assign_rider(callback: CallbackQuery, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    _, _, request_id_raw, rider_id_raw = callback.data.split(":")
    request_id, rider_id = int(request_id_raw), int(rider_id_raw)
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=?", request_id)
    rider = await db.fetchone("SELECT * FROM riders WHERE id=?", rider_id)
    if not req or not rider:
        await callback.answer("Не найдено.", show_alert=True)
        return
    await db.execute("UPDATE client_requests SET status='rider_assigned', assigned_rider_id=?, updated_at=? WHERE id=?", rider_id, now(), request_id)
    await db.commit()
    await db.add_admin_log(callback.from_user.id, "assign_rider", "request", request_id)
    price = "индивидуально" if req["is_individual_price"] else f"{req['final_price']} руб."
    await callback.bot.send_message(
        req["telegram_id"],
        (
            "Вас готов прокатить:\n\n"
            f"Райдер: {rider['name']}\n"
            f"Возраст: {rider['age']} лет\n"
            f"Опыт: {rider['seasons']} сезонов\n"
            f"Мотоцикл: {rider['motorcycle_model']}\n"
            f"Формат катания: {RIDE_MODES.get(req['ride_mode'], 'За деньги')}\n"
            f"Дата: {req['date']}\n"
            f"Время: {req['time_slot']}\n"
            f"Точка посадки: {req['pickup_address']}\n"
            f"Предварительная стоимость: {price}\n\n"
            "Администратор или райдер дополнительно подтвердит детали перед прогулкой."
        ),
    )
    await callback.bot.send_message(
        rider["telegram_id"],
        (
            f"Вы назначены на заявку №{request_id}.\n\n"
            f"Клиент: {req['client_name']}\n"
            f"Контакт: {req['client_phone'] or req['client_username'] or 'через бота'}\n"
            f"Формат катания: {RIDE_MODES.get(req['ride_mode'], 'За деньги')}\n"
            f"Дата: {req['date']}\n"
            f"Время: {req['time_slot']}\n"
            f"Точка посадки: {req['pickup_address']}\n"
            f"Маршрут: {req['route_type']}"
        ),
    )
    await callback.answer("Райдер назначен.")
    await callback.message.answer(f"Райдер №{rider_id} назначен на заявку №{request_id}.")


@router.callback_query(F.data.startswith("admin:reject_client:"))
async def reject_client(callback: CallbackQuery, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    request_id = int(callback.data.rsplit(":", 1)[1])
    req = await db.fetchone("SELECT telegram_id FROM client_requests WHERE id=?", request_id)
    await db.execute("UPDATE client_requests SET status='rejected', updated_at=? WHERE id=?", now(), request_id)
    await db.commit()
    await db.add_admin_log(callback.from_user.id, "reject_client", "request", request_id)
    if req:
        await callback.bot.send_message(req["telegram_id"], "К сожалению, сейчас не получилось организовать мотопрогулку. Администратор может связаться с вами для уточнения.")
    await callback.answer("Заявка отклонена.")


@router.callback_query(F.data == "admin:manual_rider")
async def manual_rider(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await state.clear()
    await state.set_state(AdminFlow.manual_rider_name)
    await state.update_data(photos=[])
    await callback.answer()
    await callback.message.answer("Добавление райдера.\n\nУкажите имя райдера.", reply_markup=nav("admin:panel"))


@router.message(AdminFlow.manual_rider_name)
async def manual_rider_name(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    name = message.text.strip() if message.text else ""
    if len(name) < 2 or name.isdigit():
        await message.answer("Пожалуйста, укажите имя текстом.")
        return
    await state.update_data(name=name)
    await state.set_state(AdminFlow.manual_rider_username)
    await message.answer("Укажите Telegram username райдера без @ или нажмите \"Пропустить\".", reply_markup=ik([[("Пропустить", "admin_manual:username_skip")]]))


@router.callback_query(F.data == "admin_manual:username_skip")
async def manual_rider_username_skip(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(username=None)
    await state.set_state(AdminFlow.manual_rider_telegram_id)
    await callback.message.answer("Укажите Telegram ID райдера или нажмите \"Пропустить\".", reply_markup=ik([[("Пропустить", "admin_manual:telegram_id_skip")]]))


@router.message(AdminFlow.manual_rider_username)
async def manual_rider_username(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    username = (message.text or "").strip().lstrip("@")
    if len(username) < 3:
        await message.answer("Укажите username без @ или нажмите \"Пропустить\".")
        return
    await state.update_data(username=username)
    await state.set_state(AdminFlow.manual_rider_telegram_id)
    await message.answer("Укажите Telegram ID райдера или нажмите \"Пропустить\".", reply_markup=ik([[("Пропустить", "admin_manual:telegram_id_skip")]]))


@router.callback_query(F.data == "admin_manual:telegram_id_skip")
async def manual_rider_telegram_id_skip(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(telegram_id=None)
    await state.set_state(AdminFlow.manual_rider_age)
    await callback.message.answer("Укажите возраст райдера.")


@router.message(AdminFlow.manual_rider_telegram_id)
async def manual_rider_telegram_id(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    value = (message.text or "").strip()
    if not value.isdigit():
        await message.answer("Telegram ID должен быть числом. Если ID неизвестен, нажмите \"Пропустить\".")
        return
    await state.update_data(telegram_id=int(value))
    await state.set_state(AdminFlow.manual_rider_age)
    await message.answer("Укажите возраст райдера.")


@router.message(AdminFlow.manual_rider_age)
async def manual_rider_age(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    if not (message.text or "").isdigit() or not 18 <= int(message.text) <= 80:
        await message.answer("Укажите возраст числом от 18 до 80.")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(AdminFlow.manual_rider_seasons)
    await message.answer("Укажите опыт в сезонах.")


@router.message(AdminFlow.manual_rider_seasons)
async def manual_rider_seasons(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    if not (message.text or "").isdigit() or int(message.text) < 0:
        await message.answer("Укажите опыт числом.")
        return
    await state.update_data(seasons=int(message.text))
    await state.set_state(AdminFlow.manual_rider_motorcycle_class)
    await message.answer(
        "Выберите класс мотоцикла.",
        reply_markup=ik([[("Дорожный", "admin_manual:class:Дорожный"), ("Классик / Кастом", "admin_manual:class:Классик / Кастом")], [("Спорт", "admin_manual:class:Спорт"), ("Электро", "admin_manual:class:Электро")]]),
    )


@router.callback_query(F.data.startswith("admin_manual:class:"))
async def manual_rider_class(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(motorcycle_class=callback.data.removeprefix("admin_manual:class:"))
    await state.set_state(AdminFlow.manual_rider_motorcycle_model)
    await callback.message.answer("Укажите марку и модель мотоцикла.")


@router.message(AdminFlow.manual_rider_motorcycle_model)
async def manual_rider_model(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    model = message.text.strip() if message.text else ""
    if len(model) < 2:
        await message.answer("Укажите марку и модель текстом.")
        return
    await state.update_data(motorcycle_model=model)
    await state.set_state(AdminFlow.manual_rider_equipment)
    await message.answer("Опишите экипировку для пассажира.")


@router.message(AdminFlow.manual_rider_equipment)
async def manual_rider_equipment(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    equipment = message.text.strip() if message.text else ""
    if len(equipment) < 2:
        await message.answer("Опишите экипировку текстом.")
        return
    await state.update_data(passenger_equipment=equipment)
    await state.set_state(AdminFlow.manual_rider_max_passenger_weight)
    await message.answer("Укажите максимальный вес пассажира в кг.")


@router.message(AdminFlow.manual_rider_max_passenger_weight)
async def manual_rider_max_weight(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    if not (message.text or "").isdigit() or not 35 <= int(message.text) <= 220:
        await message.answer("Укажите вес числом от 35 до 220.")
        return
    await state.update_data(max_passenger_weight=int(message.text))
    await state.set_state(AdminFlow.manual_rider_ride_modes)
    await message.answer(
        "Как райдер готов возить?",
        reply_markup=ik([[("За деньги", "admin_manual:ride_modes:money"), ("По правилу", "admin_manual:ride_modes:rules")], [("Оба варианта", "admin_manual:ride_modes:both")]]),
    )


@router.callback_query(F.data.startswith("admin_manual:ride_modes:"))
async def manual_rider_ride_modes(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    value = callback.data.rsplit(":", 1)[1]
    await state.update_data(
        ride_for_money=value in {"money", "both"},
        ride_by_rules=value in {"rules", "both"},
    )
    if value in {"rules", "both"}:
        await state.set_state(AdminFlow.manual_rider_rule_check)
        await callback.message.answer('Проверка правила. Продолжи фразу "Уронил -".')
        return
    await ask_manual_rider_pickup(callback.message, state)


@router.message(AdminFlow.manual_rider_rule_check)
async def manual_rider_rule_check(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    answer = (message.text or "").strip().lower()
    if answer != "женился":
        await state.clear()
        await message.answer(
            "Предлагаем ознакомиться с правилом самостоятельно и вернуться в админ-панель.",
            reply_markup=ik([[("Админ-панель", "admin:panel")]]),
        )
        return
    await ask_manual_rider_pickup(message, state)


async def ask_manual_rider_pickup(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminFlow.manual_rider_can_pickup_client)
    await message.answer("Райдер готов забирать клиента с адреса?", reply_markup=ik([[("Да", "admin_manual:pickup:yes"), ("Нет", "admin_manual:pickup:no")]]))


@router.callback_query(F.data.startswith("admin_manual:pickup:"))
async def manual_rider_pickup(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(can_pickup_client=callback.data.endswith(":yes"))
    await state.set_state(AdminFlow.manual_rider_can_ride_night)
    await callback.message.answer("Райдер готов катать ночью?", reply_markup=ik([[("Да", "admin_manual:night:yes"), ("Нет", "admin_manual:night:no")]]))


@router.callback_query(F.data.startswith("admin_manual:night:"))
async def manual_rider_night(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(can_ride_night=callback.data.endswith(":yes"))
    await state.set_state(AdminFlow.manual_rider_can_individual_route)
    await callback.message.answer("Райдер готов брать индивидуальные маршруты?", reply_markup=ik([[("Да", "admin_manual:individual:yes"), ("Нет", "admin_manual:individual:no")]]))


@router.callback_query(F.data.startswith("admin_manual:individual:"))
async def manual_rider_individual(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(can_individual_route=callback.data.endswith(":yes"))
    await state.set_state(AdminFlow.manual_rider_base_area)
    await callback.message.answer("Укажите район базирования.")


@router.message(AdminFlow.manual_rider_base_area)
async def manual_rider_area(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    area = message.text.strip() if message.text else ""
    if len(area) < 2:
        await message.answer("Укажите район текстом.")
        return
    await state.update_data(base_area=area)
    await state.set_state(AdminFlow.manual_rider_comment)
    await message.answer("Добавьте комментарий или нажмите \"Пропустить\".", reply_markup=ik([[("Пропустить", "admin_manual:comment_skip")]]))


@router.callback_query(F.data == "admin_manual:comment_skip")
async def manual_rider_comment_skip(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(admin_comment="")
    await state.set_state(AdminFlow.manual_rider_photos)
    await callback.message.answer("Загрузите фото мотоцикла. Можно отправить несколько фото, затем нажмите \"Готово\".", reply_markup=ik([[("Готово", "admin_manual:photos_done")], [("Пропустить фото", "admin_manual:photos_skip")]]))


@router.message(AdminFlow.manual_rider_comment)
async def manual_rider_comment(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    await state.update_data(admin_comment=(message.text or "").strip())
    await state.set_state(AdminFlow.manual_rider_photos)
    await message.answer("Загрузите фото мотоцикла. Можно отправить несколько фото, затем нажмите \"Готово\".", reply_markup=ik([[("Готово", "admin_manual:photos_done")], [("Пропустить фото", "admin_manual:photos_skip")]]))


@router.message(AdminFlow.manual_rider_photos, F.photo)
async def manual_rider_photo(message: Message, state: FSMContext, db: Database) -> None:
    if not await require_admin(message, db):
        return
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"Фото добавлено. Сейчас фото: {len(photos)}.", reply_markup=ik([[("Готово", "admin_manual:photos_done")], [("Пропустить фото", "admin_manual:photos_skip")]]))


@router.callback_query(F.data == "admin_manual:photos_skip")
async def manual_rider_photos_skip(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await state.update_data(photos=[])
    await show_manual_rider_confirm(callback.message, state)


@router.callback_query(F.data == "admin_manual:photos_done")
async def manual_rider_photos_done(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    await callback.answer()
    await show_manual_rider_confirm(callback.message, state)


async def show_manual_rider_confirm(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminFlow.manual_rider_confirm)
    data = await state.get_data()
    await message.answer(manual_rider_summary(data), reply_markup=ik([[("Добавить в базу", "admin_manual:save")], [("Отменить", "admin:panel")]]))


@router.callback_query(F.data == "admin_manual:save")
async def manual_rider_save(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await require_admin(callback, db):
        return
    data = await state.get_data()
    cursor = await db.execute(
        """
        INSERT INTO riders(
            telegram_id, username, name, age, seasons, motorcycle_class, motorcycle_model, passenger_equipment,
            max_passenger_weight, ride_for_money, ride_by_rules, can_pickup_client, can_ride_night, can_individual_route, base_area, status,
            admin_comment, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?)
        """,
        data.get("telegram_id"),
        data.get("username"),
        data["name"],
        data["age"],
        data["seasons"],
        data["motorcycle_class"],
        data["motorcycle_model"],
        data["passenger_equipment"],
        data["max_passenger_weight"],
        int(data.get("ride_for_money", True)),
        int(data.get("ride_by_rules", False)),
        int(data["can_pickup_client"]),
        int(data["can_ride_night"]),
        int(data["can_individual_route"]),
        data["base_area"],
        data.get("admin_comment"),
        now(),
        now(),
    )
    await db.commit()
    rider_id = cursor.lastrowid
    for file_id in data.get("photos", []):
        await db.execute("INSERT INTO rider_photos(rider_id, telegram_file_id, created_at) VALUES(?, ?, ?)", rider_id, file_id, now())
    await db.commit()
    await db.add_admin_log(callback.from_user.id, "manual_add_rider", "rider", rider_id)
    await state.clear()
    await callback.answer("Райдер добавлен.")
    await callback.message.answer(
        f"Райдер №{rider_id} добавлен в базу со статусом активен.\n\n"
        "Если райдер еще не запускал бота, попросите его открыть бот и нажать /start, иначе бот не сможет отправлять ему заявки.",
        reply_markup=nav(),
    )
