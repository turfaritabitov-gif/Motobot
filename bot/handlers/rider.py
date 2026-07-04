from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database, now
from bot.handlers.client import admin_chat_ids
from bot.keyboards import ik, nav, remove_keyboard, yes_no
from bot.states import RiderFlow

router = Router()

CLASSES = ["Дорожный", "Классик / Кастом", "Спорт", "Электро"]


def ride_modes_text(data: dict) -> str:
    modes = []
    if data.get("ride_for_money"):
        modes.append("За деньги")
    if data.get("ride_by_rules"):
        modes.append("По правилу")
    return ", ".join(modes) or "-"


def rider_summary(data: dict, rider_id: int | None = None) -> str:
    title = f"Анкета райдера №{rider_id}\n\n" if rider_id else "Проверьте анкету:\n\n"
    return (
        f"{title}"
        f"Имя: {data.get('name')}\n"
        f"Возраст: {data.get('age')}\n"
        f"Опыт: {data.get('seasons')} сезонов\n"
        f"Как готов возить: {ride_modes_text(data)}\n"
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


@router.callback_query(F.data == "rider:start")
async def start_rider(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(RiderFlow.ride_modes)
    await callback.message.answer(
        "Как готов возить?",
        reply_markup=ik([[("За деньги", "rider:ride_modes:money"), ("По правилу", "rider:ride_modes:rules")], [("Оба варианта", "rider:ride_modes:both")], [("Главное меню", "common:menu")]]),
    )


@router.callback_query(F.data.startswith("rider:ride_modes:"))
async def rider_ride_modes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.rsplit(":", 1)[1]
    await state.update_data(
        ride_for_money=value in {"money", "both"},
        ride_by_rules=value in {"rules", "both"},
    )
    if value in {"rules", "both"}:
        await state.set_state(RiderFlow.rule_check)
        await callback.message.answer('Проверка правила. Продолжи фразу "Уронил -".')
        return
    await ask_rider_name(callback.message, state)


@router.message(RiderFlow.rule_check)
async def rider_rule_check(message: Message, state: FSMContext) -> None:
    answer = (message.text or "").strip().lower()
    if answer != "женился":
        await state.clear()
        await message.answer(
            "Предлагаем ознакомиться с правилом самостоятельно и вернуться в главное меню.",
            reply_markup=nav(),
        )
        return
    await ask_rider_name(message, state)


async def ask_rider_name(message: Message, state: FSMContext) -> None:
    await state.set_state(RiderFlow.name)
    await message.answer("Как вас зовут?", reply_markup=nav("common:menu"))


@router.message(RiderFlow.name)
async def rider_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip() if message.text else ""
    if len(name) < 2 or name.isdigit():
        await message.answer("Пожалуйста, укажите имя текстом.")
        return
    await state.update_data(name=name)
    await state.set_state(RiderFlow.age)
    await message.answer("Сколько вам лет?")


@router.message(RiderFlow.age)
async def rider_age(message: Message, state: FSMContext) -> None:
    if not (message.text or "").isdigit() or not 18 <= int(message.text) <= 80:
        await message.answer("Укажите возраст числом от 18.")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(RiderFlow.seasons)
    await message.answer("Сколько сезонов опыта?")


@router.message(RiderFlow.seasons)
async def rider_seasons(message: Message, state: FSMContext) -> None:
    if not (message.text or "").isdigit() or int(message.text) < 0:
        await message.answer("Укажите опыт числом.")
        return
    await state.update_data(seasons=int(message.text))
    await state.set_state(RiderFlow.motorcycle_class)
    await message.answer("Выберите класс мотоцикла.", reply_markup=ik([[("Дорожный", "rider:class:Дорожный"), ("Классик / Кастом", "rider:class:Классик / Кастом")], [("Спорт", "rider:class:Спорт"), ("Электро", "rider:class:Электро")]]))


@router.callback_query(F.data.startswith("rider:class:"))
async def rider_class(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(motorcycle_class=callback.data.removeprefix("rider:class:"))
    await state.set_state(RiderFlow.motorcycle_model)
    await callback.message.answer("Укажите марку и модель мотоцикла.")


@router.message(RiderFlow.motorcycle_model)
async def rider_model(message: Message, state: FSMContext) -> None:
    model = message.text.strip() if message.text else ""
    if len(model) < 2:
        await message.answer("Укажите марку и модель текстом.")
        return
    await state.update_data(motorcycle_model=model)
    await state.set_state(RiderFlow.equipment)
    await message.answer("Какая экипировка для пассажира есть? Например: шлем, куртка, перчатки.")


@router.message(RiderFlow.equipment)
async def rider_equipment(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Опишите экипировку текстом.")
        return
    await state.update_data(passenger_equipment=message.text.strip())
    await state.set_state(RiderFlow.max_passenger_weight)
    await message.answer("Максимальный вес пассажира в кг?")


@router.message(RiderFlow.max_passenger_weight)
async def rider_max_weight(message: Message, state: FSMContext) -> None:
    if not (message.text or "").isdigit() or not 35 <= int(message.text) <= 220:
        await message.answer("Укажите вес числом.")
        return
    await state.update_data(max_passenger_weight=int(message.text))
    await state.set_state(RiderFlow.can_pickup_client)
    await message.answer("Готовы забирать клиента с адреса?", reply_markup=yes_no("rider:pickup"))


@router.callback_query(F.data.startswith("rider:pickup:"))
async def rider_pickup(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(can_pickup_client=callback.data.endswith(":yes"))
    await state.set_state(RiderFlow.can_ride_night)
    await callback.message.answer("Готовы катать ночью?", reply_markup=yes_no("rider:night"))


@router.callback_query(F.data.startswith("rider:night:"))
async def rider_night(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(can_ride_night=callback.data.endswith(":yes"))
    await state.set_state(RiderFlow.can_individual_route)
    await callback.message.answer("Готовы брать индивидуальные маршруты?", reply_markup=yes_no("rider:individual"))


@router.callback_query(F.data.startswith("rider:individual:"))
async def rider_individual(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(can_individual_route=callback.data.endswith(":yes"))
    await state.set_state(RiderFlow.base_area)
    await callback.message.answer("Укажите район базирования.")


@router.message(RiderFlow.base_area)
async def rider_area(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Укажите район текстом.")
        return
    await state.update_data(base_area=message.text.strip())
    await state.set_state(RiderFlow.comment)
    await message.answer("Добавьте комментарий или напишите \"нет\".")


@router.message(RiderFlow.comment)
async def rider_comment(message: Message, state: FSMContext) -> None:
    comment = "" if (message.text or "").strip().lower() == "нет" else (message.text or "").strip()
    await state.update_data(admin_comment=comment, photos=[])
    await state.set_state(RiderFlow.photos)
    await message.answer("Загрузите фото мотоцикла. Можно отправить несколько фото, затем нажмите \"Готово\".", reply_markup=ik([[("Готово", "rider:photos_done")]]))


@router.message(RiderFlow.photos, F.photo)
async def rider_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"Фото добавлено. Сейчас фото: {len(photos)}.", reply_markup=ik([[("Готово", "rider:photos_done")]]))


@router.callback_query(F.data == "rider:photos_done")
async def photos_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    if not data.get("photos"):
        await callback.message.answer("Добавьте хотя бы одно фото мотоцикла.")
        return
    await state.set_state(RiderFlow.confirm)
    await callback.message.answer(rider_summary(data), reply_markup=ik([[("Отправить анкету", "rider:submit")], [("Главное меню", "common:menu")]]))


@router.callback_query(F.data == "rider:submit")
async def rider_submit(callback: CallbackQuery, state: FSMContext, db: Database, config: Config) -> None:
    await callback.answer()
    data = await state.get_data()
    cursor = await db.execute(
        """
        INSERT INTO riders(
            telegram_id, username, name, age, seasons, motorcycle_class, motorcycle_model, passenger_equipment,
            max_passenger_weight, ride_for_money, ride_by_rules, can_pickup_client, can_ride_night, can_individual_route, base_area, status,
            admin_comment, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        callback.from_user.id,
        callback.from_user.username,
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
    await callback.message.answer("Анкета отправлена администратору. Мы сообщим о решении.", reply_markup=nav())
    for admin_id in await admin_chat_ids(db, config):
        try:
            await callback.bot.send_message(
                admin_id,
                "Новая анкета райдера.\n\n" + rider_summary(data, rider_id),
                reply_markup=ik([[("Добавить в базу", f"admin:approve_rider:{rider_id}"), ("Фото", f"admin:rider_photos:{rider_id}")], [("Отказать", f"admin:reject_rider:{rider_id}")]]),
            )
        except Exception:
            pass
    await state.clear()
