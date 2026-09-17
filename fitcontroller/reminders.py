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

from config import REMINDER_HOURS, REMINDER_TZ_OFFSET, REMINDER_INTERVAL_MINUTES
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


async def run_once(bot: Bot) -> int:
    """Один проход. Возвращает число отправленных сообщений."""
    now = datetime.now(timezone.utc)
    if not in_window(now):
        return 0

    sent = 0
    for row, stage, text in pending(await list_idle_candidates(), now):
        try:
            await bot.send_message(row["user_id"], text)
        except TelegramForbiddenError:
            # Заблокировал бота — этап всё равно отмечаем, чтобы не долбиться каждый раз.
            logger.info("user_id=%s заблокировал бота", row["user_id"])
        except TelegramRetryAfter as err:
            logger.warning("Лимит Telegram, ждём %s с", err.retry_after)
            await asyncio.sleep(err.retry_after)
            continue
        except Exception:
            logger.exception("Не смог отправить напоминание user_id=%s", row["user_id"])
            continue
        else:
            sent += 1

        await mark_reminded(row["user_id"], row["anchor"], stage)

    return sent


async def reminder_loop(bot: Bot) -> None:
    """Фоновая задача рядом с polling: просыпается раз в REMINDER_INTERVAL_MINUTES."""
    logger.info(
        "Reminders: окно %s:00-%s:00 (UTC%+d), проверка раз в %s мин",
        REMINDER_HOURS[0],
        REMINDER_HOURS[1],
        REMINDER_TZ_OFFSET,
        REMINDER_INTERVAL_MINUTES,
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
