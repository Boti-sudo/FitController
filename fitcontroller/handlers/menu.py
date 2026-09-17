"""Главное меню и навигация по разделам: тренировки, создание, статистика, архив."""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from config import API_PUBLIC_URL, STATS_WEBAPP_URL, WEBAPP_URL, WORKOUT_WEBAPP_URL
from fitcontroller.db import delete_workout, get_workout, list_workouts, set_archived
from fitcontroller.keyboards import (
    archive_keyboard,
    back_keyboard,
    confirm_delete_keyboard,
    create_keyboard,
    main_menu_keyboard,
    manual_keyboard,
    pick_keyboard,
    stats_keyboard,
    webapp_keyboard,
    workout_days_keyboard,
    workouts_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="menu")

MAIN_MENU_TEXT = "Главное меню — выбери раздел:"

NO_WORKOUTS_TEXT = (
    "Пока активных программ нет, ты можешь ее добавить "
    "самостоятельно или сгенерировать при помощи нашего бота."
)

CREATE_TEXT = (
    "Здесь создаются тренировки. Ты можешь:\n"
    "— Самостоятельно ввести текстом свою тренировку\n"
    "— Собрать тренировку по фото, используя нашу систему распознавания текста\n"
    "— Сгенерировать индивидуальную тренировку при помощи специально настроенного ИИ"
)

MANUAL_TEXT = (
    "Тут ты можешь либо полностью написать программу сам, либо, если у тебя есть "
    "какой-то скриншот с уже существующей программой, ты можешь загрузить его сюда — "
    "наш бот превратит его в текст и внесёт в программу тренировок, "
    "где ты сможешь отредактировать любое упражнение."
)

SOON_TEXT = "Раздел в разработке — скоро заработает."


async def send_main_menu(message: Message) -> None:
    """Новое сообщение с меню — для случаев, когда редактировать нечего."""
    await message.answer(MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())


def _format_exercise(exercise: dict) -> str:
    line = f"{exercise['position']}. {exercise['name']}"
    if exercise["muscle_group"]:
        line += f" ({exercise['muscle_group']})"
    if exercise["sets"]:
        reps = ", ".join(str(item["reps"]) for item in exercise["sets"])
        line += f" — {len(exercise['sets'])}×[{reps}]"
    return line


def _format_day(day: dict) -> str:
    lines = [f"🗓 {day['position']}. {day['title']}"]
    if day["exercises"]:
        lines += [f"   {_format_exercise(exercise)}" for exercise in day["exercises"]]
    else:
        lines.append("   Упражнений пока нет.")
    return "\n".join(lines)


def _format_workout(workout: dict) -> str:
    header = f"📁 {workout['title']}\n{workout['source']}"
    if not workout["days"]:
        return f"{header}\n\nВ комплексе пока нет тренировочных дней."

    body = "\n\n".join(_format_day(day) for day in workout["days"])
    return f"{header}\n\n{body}"


async def _render(callback: CallbackQuery, text: str, keyboard) -> None:
    """Перерисовываем то же сообщение вместо того, чтобы плодить новые."""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as err:
        # Повторный тап по той же кнопке — Telegram ругается, что менять нечего.
        if "message is not modified" not in str(err):
            raise
    await callback.answer()


@router.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery) -> None:
    await _render(callback, MAIN_MENU_TEXT, main_menu_keyboard())


async def _show_workouts(callback: CallbackQuery) -> None:
    workouts = await list_workouts(callback.from_user.id)
    text = "Твои программы:" if workouts else NO_WORKOUTS_TEXT
    await _render(callback, text, workouts_keyboard(workouts))


async def _show_archive(callback: CallbackQuery) -> None:
    workouts = await list_workouts(callback.from_user.id, archived=True)
    text = "Архив:" if workouts else "Архив пуст."
    await _render(callback, text, archive_keyboard(workouts))


@router.callback_query(F.data == "menu:workouts")
async def show_workouts(callback: CallbackQuery) -> None:
    await _show_workouts(callback)


@router.callback_query(F.data.startswith("wk:open:"))
async def open_workout(callback: CallbackQuery) -> None:
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    back_to = "menu:archive" if workout["is_archived"] else "menu:workouts"

    # Архивные не тренируем, и без адресов мини-аппа и сервера кнопки бессмысленны.
    trainable = (
        not workout["is_archived"]
        and workout["days"]
        and WORKOUT_WEBAPP_URL
        and API_PUBLIC_URL
    )
    if not trainable:
        await _render(callback, _format_workout(workout), back_keyboard(back_to))
        return

    from fitcontroller.handlers.workout import build_day_url

    days = [
        (day["title"], build_day_url(WORKOUT_WEBAPP_URL, API_PUBLIC_URL, day["day_id"]))
        for day in workout["days"]
    ]
    logger.info(
        "user_id=%s открыл workout_id=%s, ссылок на дни: %s, первая: %s",
        callback.from_user.id,
        workout["workout_id"],
        len(days),
        days[0][1],
    )
    text = f"{_format_workout(workout)}\n\nВыбери тренировочный день:"
    await _render(callback, text, workout_days_keyboard(days, back_to))


@router.callback_query(F.data == "wk:archive_list")
async def choose_to_archive(callback: CallbackQuery) -> None:
    workouts = await list_workouts(callback.from_user.id)
    text = (
        "Выбери программу, которую отправить в архив:"
        if workouts
        else "Активных программ нет — архивировать нечего."
    )
    await _render(callback, text, pick_keyboard(workouts, "archive", "menu:workouts"))


@router.callback_query(F.data == "wk:restore_list")
async def choose_to_restore(callback: CallbackQuery) -> None:
    workouts = await list_workouts(callback.from_user.id, archived=True)
    text = (
        "Выбери программу, которую вернуть из архива:"
        if workouts
        else "Архив пуст — восстанавливать нечего."
    )
    await _render(callback, text, pick_keyboard(workouts, "restore", "menu:archive"))


@router.callback_query(F.data == "wk:delete_list")
async def choose_to_delete(callback: CallbackQuery) -> None:
    workouts = await list_workouts(callback.from_user.id, archived=True)
    text = (
        "Выбери программу, которую удалить навсегда:"
        if workouts
        else "Архив пуст — удалять нечего."
    )
    await _render(callback, text, pick_keyboard(workouts, "delete", "menu:archive"))


@router.callback_query(F.data.startswith("wk:archive:"))
async def archive_workout(callback: CallbackQuery) -> None:
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    await set_archived(workout_id, callback.from_user.id, True)
    await callback.answer(f"«{workout['title']}» в архиве")
    await _show_workouts(callback)


@router.callback_query(F.data.startswith("wk:restore:"))
async def restore_workout(callback: CallbackQuery) -> None:
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    await set_archived(workout_id, callback.from_user.id, False)
    await callback.answer(f"«{workout['title']}» снова в активных")
    await _show_archive(callback)


@router.callback_query(F.data.startswith("wk:delete:"))
async def confirm_delete(callback: CallbackQuery) -> None:
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    count = sum(len(day["exercises"]) for day in workout["days"])
    text = (
        f"Удалить «{workout['title']}» навсегда?\n\n"
        f"Вместе с программой удалятся все её упражнения ({count}). "
        "Восстановить будет нельзя."
    )
    await _render(callback, text, confirm_delete_keyboard(workout_id))


@router.callback_query(F.data.startswith("wk:delok:"))
async def remove_workout(callback: CallbackQuery) -> None:
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    await delete_workout(workout_id, callback.from_user.id)
    await callback.answer(f"«{workout['title']}» удалена", show_alert=True)
    await _show_archive(callback)


@router.callback_query(F.data == "menu:archive")
async def show_archive(callback: CallbackQuery) -> None:
    await _show_archive(callback)


@router.callback_query(F.data == "menu:create")
async def show_create(callback: CallbackQuery) -> None:
    await _render(callback, CREATE_TEXT, create_keyboard())


@router.callback_query(F.data == "create:manual")
async def show_manual(callback: CallbackQuery) -> None:
    await _render(callback, MANUAL_TEXT, manual_keyboard())


@router.callback_query(F.data == "menu:stats")
async def show_stats(callback: CallbackQuery) -> None:
    # Без адресов страницы и сервера кнопка открыла бы пустоту — как и у тренировок.
    if not (STATS_WEBAPP_URL and API_PUBLIC_URL):
        await _render(
            callback,
            "📊 Статистика\n\n"
            "Адрес мини-аппа или сервера не задан — "
            "пропиши STATS_WEBAPP_URL и API_PUBLIC_URL в config.py.",
            back_keyboard("menu:main"),
        )
        return

    from fitcontroller.handlers.workout import build_stats_url

    url = build_stats_url(STATS_WEBAPP_URL, API_PUBLIC_URL)
    logger.info("user_id=%s открыл статистику", callback.from_user.id)
    await _render(
        callback,
        "📊 Статистика\n\n"
        "Прогресс веса и список тренировок — в мини-аппе.",
        stats_keyboard(url, "menu:main"),
    )


@router.callback_query(F.data == "create:ai")
async def stub_ai(callback: CallbackQuery) -> None:
    await _render(
        callback,
        f"🤖 Генерация через ИИ\n\n{SOON_TEXT}",
        back_keyboard("menu:create"),
    )


@router.callback_query(F.data == "create:photo")
async def stub_photo(callback: CallbackQuery) -> None:
    await _render(
        callback,
        f"📷 Сборка тренировки по фото\n\n{SOON_TEXT}",
        back_keyboard("create:manual"),
    )


@router.callback_query(F.data == "create:miniapp")
async def open_editor(callback: CallbackQuery) -> None:
    if not WEBAPP_URL:
        await _render(
            callback,
            "✍️ Редактор тренировки\n\n"
            "Адрес мини-аппа не задан — пропиши WEBAPP_URL в config.py.",
            back_keyboard("create:manual"),
        )
        return

    from fitcontroller.handlers.workout import cache_busted

    await callback.message.answer(
        "Жми «Начать заполнение» под полем ввода — заполнишь тренировку "
        "и она сама прилетит сюда.",
        reply_markup=webapp_keyboard(cache_busted(WEBAPP_URL)),
    )
    await callback.answer()
