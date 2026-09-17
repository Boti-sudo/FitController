"""Схема БД и справочные значения — единственный источник правды по структуре."""

# Справочники. Код — то, что лежит в БД и в callback_data; подпись — то, что видит юзер.
GENDERS = {
    "male": "Мужской",
    "female": "Женский",
}

GOALS = {
    "muscle": "Набрать мышечную массу",
    "loss": "Похудеть",
    "recomp": "Сушка / рельеф",
    "strength": "Увеличить силу",
    "endurance": "Повысить выносливость",
    "maintain": "Поддерживать форму",
}

SOURCE_AI = "ai"
SOURCE_USER = "user"

SOURCES = {
    SOURCE_AI: "Сгенерирована ботом",
    SOURCE_USER: "Загружена пользователем",
}

CREATE_GENDERS = """
CREATE TABLE IF NOT EXISTS genders (
    code  TEXT PRIMARY KEY,
    label TEXT NOT NULL
)
"""

CREATE_GOALS = """
CREATE TABLE IF NOT EXISTS goals (
    code  TEXT PRIMARY KEY,
    label TEXT NOT NULL
)
"""

CREATE_WORKOUT_SOURCES = """
CREATE TABLE IF NOT EXISTS workout_sources (
    code  TEXT PRIMARY KEY,
    label TEXT NOT NULL
)
"""

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    name        TEXT    NOT NULL,
    gender_code TEXT    NOT NULL REFERENCES genders(code),
    age         INTEGER NOT NULL,
    height_cm   INTEGER NOT NULL,
    weight_kg   REAL    NOT NULL,
    goal_code   TEXT    NOT NULL REFERENCES goals(code),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

# Комплекс целиком — то, что показывается папкой в «Моих тренировках».
CREATE_WORKOUTS = """
CREATE TABLE IF NOT EXISTS workouts (
    workout_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    source_code TEXT    NOT NULL REFERENCES workout_sources(code),
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, title)
)
"""

# Тренировочный день (цикл) внутри комплекса: «День ног», «Первый день».
CREATE_WORKOUT_DAYS = """
CREATE TABLE IF NOT EXISTS workout_days (
    day_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id  INTEGER NOT NULL REFERENCES workouts(workout_id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at  TEXT,
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (workout_id, position)
)
"""

CREATE_EXERCISES = """
CREATE TABLE IF NOT EXISTS exercises (
    exercise_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id       INTEGER NOT NULL REFERENCES workout_days(day_id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    muscle_group TEXT,
    UNIQUE (day_id, position)
)
"""

# Подход — отдельная строка: в одном поле их держать нельзя, это не атомарное значение.
CREATE_EXERCISE_SETS = """
CREATE TABLE IF NOT EXISTS exercise_sets (
    set_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER NOT NULL REFERENCES exercises(exercise_id) ON DELETE CASCADE,
    set_number  INTEGER NOT NULL,
    reps        INTEGER NOT NULL,
    weight_kg   REAL,
    UNIQUE (exercise_id, set_number)
)
"""

# Журнал: одна проведённая тренировка — одна строка. Все даты строками, а не одним полем.
CREATE_WORKOUT_SESSIONS = """
CREATE TABLE IF NOT EXISTS workout_sessions (
    session_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    day_id         INTEGER REFERENCES workout_days(day_id) ON DELETE SET NULL,
    started_at     TEXT    NOT NULL,
    finished_at    TEXT,
    body_weight_kg REAL,
    comment        TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

# Рабочие веса конкретной тренировки: план лежит в exercise_sets, факт — здесь.
CREATE_SESSION_SETS = """
CREATE TABLE IF NOT EXISTS session_sets (
    session_set_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES workout_sessions(session_id) ON DELETE CASCADE,
    exercise_id    INTEGER NOT NULL REFERENCES exercises(exercise_id) ON DELETE CASCADE,
    set_number     INTEGER NOT NULL,
    reps           INTEGER NOT NULL,
    weight_kg      REAL,
    UNIQUE (session_id, exercise_id, set_number)
)
"""

# Напоминания о простое. Строка на пользователя: anchor — дата, от которой
# считаем простой (последняя закрытая тренировка), stage — последнее уже
# отправленное напоминание. Сходил в зал — anchor сменился, stage обнулился.
CREATE_REMINDERS = """
CREATE TABLE IF NOT EXISTS reminders (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    anchor  TEXT    NOT NULL,
    stage   INTEGER NOT NULL DEFAULT 0,
    sent_at TEXT
)
"""

TABLES = (
    CREATE_GENDERS,
    CREATE_GOALS,
    CREATE_WORKOUT_SOURCES,
    CREATE_USERS,
    CREATE_WORKOUTS,
    CREATE_WORKOUT_DAYS,
    CREATE_EXERCISES,
    CREATE_EXERCISE_SETS,
    CREATE_WORKOUT_SESSIONS,
    CREATE_SESSION_SETS,
    CREATE_REMINDERS,
)

# Чем наполняем справочники при старте.
REFERENCE_DATA = (
    ("genders", GENDERS),
    ("goals", GOALS),
    ("workout_sources", SOURCES),
)
