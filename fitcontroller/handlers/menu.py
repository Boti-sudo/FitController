"""Главное меню и навигация по разделам: тренировки, создание, статистика, архив."""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import API_PUBLIC_URL, STATS_WEBAPP_URL, WEBAPP_URL, WORKOUT_WEBAPP_URL
from fitcontroller.db import (
    delete_workout,
    get_workout,
    list_open_sessions,
    list_workouts,
    rename_workout,
    set_archived,
)
from fitcontroller.states import RenameWorkout
from fitcontroller.keyboards import (
    archive_keyboard,
    back_keyboard,
    confirm_delete_keyboard,
    create_keyboard,
    main_menu_keyboard,
    manual_keyboard,
    edit_days_keyboard,
    editor_keyboard,
    pick_keyboard,
    stats_keyboard,
    support_keyboard,
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


@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    await message.answer(
        "Если что-то не работает или есть вопрос — напиши, разберёмся.",
        reply_markup=support_keyboard(),
    )


async def send_main_menu(message: Message) -> None:
    """Новое сообщение с меню — для случаев, когда редактировать нечего."""
    await message.answer(MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())


def _format_exercise(exercise: dict) -> str:
    """Список в чате — только состав дня. Подходы и повторения показывает мини-апп."""
    line = f"{exercise['position']}. {exercise['name']}"
    if exercise["muscle_group"]:
        line += f" ({exercise['muscle_group']})"
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


async def _open_sessions(user_id: int, workout_id: int | None = None) -> list[tuple[str, str]]:
    """Незакрытые тренировки как пары (подпись, адрес мини-аппа).

    Пусто, если адреса мини-аппа или сервера нет: кнопка вела бы в никуда.
    """
    if not (WORKOUT_WEBAPP_URL and API_PUBLIC_URL):
        return []

    from fitcontroller.handlers.workout import build_day_url

    sessions = await list_open_sessions(user_id)
    if workout_id is not None:
        sessions = [row for row in sessions if row["workout_id"] == workout_id]

    return [
        (
            row["day_title"] if workout_id is not None
            else f"{row['workout_title']} / {row['day_title']}",
            build_day_url(WORKOUT_WEBAPP_URL, API_PUBLIC_URL, row["day_id"]),
        )
        for row in sessions
    ]


async def _show_workouts(callback: CallbackQuery) -> None:
    workouts = await list_workouts(callback.from_user.id)
    resume = await _open_sessions(callback.from_user.id)
    text = "Твои программы:" if workouts else NO_WORKOUTS_TEXT
    await _render(callback, text, workouts_keyboard(workouts, resume))


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
    # Незакрытая тренировка — хоть в этой папке, хоть в соседней — перекрывает
    # выбор дня: сначала её надо завершить.
    resume = await _open_sessions(callback.from_user.id)
    if resume:
        text = (
            f"{_format_workout(workout)}\n\n"
            "У тебя есть незавершённая тренировка. Заверши её, "
            "прежде чем начинать новую."
        )
        await _render(callback, text, workout_days_keyboard([], back_to, resume))
        return

    text = f"{_format_workout(workout)}\n\nВыбери тренировочный день:"
    await _render(
        callback,
        text,
        workout_days_keyboard(days, back_to, workout_id=workout["workout_id"]),
    )


MAX_TITLE = 64


@router.callback_query(F.data.startswith("wk:rename:"))
async def ask_new_title(callback: CallbackQuery, state: FSMContext) -> None:
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    await state.set_state(RenameWorkout.title)
    await state.update_data(workout_id=workout_id)
    await callback.message.answer(
        f"Впиши новое название для «{workout['title']}».\n"
        "Чтобы передумать — /cancel"
    )
    await callback.answer()


@router.message(RenameWorkout.title, Command("cancel"))
async def cancel_rename(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Название оставил как было.")
    await send_main_menu(message)


@router.message(RenameWorkout.title, F.text)
async def apply_new_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not title:
        await message.answer("Название не может быть пустым. Впиши ещё раз.")
        return
    if len(title) > MAX_TITLE:
        await message.answer(f"Слишком длинно — до {MAX_TITLE} символов. Впиши покороче.")
        return

    data = await state.get_data()
    workout_id = data["workout_id"]

    renamed = await rename_workout(workout_id, message.from_user.id, title)
    if not renamed:
        # Либо занято другой папкой, либо программы уже нет — обе причины
        # разбираются одним запросом.
        workout = await get_workout(workout_id, message.from_user.id)
        if workout is None:
            await state.clear()
            await message.answer("Программа не найдена.")
            await send_main_menu(message)
            return
        await message.answer(
            f"Комплекс с названием «{title}» уже есть. Впиши другое."
        )
        return

    await state.clear()
    await message.answer(f"Готово, теперь это «{title}».")

    workout = await get_workout(workout_id, message.from_user.id)
    await message.answer(_format_workout(workout))
    await send_main_menu(message)


@router.message(RenameWorkout.title)
async def rename_wrong_type(message: Message) -> None:
    await message.answer("Пришли новое название текстом или отмени через /cancel")


@router.callback_query(F.data.startswith("wk:add:"))
async def add_day_to_workout(callback: CallbackQuery) -> None:
    """Конструктор с уже подставленной папкой — день ляжет именно в неё."""
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    if not (WEBAPP_URL and API_PUBLIC_URL):
        await callback.answer(
            "Конструктор недоступен: не задан адрес мини-аппа или сервера.", show_alert=True
        )
        return

    from fitcontroller.handlers.workout import build_editor_url

    url = build_editor_url(WEBAPP_URL, API_PUBLIC_URL, workout_id=workout_id)
    await _render(
        callback,
        f"➕ Новый день в «{workout['title']}»\n\n"
        "Название комплекса подставится само, при желании его можно поменять.",
        editor_keyboard(url, f"wk:open:{workout_id}"),
    )


@router.callback_query(F.data.startswith("wk:days:"))
async def choose_day_to_edit(callback: CallbackQuery) -> None:
    """Список дней папки на reply-клавиатуре: только оттуда работает sendData."""
    workout_id = int(callback.data.rsplit(":", 1)[1])
    workout = await get_workout(workout_id, callback.from_user.id)
    if workout is None:
        await callback.answer("Программа не найдена.", show_alert=True)
        return

    if not (WEBAPP_URL and API_PUBLIC_URL):
        await callback.answer(
            "Редактор недоступен: не задан адрес мини-аппа или сервера.", show_alert=True
        )
        return

    if not workout["days"]:
        await callback.answer("В этой программе пока нет дней.", show_alert=True)
        return

    from fitcontroller.handlers.workout import build_editor_url

    days = [
        (day["title"], build_editor_url(WEBAPP_URL, API_PUBLIC_URL, day["day_id"]))
        for day in workout["days"]
    ]
    await _render(
        callback,
        f"✏️ «{workout['title']}» — выбери день, который правим:",
        edit_days_keyboard(days, f"wk:open:{workout_id}"),
    )


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
    if not (WEBAPP_URL and API_PUBLIC_URL):
        await _render(
            callback,
            "✍️ Редактор тренировки\n\n"
            "Не задан адрес мини-аппа или сервера — пропиши WEBAPP_URL "
            "и API_PUBLIC_URL в config.py.",
            back_keyboard("create:manual"),
        )
        return

    from fitcontroller.handlers.workout import build_editor_url

    await _render(
        callback,
        "✍️ Конструктор тренировки\n\n"
        "Заполни день и сохрани — тренировка появится в «Моих тренировках».",
        editor_keyboard(build_editor_url(WEBAPP_URL, API_PUBLIC_URL), "create:manual"),
    )
