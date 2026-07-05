from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database, now
from bot.keyboards import ik, location_keyboard, nav, phone_keyboard, remove_keyboard
from bot.services.pricing import calculate_price
from bot.services.trips import schedule_trip_notifications
from bot.states import ClientFlow, TripFlow
from bot.texts import CONSENT

router = Router()

CLASSES = ["Дорожный", "Классик / Кастом", "Спорт", "Электро"]
ROUTES = ["Малое кольцо - город", "Большое кольцо - город", "На выбор райдера", "Индивидуальный маршрут"]
TIME_SLOTS = ["Утро - 06:00-12:00", "День - 12:00-18:00", "Вечер - 18:00-00:00", "Ночь - 00:00-06:00"]

RIDE_MODES = {
    "money": "За деньги",
    "rules": "По правилам",
}


def share_text() -> str:
    return "Спасибо! Будем рады видеть вас снова. Поделитесь ботом с друзьями: @motoprog_bot"


def score_keyboard(prefix: str):
    return ik([[(str(i), f"{prefix}:{i}") for i in range(1, 6)]])


def rider_card_for_client(row) -> str:
    return (
        f"Райдер: {row['name']}\n"
        f"Возраст: {row['age']} лет\n"
        f"Опыт: {row['seasons']} сезонов\n"
        f"Мотоцикл: {row['motorcycle_model']}\n"
        f"Класс: {row['motorcycle_class']}\n"
        f"Экип: {row['passenger_equipment']}"
    )


def class_keyboard(weight: int | None = None):
    classes = CLASSES if not weight or weight <= 100 else CLASSES[:2]
    rows = [[(c, f"client:class:{c}") for c in classes[:2]]]
    if classes[2:]:
        rows.append([(c, f"client:class:{c}") for c in classes[2:]])
    rows.append([("Назад", "client:back:weight"), ("Главное меню", "common:menu")])
    return ik(rows)


def request_summary(data: dict, request_id: int | None = None) -> str:
    price = "индивидуально" if data.get("is_individual_price") else f"{data.get('final_price')} руб."
    title = f"Заявка №{request_id}\n\n" if request_id else "Проверьте заявку:\n\n"
    return (
        f"{title}"
        f"Имя: {data.get('client_name')}\n"
        f"Возраст: {data.get('client_age')}\n"
        f"Рост/вес: {data.get('client_height')} см / {data.get('client_weight')} кг\n"
        f"Контакт: {data.get('client_phone') or data.get('client_username') or 'через Telegram'}\n"
        f"Формат катания: {RIDE_MODES.get(data.get('ride_mode'), 'За деньги')}\n"
        f"Класс: {data.get('motorcycle_class')}\n"
        f"Маршрут: {data.get('route_type')}\n"
        f"Дата: {data.get('date')}\n"
        f"Время: {data.get('time_slot')}\n"
        f"Посадка: {data.get('pickup_address')}\n"
        f"Предварительная стоимость: {price}"
    )


async def admin_chat_ids(db: Database, config: Config) -> list[int]:
    ids = set(config.admin_chat_ids)
    legacy_value = await db.get_setting("admin_chat_id")
    if legacy_value.lstrip("-").isdigit():
        ids.add(int(legacy_value))
    values = await db.get_setting("admin_chat_ids")
    for chunk in values.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            ids.add(int(chunk))
    rows = await db.fetchall("SELECT telegram_id FROM users WHERE role='admin' AND is_blocked=0")
    ids.update(row["telegram_id"] for row in rows)
    return sorted(ids)


@router.callback_query(F.data == "client:start")
async def start_client(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(ClientFlow.ride_mode)
    await callback.message.answer(
        "Выберите формат катания.",
        reply_markup=ik([[("За деньги", "client:ride_mode:money"), ("По правилам", "client:ride_mode:rules")], [("Назад", "common:menu")]]),
    )


@router.callback_query(F.data.startswith("client:ride_mode:"))
async def ride_mode(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.rsplit(":", 1)[1]
    await state.update_data(ride_mode=value)
    if value == "rules":
        await state.set_state(ClientFlow.rule_check)
        await callback.message.answer('Правила знаешь? Продолжи фразу "Села - ".')
        return
    await show_consent(callback.message, state)


@router.message(ClientFlow.rule_check)
async def client_rule_check(message: Message, state: FSMContext) -> None:
    answer = (message.text or "").strip().lower()
    if answer != "дала":
        await state.clear()
        await message.answer(
            "Предлагаем ознакомиться с правилом самостоятельно и вернуться в главное меню.",
            reply_markup=nav(),
        )
        return
    await show_consent(message, state)


async def show_consent(message: Message, state: FSMContext) -> None:
    await message.answer(CONSENT, reply_markup=ik([[("Согласен, продолжить", "client:consent")], [("Назад", "common:menu")]]))


@router.callback_query(F.data == "client:consent")
async def consent(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.name)
    await state.update_data(consent_accepted_at=now())
    await callback.message.answer("Как тебя зовут?", reply_markup=nav("client:start"))


@router.message(ClientFlow.name)
async def client_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip() if message.text else ""
    if len(name) < 2 or len(name) > 50 or name.isdigit():
        await message.answer("Пожалуйста, укажи имя текстом.")
        return
    await state.update_data(client_name=name)
    await state.set_state(ClientFlow.age)
    await message.answer("Сколько тебе лет?", reply_markup=nav("client:consent"))


@router.message(ClientFlow.age)
async def client_age(message: Message, state: FSMContext) -> None:
    if not (message.text or "").isdigit():
        await message.answer("Укажи возраст числом.")
        return
    age = int(message.text)
    if age < 16:
        await state.clear()
        await message.answer("Извините, сейчас мотопрогулки доступны только для пользователей от 16 лет.", reply_markup=nav())
        return
    await state.update_data(client_age=age)
    if age < 18:
        await state.set_state(ClientFlow.minor_confirm)
        await message.answer(
            "Для пользователей младше 18 лет мотопрогулка возможна только при согласии законного представителя. "
            "Администратор может запросить дополнительное подтверждение.",
            reply_markup=ik([[("Продолжить", "client:minor_continue")], [("Назад", "client:back:name")]]),
        )
        return
    await state.set_state(ClientFlow.height)
    await message.answer("Какой у тебя рост в сантиметрах?", reply_markup=nav("client:back:name"))


@router.callback_query(F.data == "client:minor_continue")
async def minor_continue(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.height)
    await callback.message.answer("Какой у тебя рост в сантиметрах?", reply_markup=nav("client:back:age"))


@router.message(ClientFlow.height)
async def client_height(message: Message, state: FSMContext) -> None:
    if not (message.text or "").isdigit() or not 120 <= int(message.text) <= 220:
        await message.answer("Укажи рост числом в сантиметрах, например: 175.")
        return
    await state.update_data(client_height=int(message.text))
    await state.set_state(ClientFlow.weight)
    await message.answer("Какой у тебя вес в килограммах?", reply_markup=nav("client:back:age"))


@router.message(ClientFlow.weight)
async def client_weight(message: Message, state: FSMContext) -> None:
    if not (message.text or "").isdigit() or not 35 <= int(message.text) <= 180:
        await message.answer("Укажи вес числом в килограммах, например: 70.")
        return
    weight = int(message.text)
    await state.update_data(client_weight=weight)
    if weight > 100:
        await message.answer("Для некоторых классов мотоциклов есть ограничения. Классы \"Спорт\" и \"Электро\" сейчас недоступны.")
    await state.set_state(ClientFlow.contact)
    await message.answer(
        "Оставь контакт для связи. Можно отправить номер телефона или продолжить с Telegram-контактом.",
        reply_markup=ik([[("Отправить номер телефона", "client:phone")], [("Использовать Telegram", "client:telegram")], [("Назад", "client:back:height")]]),
    )


@router.callback_query(F.data == "client:phone")
async def ask_phone(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.contact_phone)
    await callback.message.answer("Нажмите кнопку ниже, чтобы отправить номер телефона.", reply_markup=phone_keyboard())


@router.message(ClientFlow.contact_phone)
async def save_phone(message: Message, state: FSMContext, db: Database) -> None:
    if not message.contact:
        await message.answer("Пожалуйста, отправьте контакт кнопкой ниже.", reply_markup=phone_keyboard())
        return
    await db.upsert_user(message.from_user, phone=message.contact.phone_number)
    await state.update_data(client_phone=message.contact.phone_number, client_username=f"@{message.from_user.username}" if message.from_user.username else None)
    await state.set_state(ClientFlow.motorcycle_class)
    data = await state.get_data()
    await message.answer("Выбери класс мотоцикла.", reply_markup=class_keyboard(data.get("client_weight")))


@router.callback_query(F.data == "client:telegram")
async def use_telegram(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    username = callback.from_user.username
    await state.update_data(client_username=f"@{username}" if username else None)
    if not username:
        await state.set_state(ClientFlow.no_username)
        await callback.message.answer(
            "У вас не указан Telegram username. Администратор все равно сможет связаться с вами через бота, но для удобства можно также отправить номер телефона.",
            reply_markup=ik([[("Отправить номер телефона", "client:phone")], [("Продолжить без телефона", "client:no_phone")]]),
        )
        return
    await state.set_state(ClientFlow.motorcycle_class)
    data = await state.get_data()
    await callback.message.answer("Выбери класс мотоцикла.", reply_markup=class_keyboard(data.get("client_weight")))


@router.callback_query(F.data == "client:no_phone")
async def no_phone(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.motorcycle_class)
    data = await state.get_data()
    await callback.message.answer("Выбери класс мотоцикла.", reply_markup=class_keyboard(data.get("client_weight")))


@router.callback_query(F.data.startswith("client:class:"))
async def motorcycle_class(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.removeprefix("client:class:")
    data = await state.get_data()
    if data.get("client_weight", 0) > 100 and value in {"Спорт", "Электро"}:
        await callback.message.answer("Этот класс недоступен при указанном весе. Выберите другой класс.")
        return
    await state.update_data(motorcycle_class=value)
    await state.set_state(ClientFlow.route)
    await callback.message.answer("Выбери маршрут.", reply_markup=ik([[("Малое кольцо - город", "client:route:Малое кольцо - город")], [("Большое кольцо - город", "client:route:Большое кольцо - город")], [("На выбор райдера", "client:route:На выбор райдера")], [("Индивидуальный маршрут", "client:route:Индивидуальный маршрут")], [("Назад", "client:back:contact")]]))


@router.callback_query(F.data.startswith("client:route:"))
async def route(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.removeprefix("client:route:")
    await state.update_data(route_type=value)
    if value == "Индивидуальный маршрут":
        await state.set_state(ClientFlow.route_individual)
        await callback.message.answer("Стоимость индивидуального маршрута согласовывается отдельно с райдером и администратором.", reply_markup=ik([[("Продолжить", "client:route_continue")], [("Назад", "client:back:class")]]))
        return
    await state.set_state(ClientFlow.date)
    await callback.message.answer("Выберите желаемую дату прогулки в формате ДД.ММ.ГГГГ.", reply_markup=nav("client:back:class"))


@router.callback_query(F.data == "client:route_continue")
async def route_continue(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.date)
    await callback.message.answer("Выберите желаемую дату прогулки в формате ДД.ММ.ГГГГ.", reply_markup=nav("client:back:route"))


@router.message(ClientFlow.date)
async def client_date(message: Message, state: FSMContext, db: Database) -> None:
    try:
        chosen = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except Exception:
        await message.answer("Пожалуйста, укажите дату в формате ДД.ММ.ГГГГ, например: 15.06.2026.")
        return
    today = datetime.now().date()
    max_days = int(await db.get_setting("max_booking_days", "60"))
    if chosen < today or chosen > today + timedelta(days=max_days):
        await message.answer(f"Дата не может быть в прошлом или дальше чем на {max_days} дней вперед.")
        return
    await state.update_data(date=chosen.strftime("%d.%m.%Y"))
    await state.set_state(ClientFlow.time_slot)
    await message.answer("Выберите желаемое время прогулки.", reply_markup=ik([[("Утро - 06:00-12:00", "client:time:Утро - 06:00-12:00")], [("День - 12:00-18:00", "client:time:День - 12:00-18:00")], [("Вечер - 18:00-00:00", "client:time:Вечер - 18:00-00:00")], [("Ночь - 00:00-06:00", "client:time:Ночь - 00:00-06:00")]]))


@router.callback_query(F.data.startswith("client:time:"))
async def time_slot(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(time_slot=callback.data.removeprefix("client:time:"))
    await state.set_state(ClientFlow.pickup_type)
    await callback.message.answer("Откуда вас забрать?", reply_markup=ik([[("Приеду на точку сбора", "client:pickup:meeting")], [("Заберите меня", "client:pickup:custom")]]))


@router.callback_query(F.data == "client:pickup:meeting")
async def pickup_meeting(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await callback.answer()
    lat = float(await db.get_setting("meeting_point_lat"))
    lng = float(await db.get_setting("meeting_point_lng"))
    address = await db.get_setting("meeting_point_address")
    await state.update_data(pickup_type="meeting_point", pickup_address=address, pickup_lat=lat, pickup_lng=lng)
    await callback.message.answer(f"{address}.\n\nПосле назначения райдера администратор подтвердит точное место встречи.")
    await show_confirm(callback.message, state, db)


@router.callback_query(F.data == "client:pickup:custom")
async def pickup_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.pickup_method)
    await callback.message.answer("Укажите адрес или отправьте координаты.", reply_markup=ik([[("Указать адрес", "client:pickup_address")], [("Отправить координаты", "client:pickup_location")]]))


@router.callback_query(F.data == "client:pickup_address")
async def pickup_address_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.pickup_address)
    await callback.message.answer("Введите адрес, откуда вас забрать.", reply_markup=nav("client:pickup:custom"))


@router.message(ClientFlow.pickup_address)
async def pickup_address_save(message: Message, state: FSMContext, db: Database) -> None:
    if not message.text or len(message.text.strip()) < 5:
        await message.answer("Пожалуйста, укажите адрес чуть подробнее.")
        return
    await state.update_data(pickup_type="custom_pickup", pickup_address=message.text.strip(), pickup_lat=None, pickup_lng=None)
    await show_confirm(message, state, db)


@router.callback_query(F.data == "client:pickup_location")
async def pickup_location_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.pickup_location)
    await callback.message.answer("Отправьте геолокацию кнопкой ниже.", reply_markup=location_keyboard())


@router.message(ClientFlow.pickup_location)
async def pickup_location_save(message: Message, state: FSMContext, db: Database) -> None:
    if not message.location:
        await message.answer("Пожалуйста, отправьте геолокацию кнопкой ниже.", reply_markup=location_keyboard())
        return
    address = f"Координаты: {message.location.latitude}, {message.location.longitude}"
    await state.update_data(pickup_type="custom_pickup", pickup_address=address, pickup_lat=message.location.latitude, pickup_lng=message.location.longitude)
    await show_confirm(message, state, db)


async def show_confirm(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    price = await calculate_price(db, data["motorcycle_class"], data["route_type"], data["pickup_type"])
    await state.update_data(**price)
    data = await state.get_data()
    await state.set_state(ClientFlow.confirm)
    await message.answer(
        request_summary(data),
        reply_markup=ik([[("Отправить заявку", "client:submit")], [("Редактировать", "client:edit")], [("Главное меню", "common:menu")]]),
    )


@router.callback_query(F.data == "client:edit")
async def edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ClientFlow.edit_field)
    await callback.message.answer(
        "Что изменить?",
        reply_markup=ik([[("Имя", "client:edit:name"), ("Возраст", "client:edit:age")], [("Рост", "client:edit:height"), ("Вес", "client:edit:weight")], [("Класс", "client:edit:class"), ("Маршрут", "client:edit:route")], [("Дата", "client:edit:date"), ("Время", "client:edit:time")], [("Посадка", "client:edit:pickup")]]),
    )


@router.callback_query(F.data.startswith("client:edit:"))
async def edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    field = callback.data.rsplit(":", 1)[1]
    mapping = {
        "name": (ClientFlow.name, "Как тебя зовут?"),
        "age": (ClientFlow.age, "Сколько тебе лет?"),
        "height": (ClientFlow.height, "Какой у тебя рост в сантиметрах?"),
        "weight": (ClientFlow.weight, "Какой у тебя вес в килограммах?"),
        "class": (ClientFlow.motorcycle_class, "Выбери класс мотоцикла."),
        "route": (ClientFlow.route, "Выбери маршрут."),
        "date": (ClientFlow.date, "Выберите дату в формате ДД.ММ.ГГГГ."),
        "time": (ClientFlow.time_slot, "Выберите время."),
        "pickup": (ClientFlow.pickup_type, "Откуда вас забрать?"),
    }
    await state.set_state(mapping[field][0])
    data = await state.get_data()
    if field == "class":
        await callback.message.answer(mapping[field][1], reply_markup=class_keyboard(data.get("client_weight")))
    elif field == "route":
        await callback.message.answer(mapping[field][1], reply_markup=ik([[("Малое кольцо - город", "client:route:Малое кольцо - город")], [("Большое кольцо - город", "client:route:Большое кольцо - город")], [("На выбор райдера", "client:route:На выбор райдера")], [("Индивидуальный маршрут", "client:route:Индивидуальный маршрут")]]))
    elif field == "time":
        await callback.message.answer(mapping[field][1], reply_markup=ik([[("Утро - 06:00-12:00", "client:time:Утро - 06:00-12:00")], [("День - 12:00-18:00", "client:time:День - 12:00-18:00")], [("Вечер - 18:00-00:00", "client:time:Вечер - 18:00-00:00")], [("Ночь - 00:00-06:00", "client:time:Ночь - 00:00-06:00")]]))
    elif field == "pickup":
        await callback.message.answer(mapping[field][1], reply_markup=ik([[("Приеду на точку сбора", "client:pickup:meeting")], [("Заберите меня", "client:pickup:custom")]]))
    else:
        await callback.message.answer(mapping[field][1])


@router.callback_query(F.data == "client:submit")
async def submit(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await callback.answer()
    data = await state.get_data()
    cursor = await db.execute(
        """
        INSERT INTO client_requests(
            telegram_id, client_name, client_age, client_height, client_weight, client_phone, client_username,
            ride_mode, motorcycle_class, route_type, date, time_slot, pickup_type, pickup_address, pickup_lat, pickup_lng,
            base_price, pickup_markup_percent, route_markup_percent, final_price, is_individual_price, status,
            consent_accepted, consent_accepted_at, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', 1, ?, ?, ?)
        """,
        callback.from_user.id,
        data["client_name"],
        data["client_age"],
        data["client_height"],
        data["client_weight"],
        data.get("client_phone"),
        data.get("client_username"),
        data.get("ride_mode", "money"),
        data["motorcycle_class"],
        data["route_type"],
        data["date"],
        data["time_slot"],
        data["pickup_type"],
        data["pickup_address"],
        data.get("pickup_lat"),
        data.get("pickup_lng"),
        data.get("base_price"),
        data.get("pickup_markup_percent"),
        data.get("route_markup_percent"),
        data.get("final_price"),
        int(data.get("is_individual_price", False)),
        data.get("consent_accepted_at", now()),
        now(),
        now(),
    )
    await db.commit()
    request_id = cursor.lastrowid
    await callback.message.answer(f"Заявка №{request_id} принята. Администратор подберет райдера и свяжется с вами.", reply_markup=nav())
    for admin_id in await admin_chat_ids(db, config):
        try:
            await callback.bot.send_message(
                admin_id,
                "Новая клиентская заявка.\n\n" + request_summary(data, request_id),
                reply_markup=ik([[("Отправить подходящим райдерам", f"admin:send_riders:{request_id}")], [("Отказать", f"admin:reject_client:{request_id}")]]),
            )
        except Exception:
            pass
    await state.clear()


async def notify_admins(bot, db: Database, config: Config, text: str, reply_markup=None) -> None:
    for admin_id in await admin_chat_ids(db, config):
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            pass


async def confirm_trip(bot, db: Database, request_id: int, rider_id: int) -> tuple[bool, str]:
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=?", request_id)
    rider = await db.fetchone("SELECT * FROM riders WHERE id=?", rider_id)
    if not req or not rider or req["telegram_id"] is None or not rider["telegram_id"]:
        return False, "Заявка или райдер не найдены."
    await db.execute("UPDATE client_requests SET status='trip_confirmed', assigned_rider_id=?, updated_at=? WHERE id=?", rider_id, now(), request_id)
    await db.commit()
    await schedule_trip_notifications(db, request_id)
    price = "индивидуально" if req["is_individual_price"] else f"{req['final_price']} руб."
    await bot.send_message(
        req["telegram_id"],
        (
            "Поездка согласована.\n\n"
            f"{rider_card_for_client(rider)}\n"
            f"Дата: {req['date']}\n"
            f"Время: {req['time_slot']}\n"
            f"Точка посадки: {req['pickup_address']}\n"
            f"Предварительная стоимость: {price}\n\n"
            f"{share_text()}"
        ),
    )
    await bot.send_message(
        rider["telegram_id"],
        (
            f"Клиент подтвердил заявку №{request_id}.\n\n"
            f"Клиент: {req['client_name']}\n"
            f"Контакт: {req['client_phone'] or req['client_username'] or 'через бота'}\n"
            f"Дата: {req['date']}\n"
            f"Время: {req['time_slot']}\n"
            f"Точка посадки: {req['pickup_address']}\n"
            f"Маршрут: {req['route_type']}"
        ),
    )
    return True, "Поездка согласована."


@router.callback_query(F.data.startswith("client:rider_accept:"))
async def client_accept_rider(callback: CallbackQuery, db: Database, config: Config) -> None:
    _, _, request_id_raw, rider_id_raw = callback.data.split(":")
    request_id, rider_id = int(request_id_raw), int(rider_id_raw)
    req = await db.fetchone("SELECT status, assigned_rider_id FROM client_requests WHERE id=? AND telegram_id=?", request_id, callback.from_user.id)
    if not req or req["status"] != "rider_assigned" or req["assigned_rider_id"] != rider_id:
        await callback.answer("Это согласование уже неактуально.", show_alert=True)
        return
    ok, message = await confirm_trip(callback.bot, db, request_id, rider_id)
    await callback.answer(message, show_alert=not ok)
    if ok:
        await notify_admins(callback.bot, db, config, f"Клиент подтвердил райдера по заявке №{request_id}.")


@router.callback_query(F.data.startswith("client:rider_reject:"))
async def client_reject_rider(callback: CallbackQuery, db: Database, config: Config) -> None:
    _, _, request_id_raw, rider_id_raw = callback.data.split(":")
    request_id, rider_id = int(request_id_raw), int(rider_id_raw)
    req = await db.fetchone("SELECT status, assigned_rider_id FROM client_requests WHERE id=? AND telegram_id=?", request_id, callback.from_user.id)
    if not req or req["status"] != "rider_assigned" or req["assigned_rider_id"] != rider_id:
        await callback.answer("Это согласование уже неактуально.", show_alert=True)
        return
    await db.execute("INSERT OR IGNORE INTO request_rejected_riders(request_id, rider_id, created_at) VALUES(?, ?, ?)", request_id, rider_id, now())
    await db.execute("UPDATE client_requests SET status='rider_accepted', assigned_rider_id=NULL, updated_at=? WHERE id=?", now(), request_id)
    await db.commit()
    await callback.answer()
    await callback.message.answer("Поняли. Предложим администратору подобрать нового райдера.")
    await notify_admins(
        callback.bot,
        db,
        config,
        f"Клиент отказался от райдера по заявке №{request_id}. Нужно подобрать нового из откликнувшихся.",
        reply_markup=ik([[("Выбрать другого райдера", f"admin:choose_alt:{request_id}")]]),
    )


@router.callback_query(F.data.startswith("client:show_rejected:"))
async def show_rejected_riders(callback: CallbackQuery, db: Database) -> None:
    request_id = int(callback.data.rsplit(":", 1)[1])
    req = await db.fetchone("SELECT telegram_id, status FROM client_requests WHERE id=?", request_id)
    if not req or req["telegram_id"] != callback.from_user.id or req["status"] == "trip_confirmed":
        await callback.answer("Список уже неактуален.", show_alert=True)
        return
    rows = await db.fetchall(
        """
        SELECT r.* FROM request_rejected_riders rr
        JOIN riders r ON r.id=rr.rider_id
        WHERE rr.request_id=? AND r.status='approved'
        ORDER BY rr.created_at
        """,
        request_id,
    )
    if not rows:
        await callback.answer("Ранее отклонённых райдеров нет.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("Ранее отклонённые райдеры:")
    for rider in rows:
        await callback.message.answer(
            rider_card_for_client(rider),
            reply_markup=ik([[("Выбрать этого райдера", f"client:choose_rejected:{request_id}:{rider['id']}")]]),
        )


@router.callback_query(F.data.startswith("client:choose_rejected:"))
async def choose_rejected_rider(callback: CallbackQuery, db: Database, config: Config) -> None:
    _, _, request_id_raw, rider_id_raw = callback.data.split(":")
    request_id, rider_id = int(request_id_raw), int(rider_id_raw)
    req = await db.fetchone("SELECT telegram_id, status FROM client_requests WHERE id=?", request_id)
    if not req or req["telegram_id"] != callback.from_user.id or req["status"] == "trip_confirmed":
        await callback.answer("Выбор уже неактуален.", show_alert=True)
        return
    ok, message = await confirm_trip(callback.bot, db, request_id, rider_id)
    await callback.answer(message, show_alert=not ok)
    if ok:
        await notify_admins(callback.bot, db, config, f"Клиент выбрал ранее отклонённого райдера по заявке №{request_id}.")


@router.callback_query(F.data.startswith("trip:client:"))
async def client_trip_report(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    _, _, answer, request_id_raw = callback.data.split(":")
    request_id = int(request_id_raw)
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=? AND telegram_id=?", request_id, callback.from_user.id)
    if not req:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await callback.answer()
    if answer == "no":
        await state.set_state(TripFlow.client_no_reason)
        await state.update_data(report_request_id=request_id)
        await callback.message.answer("Укажите, пожалуйста, причину в свободной форме.")
        return
    await state.set_state(TripFlow.client_rating_transport)
    await state.update_data(report_request_id=request_id)
    await callback.message.answer("Оцените состояние транспорта от 1 до 5.", reply_markup=score_keyboard("trip:score:transport"))


@router.callback_query(F.data.startswith("trip:score:"))
async def client_score(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    _, _, field, score_raw = callback.data.split(":")
    score = int(score_raw)
    data = await state.get_data()
    if field == "transport":
        await state.update_data(transport_score=score)
        await state.set_state(TripFlow.client_rating_politeness)
        await callback.answer()
        await callback.message.answer("Оцените вежливость райдера от 1 до 5.", reply_markup=score_keyboard("trip:score:politeness"))
        return
    if field == "politeness":
        await state.update_data(politeness_score=score)
        await state.set_state(TripFlow.client_rating_driving)
        await callback.answer()
        await callback.message.answer("Оцените манеру вождения от 1 до 5.", reply_markup=score_keyboard("trip:score:driving"))
        return
    request_id = data["report_request_id"]
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=?", request_id)
    existing = await db.fetchone("SELECT id FROM ride_feedback WHERE request_id=? AND client_telegram_id=?", request_id, callback.from_user.id)
    if existing:
        await state.clear()
        await callback.answer("Оценка уже сохранена.", show_alert=True)
        return
    transport = data["transport_score"]
    politeness = data["politeness_score"]
    driving = score
    rider_id = req["assigned_rider_id"]
    await db.execute(
        "INSERT INTO ride_feedback(request_id, rider_id, client_telegram_id, transport_score, politeness_score, driving_score, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
        request_id,
        rider_id,
        callback.from_user.id,
        transport,
        politeness,
        driving,
        now(),
    )
    await db.execute(
        """
        UPDATE riders SET
            completed_trips=completed_trips+1,
            rating_count=rating_count+3,
            rating_sum_total=rating_sum_total+?,
            rating_sum_transport=rating_sum_transport+?,
            rating_sum_politeness=rating_sum_politeness+?,
            rating_sum_driving=rating_sum_driving+?,
            updated_at=?
        WHERE id=?
        """,
        transport + politeness + driving,
        transport,
        politeness,
        driving,
        now(),
        rider_id,
    )
    await db.execute("INSERT INTO trip_reports(request_id, reporter_role, telegram_id, did_happen, created_at) VALUES(?, 'client', ?, 1, ?)", request_id, callback.from_user.id, now())
    await db.commit()
    await state.clear()
    await callback.answer("Спасибо за оценку.")
    await callback.message.answer(share_text())


@router.message(TripFlow.client_no_reason)
async def client_no_reason(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    data = await state.get_data()
    request_id = data["report_request_id"]
    reason = (message.text or "").strip()
    await db.execute(
        "INSERT INTO trip_reports(request_id, reporter_role, telegram_id, did_happen, reason, created_at) VALUES(?, 'client', ?, 0, ?, ?)",
        request_id,
        message.from_user.id,
        reason,
        now(),
    )
    await db.commit()
    await state.clear()
    await notify_admins(message.bot, db, config, f"Клиент сообщил, что поездка №{request_id} не состоялась.\nПричина: {reason}")
    await message.answer(share_text())


@router.callback_query(F.data.startswith("trip:rider:"))
async def rider_trip_report(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    _, _, answer, request_id_raw = callback.data.split(":")
    request_id = int(request_id_raw)
    req = await db.fetchone("SELECT * FROM client_requests WHERE id=?", request_id)
    rider = await db.fetchone("SELECT * FROM riders WHERE id=? AND telegram_id=?", req["assigned_rider_id"], callback.from_user.id) if req else None
    if not req or not rider:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await callback.answer()
    if answer == "no":
        await state.set_state(TripFlow.rider_no_reason)
        await state.update_data(report_request_id=request_id)
        await callback.message.answer("Укажите, пожалуйста, причину в свободной форме.")
        return
    if req["ride_mode"] == "money":
        await callback.message.answer("Клиент произвёл расчёт с вами?", reply_markup=ik([[("Да", f"trip:rider_payment:yes:{request_id}"), ("Нет", f"trip:rider_payment:no:{request_id}")]]))
        return
    await db.execute("INSERT INTO trip_reports(request_id, reporter_role, telegram_id, did_happen, created_at) VALUES(?, 'rider', ?, 1, ?)", request_id, callback.from_user.id, now())
    await db.commit()
    await callback.message.answer(share_text())


@router.callback_query(F.data.startswith("trip:rider_payment:"))
async def rider_payment_report(callback: CallbackQuery, db: Database) -> None:
    _, _, answer, request_id_raw = callback.data.split(":")
    request_id = int(request_id_raw)
    payment_received = answer == "yes"
    await db.execute(
        "INSERT INTO trip_reports(request_id, reporter_role, telegram_id, did_happen, payment_received, created_at) VALUES(?, 'rider', ?, 1, ?, ?)",
        request_id,
        callback.from_user.id,
        int(payment_received),
        now(),
    )
    await db.commit()
    await callback.answer()
    if payment_received:
        await callback.message.answer("Спасибо! Если хотите поддержать сообщество, можно отправить донат в Мото помощь. " + share_text())
    else:
        await callback.message.answer(share_text())


@router.message(TripFlow.rider_no_reason)
async def rider_no_reason(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    data = await state.get_data()
    request_id = data["report_request_id"]
    reason = (message.text or "").strip()
    await db.execute(
        "INSERT INTO trip_reports(request_id, reporter_role, telegram_id, did_happen, reason, created_at) VALUES(?, 'rider', ?, 0, ?, ?)",
        request_id,
        message.from_user.id,
        reason,
        now(),
    )
    await db.commit()
    await state.clear()
    await notify_admins(message.bot, db, config, f"Райдер сообщил, что поездка №{request_id} не состоялась.\nПричина: {reason}")
    await message.answer(share_text())
