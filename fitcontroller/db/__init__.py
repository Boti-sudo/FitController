"""Фасад пакета: хендлерам не нужно знать, в каком модуле лежит запрос."""

from fitcontroller.db.connection import connect, init_db
from fitcontroller.db.schema import GENDERS, GOALS, SOURCE_AI, SOURCE_USER, SOURCES
from fitcontroller.db.sessions import (
    finish_session,
    get_active_session,
    get_day_plan,
    get_last_session,
    get_latest_body_weight,
    get_session,
    get_session_detail,
    list_finished_sessions,
    list_open_sessions,
    list_sessions,
    list_stale_sessions,
    mark_session_reminded,
    save_progress,
    save_session,
    start_session,
)
from fitcontroller.db.users import get_user, upsert_user
from fitcontroller.db.workouts import (
    delete_workout,
    get_workout,
    list_workouts,
    save_training_day,
    set_archived,
)

__all__ = [
    "GENDERS",
    "GOALS",
    "SOURCES",
    "SOURCE_AI",
    "SOURCE_USER",
    "connect",
    "delete_workout",
    "finish_session",
    "get_active_session",
    "get_day_plan",
    "get_last_session",
    "get_latest_body_weight",
    "get_session",
    "get_session_detail",
    "get_user",
    "get_workout",
    "init_db",
    "list_finished_sessions",
    "list_open_sessions",
    "list_sessions",
    "list_stale_sessions",
    "mark_session_reminded",
    "list_workouts",
    "save_progress",
    "save_session",
    "save_training_day",
    "set_archived",
    "start_session",
    "upsert_user",
]
