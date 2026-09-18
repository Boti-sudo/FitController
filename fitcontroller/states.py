from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    """Шаги анкеты, которую пользователь заполняет после /start."""

    name = State()
    gender = State()
    age = State()
    height = State()
    weight = State()
    goal = State()


class RenameWorkout(StatesGroup):
    """Ввод нового названия комплекса."""

    title = State()
