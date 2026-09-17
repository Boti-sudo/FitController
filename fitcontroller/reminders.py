"""Напоминания тем, кто давно не тренировался.

Простой считается от последней закрытой тренировки. На 7-е, 9-е и 15-е сутки
уходит по одному сообщению, дальше бот молчит. Сходил в зал — отсчёт с нуля.

Сообщения шлются только в дневное окно: проверка идёт раз в полчаса, и если
в момент наступления срока окно уже закрыто или бот был выключен, напоминание
уйдёт при следующей проверке внутри окна — то есть на следующий день.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from config import (
    FORGOTTEN_AFTER_HOURS,
    REMINDER_HOURS,
    REMINDER_INTERVAL_MINUTES,
    REMINDER_TZ_OFFSET,
)
from fitcontroller.db import list_stale_sessions, mark_session_reminded
from fitcontroller.db.reminders import list_idle_candidates, mark_reminded

logger = logging.getLogger(__name__)

# Порог в сутках и текст. Порядок важен: ищем самый поздний подошедший этап.
STAGES = (
    (
        15,
        "Прошло 2 недели. Не хочу быть навязчивым и больше не буду присылать "
        "уведомления, просто помни: быть красивым и накачанным — это круто.",
    ),
    (9, "В зале без тебя совсем грустно 😢"),
    (
        7,
        "Привет, ты уже неделю не тренируешься! 😔 "
        "Ты всё ещё хочешь сохранить и улучшить свои результаты?",
    ),
)


def _parse(moment: str) -> datetime:
    """Даты в базе лежат строками в UTC и без метки зоны — проставляем её."""
    return datetime.strptime(moment, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def in_window(now: datetime) -> bool:
    """Дневное окно по местному времени пользователя бота."""
    local_hour = (now + timedelta(hours=REMINDER_TZ_OFFSET)).hour
    return REMINDER_HOURS[0] <= local_hour < REMINDER_HOURS[1]


def due_stage(idle_days: int, sent_stage: int) -> tuple[int, str] | None:
    """Какой этап пора отправить: самый поздний подошедший, если он ещё не уходил."""
    for days, text in STAGES:
        if idle_days >= days:
            return (days, text) if days > sent_stage else None
    return None


def pending(candidates: list[dict], now: datetime) -> list[tuple[dict, int, str]]:
    """Отбирает, кому и что пора отправить. Вынесено отдельно ради тестов."""
    due = []
    for row in candidates:
        try:
            anchor = _parse(row["anchor"])
        except ValueError:
            logger.warning("user_id=%s: непонятная дата %r", row["user_id"], row["anchor"])
            continue

        # Тренировался после прошлого напоминания — счётчик этапов сбрасывается.
        sent_stage = row["stage"] if row["sent_anchor"] == row["anchor"] else 0

        stage = due_stage((now - anchor).days, sent_stage)
        if stage:
            due.append((row, stage[0], stage[1]))
    return due


async def _send(bot: Bot, user_id: int, text: str) -> bool:
    """Отправка с разбором типовых отказов Telegram. True — сообщение ушло."""
    try:
        await bot.send_message(user_id, text)
    except TelegramForbiddenError:
        # Заблокировал бота — отметку всё равно ставим, чтобы не долбиться каждый раз.
        logger.info("user_id=%s заблокировал бота", user_id)
    except TelegramRetryAfter as err:
        logger.warning("Лимит Telegram, ждём %s с", err.retry_after)
        await asyncio.sleep(err.retry_after)
        return False
    except Exception:
        logger.exception("Не смог отправить сообщение user_id=%s", user_id)
        return False
    return True


async def notify_forgotten(bot: Bot) -> int:
    """Тренировка висит открытой дольше порога — человек просто забыл её закрыть.

    Шлём в любое время суток, не дожидаясь дневного окна: напоминание полезно,
    пока человек ещё помнит, что делал в зале.
    """
    sent = 0
    for row in await list_stale_sessions(FORGOTTEN_AFTER_HOURS):
        where = f"«{row['workout_title']}»"
        muscles = ", ".join(row["muscle_groups"])
        text = (
            f"Ты забыл завершить тренировку из {where}"
            + (f" на {muscles}" if muscles else "")
            + ". Зайди и закрой её, чтобы веса попали в статистику."
        )

        if not await _send(bot, row["user_id"], text):
            continue

        await mark_session_reminded(row["session_id"])
        sent += 1
    return sent


async def run_once(bot: Bot) -> int:
    """Один проход. Возвращает число отправленных сообщений."""
    sent = await notify_forgotten(bot)

    now = datetime.now(timezone.utc)
    if not in_window(now):
        return sent

    for row, stage, text in pending(await list_idle_candidates(), now):
        if not await _send(bot, row["user_id"], text):
            continue

        await mark_reminded(row["user_id"], row["anchor"], stage)
        sent += 1

    return sent


async def reminder_loop(bot: Bot) -> None:
    """Фоновая задача рядом с polling: просыпается раз в REMINDER_INTERVAL_MINUTES."""
    logger.info(
        "Reminders: окно %s:00-%s:00 (UTC%+d), проверка раз в %s мин, "
        "незакрытая тренировка — через %s ч",
        REMINDER_HOURS[0],
        REMINDER_HOURS[1],
        REMINDER_TZ_OFFSET,
        REMINDER_INTERVAL_MINUTES,
        FORGOTTEN_AFTER_HOURS,
    )
    while True:
        try:
            sent = await run_once(bot)
            if sent:
                logger.info("Reminders: отправлено %s", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminders: проход упал, ждём следующего")

        await asyncio.sleep(REMINDER_INTERVAL_MINUTES * 60)
