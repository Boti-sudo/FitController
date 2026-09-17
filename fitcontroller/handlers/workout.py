"""Ссылки на мини-аппы.

Результат тренировки приходит не сюда, а в HTTP API (fitcontroller/api.py):
мини-апп пишет в БД в момент нажатия «Начать», а не одним пакетом в конце.
"""

import time
from urllib.parse import urlencode

def cache_busted(page_url: str) -> str:
    """Добавляет к адресу страницы метку времени.

    Telegram кэширует страницу мини-аппа, и после выкладки новой версии
    в клиенте может остаться старая копия. Метка считается в момент сборки
    ссылки, а не при старте бота: каждое открытие папки даёт свежий адрес.
    Для продакшена сюда лучше подставить номер версии страницы.
    """
    separator = "&" if "?" in page_url else "?"
    return f"{page_url.rstrip('/')}/{separator}v={int(time.time())}"


def build_day_url(page_url: str, api_url: str, day_id: int) -> str:
    """Страница получает адрес API и номер дня, всё остальное забирает запросом.

    Параметры кладём в hash: он не уходит на сервер GitHub Pages и не оседает
    в его логах.
    """
    params = urlencode({"api": api_url.rstrip("/"), "day": day_id})
    return f"{cache_busted(page_url)}#{params}"


def build_stats_url(page_url: str, api_url: str) -> str:
    """Странице статистики нужен только адрес API — день она не открывает."""
    params = urlencode({"api": api_url.rstrip("/")})
    return f"{cache_busted(page_url)}#{params}"


def build_editor_url(page_url: str, api_url: str, day_id: int | None = None) -> str:
    """Адрес конструктора.

    Без day_id — создание: страница подтянет список папок, чтобы положить день
    в существующую. С day_id — правка: страница загрузит день и заполнит форму.
    """
    params = {"api": api_url.rstrip("/")}
    if day_id is not None:
        params["day"] = day_id
    return f"{cache_busted(page_url)}#{urlencode(params)}"
