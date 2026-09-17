import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    """Читает KEY=VALUE из .env в переменные окружения.

    Отдельная библиотека ради десяти строк не нужна. Уже заданную переменную
    не трогаем: то, что передано при запуске, важнее файла.
    """
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")

# Секрет в коде не держим: он живёт в .env (файл в .gitignore) или в окружении.
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
