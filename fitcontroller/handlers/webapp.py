"""Приём данных из мини-аппа: разбор payload и сохранение тренировочных дней."""

import json
import logging

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove

from fitcontroller.db import SOURCE_USER, save_training_day, update_training_day
from fitcontroller.payloads import PayloadError, parse_edit_payload, parse_payload

logger = logging.getLogger(__name__)

router = Router(name="webapp")

def _summary(workout_title: str, days: list[dict]) -> str:
    lines = [f"Сохранено в «{workout_title}»:", ""]
    for day in days:
        sets_total = sum(len(exercise["sets"]) for exercise in day["exercises"])
        lines.append(
            f"• {day['title']} — упражнений: {len(day['exercises'])}, подходов: {sets_total}"
        )
    return "\n".join(lines)


def is_edited_day(message: Message) -> bool:
    """Payload из редактора существующего дня: помечен k="edit"."""
    try:
        data = json.loads(message.web_app_data.data)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(data, dict) and data.get("k") == "edit"


def is_new_workout(message: Message) -> bool:
    """Payload из редактора создания: помечен k="new" (или без метки — старая версия)."""
    try:
        data = json.loads(message.web_app_data.data)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(data, dict) and data.get("k", "new") == "new"


@router.message(F.web_app_data, is_edited_day)
async def receive_edited_day(message: Message) -> None:
    try:
        day_id, day_title, exercises = parse_edit_payload(message.web_app_data.data)
    except PayloadError as err:
        logger.warning("Bad edit payload from user_id=%s: %s", message.from_user.id, err)
        await message.answer(
            f"Не смог сохранить изменения: {err}.\nПопробуй ещё раз.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    try:
        await update_training_day(
            user_id=message.from_user.id,
            day_id=day_id,
            day_title=day_title,
            exercises=exercises,
        )
    except PermissionError:
        await message.answer(
            "Этот тренировочный день не найден.", reply_markup=ReplyKeyboardRemove()
        )
        return

    sets_total = sum(len(exercise["sets"]) for exercise in exercises)
    await message.answer(
        f"Изменения сохранены: «{day_title}» — упражнений: {len(exercises)}, "
        f"подходов: {sets_total}",
        reply_markup=ReplyKeyboardRemove(),
    )

    from fitcontroller.handlers.menu import send_main_menu

    await send_main_menu(message)


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
