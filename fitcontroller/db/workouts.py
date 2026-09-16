"""Запросы по комплексам, тренировочным дням, упражнениям и подходам."""

import logging

from fitcontroller.db.connection import connect

logger = logging.getLogger(__name__)

SELECT_WORKOUTS = """
SELECT w.*, s.label AS source
FROM workouts w
JOIN workout_sources s ON s.code = w.source_code
WHERE w.user_id = ? AND w.is_archived = ?
ORDER BY w.created_at
"""

SELECT_WORKOUT = """
SELECT w.*, s.label AS source
FROM workouts w
JOIN workout_sources s ON s.code = w.source_code
WHERE w.workout_id = ? AND w.user_id = ?
"""

SELECT_DAYS = """
SELECT * FROM workout_days
WHERE workout_id = ? AND is_archived = 0
ORDER BY position
"""

# Одним запросом на весь комплекс: упражнения и подходы всех его дней.
SELECT_EXERCISES_FOR_WORKOUT = """
SELECT e.*
FROM exercises e
JOIN workout_days d ON d.day_id = e.day_id
WHERE d.workout_id = ?
ORDER BY d.position, e.position
"""

SELECT_SETS_FOR_WORKOUT = """
SELECT s.*
FROM exercise_sets s
JOIN exercises e    ON e.exercise_id = s.exercise_id
JOIN workout_days d ON d.day_id = e.day_id
WHERE d.workout_id = ?
ORDER BY s.exercise_id, s.set_number
"""


async def list_workouts(user_id: int, archived: bool = False) -> list[dict]:
    """Комплексы пользователя: активные или те, что лежат в архиве."""
    async with connect() as db:
        async with db.execute(SELECT_WORKOUTS, (user_id, int(archived))) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_workout(workout_id: int, user_id: int) -> dict | None:
    """Комплекс целиком: дни, их упражнения и подходы.

    user_id в условии — чтобы по чужому workout_id комплекс было не открыть.
    """
    async with connect() as db:
        async with db.execute(SELECT_WORKOUT, (workout_id, user_id)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None

        async with db.execute(SELECT_DAYS, (workout_id,)) as cursor:
            days = [dict(day) for day in await cursor.fetchall()]
        async with db.execute(SELECT_EXERCISES_FOR_WORKOUT, (workout_id,)) as cursor:
            exercises = [dict(exercise) for exercise in await cursor.fetchall()]
        async with db.execute(SELECT_SETS_FOR_WORKOUT, (workout_id,)) as cursor:
            sets = [dict(item) for item in await cursor.fetchall()]

    # Раскладываем плоские выборки по вложенности, без запроса на каждый день.
    sets_by_exercise: dict[int, list[dict]] = {}
    for item in sets:
        sets_by_exercise.setdefault(item["exercise_id"], []).append(item)

    exercises_by_day: dict[int, list[dict]] = {}
    for exercise in exercises:
        exercise["sets"] = sets_by_exercise.get(exercise["exercise_id"], [])
        exercises_by_day.setdefault(exercise["day_id"], []).append(exercise)

    for day in days:
        day["exercises"] = exercises_by_day.get(day["day_id"], [])

    workout = dict(row)
    workout["days"] = days
    return workout


async def save_training_day(
    user_id: int,
    workout_title: str,
    day_title: str,
    exercises: list[dict],
    source_code: str,
) -> tuple[int, int]:
    """Сохраняет день целиком: комплекс → день → упражнения → подходы.

    Комплекс с таким названием переиспользуется, если уже есть, — так
    «добавить ещё один тренировочный день» кладёт день в ту же папку.
    Каждое упражнение — dict с ключами name, muscle_group и sets (список повторений).
    """
    async with connect() as db:
        async with db.execute(
            "SELECT workout_id FROM workouts WHERE user_id = ? AND title = ?",
            (user_id, workout_title),
        ) as cursor:
            found = await cursor.fetchone()

        if found:
            workout_id = found["workout_id"]
            await db.execute(
                "UPDATE workouts SET updated_at = datetime('now') WHERE workout_id = ?",
                (workout_id,),
            )
        else:
            cursor = await db.execute(
                "INSERT INTO workouts (user_id, title, source_code) VALUES (?, ?, ?)",
                (user_id, workout_title, source_code),
            )
            workout_id = cursor.lastrowid

        async with db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next FROM workout_days WHERE workout_id = ?",
            (workout_id,),
        ) as cursor:
            position = (await cursor.fetchone())["next"]

        cursor = await db.execute(
            "INSERT INTO workout_days (workout_id, position, title) VALUES (?, ?, ?)",
            (workout_id, position, day_title),
        )
        day_id = cursor.lastrowid

        for exercise_position, exercise in enumerate(exercises, start=1):
            cursor = await db.execute(
                """
                INSERT INTO exercises (day_id, position, name, muscle_group)
                VALUES (?, ?, ?, ?)
                """,
                (
                    day_id,
                    exercise_position,
                    exercise["name"],
                    exercise.get("muscle_group") or None,
                ),
            )
            exercise_id = cursor.lastrowid

            reps_list = exercise.get("sets") or []
            if reps_list:
                await db.executemany(
                    """
                    INSERT INTO exercise_sets (exercise_id, set_number, reps)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (exercise_id, set_number, reps)
                        for set_number, reps in enumerate(reps_list, start=1)
                    ],
                )

        await db.commit()

    logger.info(
        "Saved day_id=%s (position=%s) in workout_id=%s for user_id=%s",
        day_id,
        position,
        workout_id,
        user_id,
    )
    return workout_id, day_id


async def delete_workout(workout_id: int, user_id: int) -> None:
    """Дни, упражнения и подходы уедут следом — на них стоит ON DELETE CASCADE."""
    async with connect() as db:
        await db.execute(
            "DELETE FROM workouts WHERE workout_id = ? AND user_id = ?",
            (workout_id, user_id),
        )
        await db.commit()
    logger.info("Deleted workout_id=%s for user_id=%s", workout_id, user_id)


async def set_archived(workout_id: int, user_id: int, archived: bool) -> None:
    async with connect() as db:
        await db.execute(
            """
            UPDATE workouts
            SET is_archived = ?, updated_at = datetime('now')
            WHERE workout_id = ? AND user_id = ?
            """,
            (int(archived), workout_id, user_id),
        )
        await db.commit()
    logger.info("workout_id=%s archived=%s", workout_id, archived)


