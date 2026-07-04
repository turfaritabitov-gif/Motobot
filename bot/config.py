from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_username: str
    admin_chat_id: int | None
    db_path: str
    welcome_photo_path: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    admin_chat_id_raw = os.getenv("ADMIN_CHAT_ID", "").strip()
    admin_chat_id = int(admin_chat_id_raw) if admin_chat_id_raw.isdigit() else None
    return Config(
        bot_token=token,
        admin_username=os.getenv("ADMIN_USERNAME", "").strip().lstrip("@"),
        admin_chat_id=admin_chat_id,
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        welcome_photo_path=os.getenv("WELCOME_PHOTO_PATH", "Фото приветствие.JPG"),
    )
