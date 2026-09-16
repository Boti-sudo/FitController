"""Настройка логирования: в консоль и в файл с ротацией."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    """Один и тот же поток событий уходит и на экран, и в файл.

    encoding="utf-8" обязателен: по умолчанию на Windows файл пишется
    в cp1251, и кириллица в сообщениях роняет запись.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    # aiohttp по умолчанию молчит про запросы — включаем собственный access-лог.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
