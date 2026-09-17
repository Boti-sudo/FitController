"""Подключение к БД и инициализация схемы."""

import logging
from contextlib import asynccontextmanager

import aiosqlite

from config import DB_PATH
from fitcontroller.db.schema import REFERENCE_DATA, TABLES

logger = logging.getLogger(__name__)


@asynccontextmanager
async def connect():
    """Соединение с включёнными внешними ключами и доступом к полям по имени.

    PRAGMA foreign_keys выставляется на каждое соединение — в SQLite это
    настройка сессии, а не файла, и по умолчанию она выключена.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        db.row_factory = aiosqlite.Row
        yield db


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        return {row[1] for row in await cursor.fetchall()}


async def _drop_legacy_exercises(db: aiosqlite.Connection) -> None:
    """Упражнения переехали с программы на тренировочный день.

    CREATE TABLE IF NOT EXISTS старую таблицу не переделает, а ALTER не умеет
    менять внешние ключи — поэтому пустую таблицу старой формы сносим.
    Если в ней вдруг оказались данные, останавливаемся и не трогаем их.
    """
    columns = await _columns(db, "exercises")
    if not columns or "workout_id" not in columns:
        return

    async with db.execute("SELECT COUNT(*) FROM exercises") as cursor:
        (count,) = await cursor.fetchone()

    if count:
        raise RuntimeError(
            f"exercises со старой схемой содержит {count} строк — "
            "перенеси их вручную перед запуском"
        )

    await db.execute("DROP TABLE exercises")
    logger.warning("Dropped legacy exercises table (was empty)")


async def _drop_legacy_sessions(db: aiosqlite.Connection) -> None:
    """В журнале теперь начало, конец, вес и комментарий вместо одной даты."""
    columns = await _columns(db, "workout_sessions")
    if not columns or "started_at" in columns:
        return

    async with db.execute("SELECT COUNT(*) FROM workout_sessions") as cursor:
        (count,) = await cursor.fetchone()

    if count:
        raise RuntimeError(
            f"workout_sessions со старой схемой содержит {count} строк — "
            "перенеси их вручную перед запуском"
        )

    await db.execute("DROP TABLE workout_sessions")
    logger.warning("Dropped legacy workout_sessions table (was empty)")


async def _add_missing_columns(db: aiosqlite.Connection) -> None:
    """Дописывает колонки, появившиеся позже таблицы.

    CREATE TABLE IF NOT EXISTS существующую таблицу не трогает, а данные в ней
    уже есть — поэтому недостающее добавляем отдельным ALTER.
    """
    additions = (("workout_sessions", "reminded_at", "TEXT"),)

    for table, column, kind in additions:
        columns = await _columns(db, table)
        if columns and column not in columns:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            logger.warning("Added column %s.%s", table, column)


async def _fill_reference_tables(db: aiosqlite.Connection) -> None:
    for table, values in REFERENCE_DATA:
        await db.executemany(
            f"""
            INSERT INTO {table} (code, label) VALUES (?, ?)
            ON CONFLICT(code) DO UPDATE SET label = excluded.label
            """,
            list(values.items()),
        )


async def init_db() -> None:
    async with connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await _drop_legacy_exercises(db)
        await _drop_legacy_sessions(db)
        for statement in TABLES:
            await db.execute(statement)
        await _add_missing_columns(db)
        await _fill_reference_tables(db)
        await db.commit()
    logger.info("Database ready at %s", DB_PATH)
