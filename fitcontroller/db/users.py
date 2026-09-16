"""Запросы по анкете пользователя."""

import logging

from fitcontroller.db.connection import connect

logger = logging.getLogger(__name__)

# Подписи приезжают из справочников, поэтому хендлерам не нужно знать про коды.
SELECT_USER = """
SELECT u.*, g.label AS gender, t.label AS goal
FROM users u
JOIN genders g ON g.code = u.gender_code
JOIN goals   t ON t.code = u.goal_code
WHERE u.user_id = ?
"""


async def get_user(user_id: int) -> dict | None:
    async with connect() as db:
        async with db.execute(SELECT_USER, (user_id,)) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_user(
    user_id: int,
    username: str | None,
    name: str,
    gender_code: str,
    age: int,
    height_cm: int,
    weight_kg: float,
    goal_code: str,
) -> None:
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO users (
                user_id, username, name, gender_code, age, height_cm, weight_kg, goal_code
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username    = excluded.username,
                name        = excluded.name,
                gender_code = excluded.gender_code,
                age         = excluded.age,
                height_cm   = excluded.height_cm,
                weight_kg   = excluded.weight_kg,
                goal_code   = excluded.goal_code,
                updated_at  = datetime('now')
            """,
            (user_id, username, name, gender_code, age, height_cm, weight_kg, goal_code),
        )
        await db.commit()
    logger.info("Saved profile for user_id=%s", user_id)
