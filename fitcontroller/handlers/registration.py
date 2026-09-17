import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from fitcontroller.db import get_latest_body_weight, get_user, upsert_user
from fitcontroller.handlers.menu import send_main_menu
from config import REMINDER_TZ_OFFSET
from fitcontroller.db import GENDERS, GOALS
from fitcontroller.keyboards import genders_keyboard, goals_keyboard
from fitcontroller.states import Registration

logger = logging.getLogger(__name__)

router = Router(name="registration")

GREETING = (
    "Привет! Этот бот поможет тебе генерировать и отслеживать свои тренировки, "
    "свой прогресс а так же записывать веса предыдущих упражнение и записывать новые.\n\n"
    "Для начала расскажи немного о себе:"
)

AGE_RANGE = (10, 100)
HEIGHT_RANGE = (100, 250)
WEIGHT_RANGE = (30.0, 300.0)


def _parse_number(text: str) -> float | None:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


async def _ask_name(message: Message, state: FSMContext) -> None:
    await state.set_state(Registration.name)
    await message.answer("Как к тебе обращаться?", reply_markup=ReplyKeyboardRemove())


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = await get_user(message.from_user.id)
    if user:
        await message.answer(
            f"С возвращением, {user['name']}!",
            reply_markup=ReplyKeyboardRemove(),
        )
        await send_main_menu(message)
        return

    await message.answer(GREETING)
    await _ask_name(message, state)


@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Заполним анкету заново.")
    await _ask_name(message, state)


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Анкета ещё не заполнена. Нажми /start")
        return

    # Вес из анкеты быстро устаревает: если человек взвешивался на тренировке,
    # показываем последнее измерение, а не то, что он вписал при регистрации.
    latest = await get_latest_body_weight(message.from_user.id)
    await message.answer(_format_profile(user, latest))


@router.message(Registration.name, F.text)
async def process_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Напиши, как к тебе обращаться.")
        return
    if len(name) > 64:
        await message.answer("Слишком длинно. Напиши имя покороче — до 64 символов.")
        return

    await state.update_data(name=name)
    await state.set_state(Registration.gender)
    await message.answer(
        f"Приятно познакомиться, {name}!\n\nКакой у тебя пол?",
        reply_markup=genders_keyboard(),
    )


@router.callback_query(Registration.gender, F.data.startswith("gender:"))
async def process_gender(callback: CallbackQuery, state: FSMContext) -> None:
    gender_code = callback.data.split(":", 1)[1]
    if gender_code not in GENDERS:
        await callback.answer("Неизвестный вариант, выбери ещё раз.", show_alert=True)
        return

    await state.update_data(gender_code=gender_code)
    await state.set_state(Registration.age)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Сколько тебе лет?")
    await callback.answer()


@router.message(Registration.gender)
async def process_gender_as_text(message: Message) -> None:
    await message.answer("Выбери пол кнопкой под сообщением выше.")


@router.message(Registration.age, F.text)
async def process_age(message: Message, state: FSMContext) -> None:
    value = _parse_number(message.text)
    low, high = AGE_RANGE
    if value is None or not low <= value <= high or value != int(value):
        await message.answer(f"Введи возраст целым числом от {low} до {high}. Например: 27")
        return

    await state.update_data(age=int(value))
    await state.set_state(Registration.height)
    await message.answer("Какой у тебя рост? В сантиметрах, например: 180")


@router.message(Registration.height, F.text)
async def process_height(message: Message, state: FSMContext) -> None:
    value = _parse_number(message.text)
    low, high = HEIGHT_RANGE
    if value is None or not low <= value <= high:
        await message.answer(f"Введи рост в сантиметрах — число от {low} до {high}. Например: 180")
        return

    await state.update_data(height=int(value))
    await state.set_state(Registration.weight)
    await message.answer("Какой у тебя вес? В килограммах, например: 75.5")


@router.message(Registration.weight, F.text)
async def process_weight(message: Message, state: FSMContext) -> None:
    value = _parse_number(message.text)
    low, high = WEIGHT_RANGE
    if value is None or not low <= value <= high:
        await message.answer(f"Введи вес в килограммах — число от {low:g} до {high:g}. Например: 75.5")
        return

    await state.update_data(weight=round(value, 1))
    await state.set_state(Registration.goal)
    await message.answer("Какая цель?", reply_markup=goals_keyboard())


@router.callback_query(Registration.goal, F.data.startswith("goal:"))
async def process_goal(callback: CallbackQuery, state: FSMContext) -> None:
    goal_code = callback.data.split(":", 1)[1]
    if goal_code not in GOALS:
        await callback.answer("Неизвестная цель, выбери ещё раз.", show_alert=True)
        return

    data = await state.get_data()
    await upsert_user(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        name=data["name"],
        gender_code=data["gender_code"],
        age=data["age"],
        height_cm=data["height"],
        weight_kg=data["weight"],
        goal_code=goal_code,
    )
    await state.clear()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Готово, анкета сохранена!\n\n"
        + _format_profile(
            {
                "name": data["name"],
                "gender": GENDERS[data["gender_code"]],
                "age": data["age"],
                "height_cm": data["height"],
                "weight_kg": data["weight"],
                "goal": GOALS[goal_code],
            }
        )
    )
    await send_main_menu(callback.message)
    await callback.answer()


@router.message(Registration.goal)
async def process_goal_as_text(message: Message) -> None:
    await message.answer("Выбери цель кнопкой под сообщением выше.")


@router.message(StateFilter(Registration))
async def process_unexpected(message: Message) -> None:
    await message.answer("Ответь, пожалуйста, текстом.")


def _weight_line(user: dict, latest: dict | None) -> str:
    if not latest:
        return f"Вес: {user['weight_kg']:g} кг (из анкеты)"

    # Даты в базе в UTC — переводим в местные, иначе вечерняя тренировка
    # покажется вчерашней.
    measured = datetime.strptime(latest["finished_at"], "%Y-%m-%d %H:%M:%S")
    measured += timedelta(hours=REMINDER_TZ_OFFSET)
    return f"Вес: {latest['body_weight_kg']:g} кг (взвешивание {measured:%d.%m.%Y})"


def _format_profile(user: dict, latest: dict | None = None) -> str:
    return (
        f"Имя: {user['name']}\n"
        f"Пол: {user['gender'] or '—'}\n"
        f"Возраст: {user['age']}\n"
        f"Рост: {user['height_cm']} см\n"
        f"{_weight_line(user, latest)}\n"
        f"Цель: {user['goal']}"
    )
