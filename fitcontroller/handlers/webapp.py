"""Приём данных из мини-аппа: разбор payload и сохранение тренировочных дней."""

import json
import logging

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove

from fitcontroller.db import SOURCE_USER, save_training_day

logger = logging.getLogger(__name__)

router = Router(name="webapp")

MAX_TITLE = 64
MAX_MUSCLE = 64
MAX_DAYS = 20
MAX_EXERCISES = 50
MAX_SETS = 30


class PayloadError(ValueError):
    """Мини-апп прислал что-то, чего мы не ждали."""


def _text(value, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"поле «{field}» пустое")
    text = value.strip()
    if len(text) > limit:
        raise PayloadError(f"поле «{field}» длиннее {limit} символов")
    return text


def _reps(value, exercise: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise PayloadError(f"в упражнении «{exercise}» нет подходов")
    if len(value) > MAX_SETS:
        raise PayloadError(f"в упражнении «{exercise}» больше {MAX_SETS} подходов")

    reps = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 999:
            raise PayloadError(f"в упражнении «{exercise}» неверное число повторений")
        reps.append(item)
    return reps


def parse_payload(raw: str) -> tuple[str, list[dict]]:
    """Разбирает JSON из мини-аппа в (название комплекса, список дней).

    Данные приходят от клиента, поэтому проверяем всё: типы, длины, диапазоны.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise PayloadError("не удалось разобрать данные") from err

    if not isinstance(data, dict):
        raise PayloadError("ожидался объект")

    workout_title = _text(data.get("t"), "название комплекса", MAX_TITLE)

    raw_days = data.get("d")
    if not isinstance(raw_days, list) or not raw_days:
        raise PayloadError("не пришло ни одного тренировочного дня")
    if len(raw_days) > MAX_DAYS:
        raise PayloadError(f"больше {MAX_DAYS} дней за раз не сохраняем")

    days = []
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            raise PayloadError("день пришёл не объектом")

        day_title = _text(raw_day.get("n"), "название дня", MAX_TITLE)

        raw_exercises = raw_day.get("e")
        if not isinstance(raw_exercises, list) or not raw_exercises:
            raise PayloadError(f"в дне «{day_title}» нет упражнений")
        if len(raw_exercises) > MAX_EXERCISES:
            raise PayloadError(f"в дне «{day_title}» больше {MAX_EXERCISES} упражнений")

        exercises = []
        for raw_exercise in raw_exercises:
            if not isinstance(raw_exercise, dict):
                raise PayloadError("упражнение пришло не объектом")

            name = _text(raw_exercise.get("n"), "название упражнения", MAX_TITLE)
            muscle = raw_exercise.get("m")
            exercises.append(
                {
                    "name": name,
                    "muscle_group": _text(muscle, "группа мышц", MAX_MUSCLE) if muscle else None,
                    "sets": _reps(raw_exercise.get("s"), name),
                }
            )

        days.append({"title": day_title, "exercises": exercises})

    return workout_title, days


def _summary(workout_title: str, days: list[dict]) -> str:
    lines = [f"Сохранено в «{workout_title}»:", ""]
    for day in days:
        sets_total = sum(len(exercise["sets"]) for exercise in day["exercises"])
        lines.append(
            f"• {day['title']} — упражнений: {len(day['exercises'])}, подходов: {sets_total}"
        )
    return "\n".join(lines)


def is_new_workout(message: Message) -> bool:
    """Payload из редактора создания: помечен k="new" (или без метки — старая версия)."""
    try:
        data = json.loads(message.web_app_data.data)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(data, dict) and data.get("k", "new") == "new"


@router.message(F.web_app_data, is_new_workout)
async def receive_webapp_data(message: Message) -> None:
    try:
        workout_title, days = parse_payload(message.web_app_data.data)
    except PayloadError as err:
        logger.warning("Bad web app payload from user_id=%s: %s", message.from_user.id, err)
        await message.answer(
            f"Не смог сохранить тренировку: {err}.\nПопробуй ещё раз.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    for day in days:
        await save_training_day(
            user_id=message.from_user.id,
            workout_title=workout_title,
            day_title=day["title"],
            exercises=day["exercises"],
            source_code=SOURCE_USER,
        )

    await message.answer(_summary(workout_title, days), reply_markup=ReplyKeyboardRemove())

    from fitcontroller.handlers.menu import send_main_menu

    await send_main_menu(message)
