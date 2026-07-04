CLASS_KEYS = {
    "Дорожный": "price_road",
    "Классик / Кастом": "price_classic_custom",
    "Спорт": "price_sport",
    "Электро": "price_electric",
}

ROUTE_MARKUPS = {
    "Малое кольцо - город": 0,
    "Большое кольцо - город": 20,
    "На выбор райдера": 20,
}


async def calculate_price(db, motorcycle_class: str, route: str, pickup_type: str) -> dict:
    base = int(await db.get_setting(CLASS_KEYS[motorcycle_class], "0"))
    pickup_markup = int(await db.get_setting("pickup_markup", "10")) if pickup_type == "custom_pickup" else 0
    if route == "Индивидуальный маршрут":
        return {
            "base_price": base,
            "pickup_markup_percent": pickup_markup,
            "route_markup_percent": 0,
            "final_price": None,
            "is_individual_price": True,
        }
    route_markup = ROUTE_MARKUPS[route]
    final = round(base * (1 + pickup_markup / 100 + route_markup / 100))
    return {
        "base_price": base,
        "pickup_markup_percent": pickup_markup,
        "route_markup_percent": route_markup,
        "final_price": final,
        "is_individual_price": False,
    }
