# Telegram bot for moto walks in Kazan

## Local run

1. Copy `.env.example` to `.env` and fill `BOT_TOKEN`.
2. Install dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

3. Start the bot:

```bash
.venv/bin/python -m bot.main
```

The first user with `ADMIN_USERNAME` who sends `/start` becomes admin and their chat id is saved to settings.
Additional admins can be listed in `ADMIN_CHAT_IDS` as comma-separated Telegram IDs. Each admin must send `/start` to the bot once before the bot can message them.

## VPS deployment

The bot runs with long polling, so a domain and HTTPS certificate are not required for the MVP.

```bash
sudo mkdir -p /opt/motobot
sudo cp -r bot data deploy requirements.txt "Фото приветствие.JPG" .env /opt/motobot/
cd /opt/motobot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp deploy/motobot.service /etc/systemd/system/motobot.service
sudo systemctl daemon-reload
sudo systemctl enable --now motobot
sudo systemctl status motobot
```
