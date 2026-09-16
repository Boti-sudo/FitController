import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

DB_PATH = BASE_DIR / "fitcontroller.db"

LOG_FILE = BASE_DIR / "logs" / "bot.log"

# Публичные HTTPS-адреса страниц из webapp/ и webapp_workout/.
# Пусто — соответствующий мини-апп выключен.
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
WORKOUT_WEBAPP_URL = os.getenv("WORKOUT_WEBAPP_URL", "")

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8081"))
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set.")
