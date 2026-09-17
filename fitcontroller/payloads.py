"""Разбор данных, присланных конструктором тренировок.

Клиенту доверять нельзя: страница живёт на чужом домене, её версия может
быть старой из кэша Telegram. Поэтому типы, длины и диапазоны проверяются
здесь, а не на странице.
"""

import json


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
            # Группа мышц необязательна: пустую просто не записываем.
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


def parse_edit_payload(raw: str) -> tuple[int, str, list[dict]]:
    """Разбирает правку одного дня: (day_id, название дня, упражнения)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise PayloadError("не удалось разобрать данные") from err

    if not isinstance(data, dict):
        raise PayloadError("ожидался объект")

    day_id = data.get("id")
    if not isinstance(day_id, int) or isinstance(day_id, bool):
        raise PayloadError("не указан тренировочный день")

    day_title = _text(data.get("n"), "название дня", MAX_TITLE)

    raw_exercises = data.get("e")
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

    return day_id, day_title, exercises
