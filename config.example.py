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

STATS_WEBAPP_URL = os.getenv("STATS_WEBAPP_URL", "")

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8081"))
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "")

# Напоминания о простое: местный сдвиг от UTC, дневное окно и период проверки.
REMINDER_TZ_OFFSET = int(os.getenv("REMINDER_TZ_OFFSET", "3"))
REMINDER_HOURS = (10, 20)
REMINDER_INTERVAL_MINUTES = int(os.getenv("REMINDER_INTERVAL_MINUTES", "30"))

# Через сколько часов напомнить о незакрытой тренировке.
FORGOTTEN_AFTER_HOURS = int(os.getenv("FORGOTTEN_AFTER_HOURS", "3"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set.")
