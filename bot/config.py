from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_username: str
    admin_chat_ids: tuple[int, ...]
    db_path: str
    welcome_photo_path: str


def parse_admin_ids(*values: str) -> tuple[int, ...]:
    ids: list[int] = []
    for value in values:
        for chunk in value.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.lstrip("-").isdigit():
                ids.append(int(chunk))
    return tuple(dict.fromkeys(ids))


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    admin_chat_id_raw = os.getenv("ADMIN_CHAT_ID", "").strip()
    admin_chat_ids_raw = os.getenv("ADMIN_CHAT_IDS", "").strip()
    return Config(
        bot_token=token,
        admin_username=os.getenv("ADMIN_USERNAME", "").strip().lstrip("@"),
        admin_chat_ids=parse_admin_ids(admin_chat_id_raw, admin_chat_ids_raw),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        welcome_photo_path=os.getenv("WELCOME_PHOTO_PATH", "Фото приветствие.JPG"),
    )
