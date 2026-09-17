"""Запросы для напоминаний о простое.

anchor — дата, от которой считается простой: последняя закрытая тренировка,
а у тех, кто ещё ни разу не тренировался, — дата заполнения анкеты.
"""

import logging

from fitcontroller.db.connection import connect

logger = logging.getLogger(__name__)

# Одним запросом на всех: кому сколько дней простоя и что ему уже отправляли.
# COALESCE берёт дату анкеты, если завершённых тренировок ещё не было.
SELECT_IDLE = """
SELECT u.user_id,
       u.name,
       COALESCE(MAX(s.finished_at), u.created_at) AS anchor,
       r.anchor AS sent_anchor,
       COALESCE(r.stage, 0) AS stage
FROM users u
LEFT JOIN workout_sessions s
       ON s.user_id = u.user_id AND s.finished_at IS NOT NULL
LEFT JOIN reminders r ON r.user_id = u.user_id
GROUP BY u.user_id
"""


async def list_idle_candidates() -> list[dict]:
    """Все пользователи с датой последней тренировки и уже отправленным этапом."""
    async with connect() as db:
        async with db.execute(SELECT_IDLE) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def mark_reminded(user_id: int, anchor: str, stage: int) -> None:
    """Запоминает отправленный этап. Сменился anchor — счётчик начинается заново."""
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO reminders (user_id, anchor, stage, sent_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                anchor  = excluded.anchor,
                stage   = excluded.stage,
                sent_at = excluded.sent_at
            """,
            (user_id, anchor, stage),
        )
        await db.commit()
    logger.info("Reminder stage=%s sent to user_id=%s (anchor=%s)", stage, user_id, anchor)
