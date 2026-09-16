"""Клавиатуры и подписи кнопок — отдельно от логики хендлеров."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from fitcontroller.db import GENDERS, GOALS

BTN_BACK = "⬅️ Назад"


def genders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label, callback_data=f"gender:{code}")
                for code, label in GENDERS.items()
            ]
        ]
    )


def goals_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"goal:{code}")]
            for code, label in GOALS.items()
        ]
    )


def _back(target: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=BTN_BACK, callback_data=target)]


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏋️ Мои тренировки", callback_data="menu:workouts")],
            [InlineKeyboardButton(text="➕ Создать тренировку", callback_data="menu:create")],
            [InlineKeyboardButton(text="📊 Посмотреть статистику", callback_data="menu:stats")],
            [InlineKeyboardButton(text="🗄 Архив", callback_data="menu:archive")],
        ]
    )


def workouts_keyboard(workouts: list[dict]) -> InlineKeyboardMarkup:
    """Папки с программами + действия, которые доступны всегда."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"📁 {workout['title']}",
                callback_data=f"wk:open:{workout['workout_id']}",
            )
        ]
        for workout in workouts
    ]
    rows += [
        [InlineKeyboardButton(text="➕ Создать новую тренировку", callback_data="menu:create")],
        [InlineKeyboardButton(text="🗄 Добавить в архив", callback_data="wk:archive_list")],
        _back("menu:main"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_keyboard(workouts: list[dict], action: str, back_to: str) -> InlineKeyboardMarkup:
    """Выбор программы под действие: archive, restore или delete."""
    rows = [
        [
            InlineKeyboardButton(
                text=workout["title"],
                callback_data=f"wk:{action}:{workout['workout_id']}",
            )
        ]
        for workout in workouts
    ]
    rows.append(_back(back_to))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def archive_keyboard(workouts: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"📁 {workout['title']}",
                callback_data=f"wk:open:{workout['workout_id']}",
            )
        ]
        for workout in workouts
    ]
    rows += [
        [InlineKeyboardButton(text="♻️ Восстановить из архива", callback_data="wk:restore_list")],
        [InlineKeyboardButton(text="🗑 Удалить из архива", callback_data="wk:delete_list")],
        _back("menu:main"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Сгенерировать через ИИ", callback_data="create:ai")],
            [InlineKeyboardButton(text="✍️ Создать самому", callback_data="create:manual")],
            _back("menu:main"),
        ]
    )


def manual_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📷 Добавить фото", callback_data="create:photo")],
            [InlineKeyboardButton(text="✍️ Создать самому", callback_data="create:miniapp")],
            _back("menu:create"),
        ]
    )


def workout_days_keyboard(days: list[tuple[str, str]], back_to: str) -> InlineKeyboardMarkup:
    """Кнопка на каждый тренировочный день: (название, адрес мини-аппа).

    Инлайн, а не reply-клавиатура: мини-апп тренировки общается с ботом
    по HTTP, sendData ему не нужен, а инлайн-кнопки ничего не оставляют
    висеть внизу экрана.
    """
    rows = [
        [InlineKeyboardButton(text=f"▶️ {title}", web_app=WebAppInfo(url=url))]
        for title, url in days
    ]
    rows.append(_back(back_to))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_keyboard(workout_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"wk:delok:{workout_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data="wk:delete_list")],
        ]
    )


def webapp_keyboard(url: str) -> ReplyKeyboardMarkup:
    """Запуск мини-аппа.

    Именно reply-кнопка, а не инлайн: WebApp.sendData() работает только
    для приложений, открытых с клавиатурной кнопки. С инлайн-кнопки
    страница откроется, но вернуть данные боту без своего сервера не сможет.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✍️ Начать заполнение", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def back_keyboard(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[_back(target)])
