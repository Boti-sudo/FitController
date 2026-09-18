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
    # Слеш дописываем только там, где параметров ещё не было: в адресе с query
    # он влез бы внутрь последнего значения (…?theme=dark/&v=…).
    if "?" in page_url:
        return f"{page_url}&v={int(time.time())}"
    return f"{page_url.rstrip('/')}/?v={int(time.time())}"


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


def build_editor_url(
    page_url: str,
    api_url: str,
    day_id: int | None = None,
    workout_id: int | None = None,
) -> str:
    """Адрес конструктора.

    Без параметров — создание с нуля: страница подтянет список папок.
    С workout_id — создание внутри конкретной папки: её название подставится
    в поле, но остаётся редактируемым. С day_id — правка существующего дня.
    """
    params = {"api": api_url.rstrip("/")}
    if day_id is not None:
        params["day"] = day_id
    if workout_id is not None:
        params["wk"] = workout_id

    # Не в хеш, как у мини-аппа тренировки: конструктор открывается кнопкой
    # клавиатуры, а ей Telegram фрагмент не передаёт — страница получала пустые
    # параметры и молча работала как обычное создание.
    return f"{cache_busted(page_url)}&{urlencode(params)}"
