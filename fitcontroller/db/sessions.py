"""Запросы по проведённым тренировкам: план дня, прошлые веса, сохранение результата."""

import logging

from fitcontroller.db.connection import connect

logger = logging.getLogger(__name__)

# day_id вместе с user_id — чтобы по чужому id день было не открыть.
SELECT_DAY = """
SELECT d.day_id, d.title AS day_title, d.position,
       w.workout_id, w.title AS workout_title
FROM workout_days d
JOIN workouts w ON w.workout_id = d.workout_id
WHERE d.day_id = ? AND w.user_id = ?
"""

SELECT_DAY_PLAN = """
SELECT e.exercise_id, e.position, e.name, e.muscle_group,
       s.set_number, s.reps
FROM exercises e
LEFT JOIN exercise_sets s ON s.exercise_id = e.exercise_id
WHERE e.day_id = ?
ORDER BY e.position, s.set_number
"""

# Последняя завершённая тренировка этого дня — источник «предыдущих» весов.
SELECT_LAST_SESSION = """
SELECT * FROM workout_sessions
WHERE day_id = ? AND user_id = ? AND finished_at IS NOT NULL
ORDER BY finished_at DESC
LIMIT 1
"""

SELECT_SESSION_SETS = """
SELECT exercise_id, set_number, reps, weight_kg
FROM session_sets
WHERE session_id = ?
ORDER BY exercise_id, set_number
"""


async def get_day_plan(day_id: int, user_id: int) -> dict | None:
    """План тренировочного дня: упражнения с запланированными подходами."""
    async with connect() as db:
        async with db.execute(SELECT_DAY, (day_id, user_id)) as cursor:
            day = await cursor.fetchone()
        if day is None:
            return None

        async with db.execute(SELECT_DAY_PLAN, (day_id,)) as cursor:
            rows = await cursor.fetchall()

    exercises: list[dict] = []
    by_id: dict[int, dict] = {}
    for row in rows:
        exercise = by_id.get(row["exercise_id"])
        if exercise is None:
            exercise = {
                "exercise_id": row["exercise_id"],
                "position": row["position"],
                "name": row["name"],
                "muscle_group": row["muscle_group"],
                "sets": [],
            }
            by_id[row["exercise_id"]] = exercise
            exercises.append(exercise)
        # LEFT JOIN: у упражнения без подходов set_number пустой.
        if row["set_number"] is not None:
            exercise["sets"].append({"set_number": row["set_number"], "reps": row["reps"]})

    result = dict(day)
    result["exercises"] = exercises
    return result


async def get_last_session(day_id: int, user_id: int) -> dict | None:
    """Последняя завершённая тренировка этого дня вместе с рабочими весами."""
    async with connect() as db:
        async with db.execute(SELECT_LAST_SESSION, (day_id, user_id)) as cursor:
            session = await cursor.fetchone()
        if session is None:
            return None

        async with db.execute(SELECT_SESSION_SETS, (session["session_id"],)) as cursor:
            sets = await cursor.fetchall()

    result = dict(session)
    result["sets"] = [dict(item) for item in sets]
    return result


async def start_session(user_id: int, day_id: int, body_weight_kg: float) -> dict:
    """Открывает тренировку: строка появляется в БД в момент нажатия «Начать»."""
    async with connect() as db:
        async with db.execute(SELECT_DAY, (day_id, user_id)) as cursor:
            if await cursor.fetchone() is None:
                raise PermissionError("день не принадлежит пользователю")

        cursor = await db.execute(
            """
            INSERT INTO workout_sessions (user_id, day_id, started_at, body_weight_kg)
            VALUES (?, ?, datetime('now'), ?)
            """,
            (user_id, day_id, body_weight_kg),
        )
        session_id = cursor.lastrowid

        async with db.execute(
            "SELECT started_at FROM workout_sessions WHERE session_id = ?", (session_id,)
        ) as cursor:
            started_at = (await cursor.fetchone())["started_at"]

        await db.execute(
            """
            UPDATE workout_days
            SET started_at = COALESCE(started_at, ?), updated_at = datetime('now')
            WHERE day_id = ?
            """,
            (started_at, day_id),
        )
        await db.commit()

    logger.info("Started session_id=%s user_id=%s day_id=%s", session_id, user_id, day_id)
    return {"session_id": session_id, "started_at": started_at}


async def get_session(session_id: int, user_id: int) -> dict | None:
    async with connect() as db:
        async with db.execute(
            "SELECT * FROM workout_sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def finish_session(
    session_id: int,
    user_id: int,
    comment: str | None,
    sets: list[dict],
) -> str:
    """Закрывает тренировку и записывает рабочие веса. Возвращает время завершения."""
    async with connect() as db:
        async with db.execute(
            "SELECT finished_at FROM workout_sessions WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise PermissionError("тренировка не найдена")
        if row["finished_at"]:
            raise PermissionError("тренировка уже завершена")

        await db.execute(
            """
            UPDATE workout_sessions
            SET finished_at = datetime('now'), comment = ?
            WHERE session_id = ?
            """,
            (comment, session_id),
        )

        # Повторное завершение исключено проверкой выше, но подчистим на всякий случай.
        await db.execute("DELETE FROM session_sets WHERE session_id = ?", (session_id,))
        if sets:
            await db.executemany(
                """
                INSERT INTO session_sets
                    (session_id, exercise_id, set_number, reps, weight_kg)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        item["exercise_id"],
                        item["set_number"],
                        item["reps"],
                        item.get("weight_kg"),
                    )
                    for item in sets
                ],
            )

        async with db.execute(
            "SELECT finished_at FROM workout_sessions WHERE session_id = ?", (session_id,)
        ) as cursor:
            finished_at = (await cursor.fetchone())["finished_at"]

        await db.commit()

    logger.info("Finished session_id=%s (%s подходов)", session_id, len(sets))
    return finished_at


async def save_session(
    user_id: int,
    day_id: int,
    started_at: str,
    finished_at: str,
    body_weight_kg: float | None,
    comment: str | None,
    sets: list[dict],
) -> int:
    """Сохраняет проведённую тренировку целиком.

    Каждый элемент sets — dict с exercise_id, set_number, reps и weight_kg.
    Проставляет дату первого старта у дня, если её ещё не было.
    """
    async with connect() as db:
        cursor = await db.execute(
            """
            INSERT INTO workout_sessions
                (user_id, day_id, started_at, finished_at, body_weight_kg, comment)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, day_id, started_at, finished_at, body_weight_kg, comment),
        )
        session_id = cursor.lastrowid

        if sets:
            await db.executemany(
                """
                INSERT INTO session_sets
                    (session_id, exercise_id, set_number, reps, weight_kg)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        item["exercise_id"],
                        item["set_number"],
                        item["reps"],
                        item.get("weight_kg"),
                    )
                    for item in sets
                ],
            )

        await db.execute(
            """
            UPDATE workout_days
            SET started_at = COALESCE(started_at, ?),
                updated_at = datetime('now')
            WHERE day_id = ?
            """,
            (started_at, day_id),
        )
        await db.commit()

    logger.info(
        "Saved session_id=%s for user_id=%s day_id=%s (%s подходов)",
        session_id,
        user_id,
        day_id,
        len(sets),
    )
    return session_id


async def list_sessions(user_id: int) -> list[dict]:
    """Все тренировки пользователя, свежие сверху."""
    async with connect() as db:
        async with db.execute(
            """
            SELECT s.*, d.title AS day_title, w.title AS workout_title
            FROM workout_sessions s
            LEFT JOIN workout_days d ON d.day_id = s.day_id
            LEFT JOIN workouts w     ON w.workout_id = d.workout_id
            WHERE s.user_id = ?
            ORDER BY s.started_at DESC
            """,
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]
