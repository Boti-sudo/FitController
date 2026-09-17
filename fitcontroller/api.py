"""HTTP API для мини-аппа тренировки.

Живёт в том же процессе, что и бот. Мини-апп — статическая страница на чужом
домене, поэтому доверять ей нельзя: личность пользователя берётся не из запроса,
а из подписанного Telegram блока initData.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from aiohttp import web

from config import API_HOST, API_PORT, BOT_TOKEN
from fitcontroller.payloads import (
    PayloadError,
    parse_edit_payload,
    parse_payload,
)
from fitcontroller.db import (
    finish_session,
    get_active_session,
    get_day_plan,
    get_last_session,
    get_session,
    get_session_detail,
    get_user,
    list_finished_sessions,
    list_open_sessions,
    SOURCE_USER,
    list_workouts,
    save_progress,
    save_training_day,
    start_session,
    update_training_day,
)

logger = logging.getLogger(__name__)

# Насколько старым может быть initData: страницу могли открыть и оставить.
INIT_DATA_TTL = 24 * 3600

# Отдаём сразу максимальный диапазон: переключение недели/месяца/полугода
# страница делает на своих данных, без похода на сервер.
STATS_DAYS = 180

MAX_COMMENT = 500
MAX_SETS = 30
MIN_BODY_WEIGHT, MAX_BODY_WEIGHT = 30.0, 300.0
MAX_SET_WEIGHT = 999.0


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def verify_init_data(init_data: str, bot_token: str) -> dict:
    """Проверяет подпись Telegram и возвращает данные пользователя.

    Алгоритм из документации: ключ — HMAC(токен бота, "WebAppData"),
    им подписывается строка из пар «ключ=значение», отсортированных по ключу.
    """
    if not init_data:
        raise ApiError(401, "нет initData")

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received = fields.pop("hash", None)
    if not received:
        raise ApiError(401, "в initData нет подписи")

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received):
        raise ApiError(401, "подпись не сходится")

    try:
        auth_date = int(fields.get("auth_date", 0))
    except ValueError as err:
        raise ApiError(401, "некорректный auth_date") from err
    if time.time() - auth_date > INIT_DATA_TTL:
        raise ApiError(401, "данные устарели, открой тренировку заново")

    try:
        user = json.loads(fields["user"])
    except (KeyError, json.JSONDecodeError) as err:
        raise ApiError(401, "в initData нет пользователя") from err

    if not isinstance(user.get("id"), int):
        raise ApiError(401, "в initData нет id пользователя")
    return user


def current_user_id(request: web.Request) -> int:
    return verify_init_data(request.headers.get("X-Telegram-Init-Data", ""), BOT_TOKEN)["id"]


def _number(value, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, f"поле «{field}» не число")
    if not low <= value <= high:
        raise ApiError(400, f"поле «{field}» вне диапазона {low:g}–{high:g}")
    return float(value)


async def handle_day(request: web.Request) -> web.Response:
    """План дня вместе с весами и комментарием прошлой тренировки."""
    user_id = current_user_id(request)
    try:
        day_id = int(request.match_info["day_id"])
    except ValueError as err:
        raise ApiError(400, "некорректный day_id") from err

    plan = await get_day_plan(day_id, user_id)
    if plan is None:
        raise ApiError(404, "тренировочный день не найден")

    # Мини-апп могли закрыть посреди тренировки — тогда возвращаем её как есть.
    active = await get_active_session(day_id, user_id)
    active_payload = None
    if active:
        active_payload = {
            "session_id": active["session_id"],
            "started_at": active["started_at"],
            "body_weight_kg": active["body_weight_kg"],
            "sets": [
                {
                    "exercise_id": item["exercise_id"],
                    "set_number": item["set_number"],
                    "weight_kg": item["weight_kg"],
                }
                for item in active["sets"]
            ],
        }

    # Тренировка другого дня, оставшаяся открытой, блокирует старт этой.
    blocked_by = None
    if active is None:
        others = [row for row in await list_open_sessions(user_id) if row["day_id"] != day_id]
        if others:
            blocked_by = {
                "day_id": others[0]["day_id"],
                "day_title": others[0]["day_title"],
                "workout_title": others[0]["workout_title"],
            }

    last = await get_last_session(day_id, user_id)
    previous: dict[tuple[int, int], float] = {}
    if last:
        for item in last["sets"]:
            previous[(item["exercise_id"], item["set_number"])] = item["weight_kg"] or 0

    return web.json_response(
        {
            "day_id": plan["day_id"],
            "workout_title": plan["workout_title"],
            "day_title": plan["day_title"],
            "active_session": active_payload,
            "blocked_by": blocked_by,
            "previous_comment": last["comment"] if last else None,
            "previous_finished_at": last["finished_at"] if last else None,
            "exercises": [
                {
                    "exercise_id": exercise["exercise_id"],
                    "name": exercise["name"],
                    "muscle_group": exercise["muscle_group"],
                    "sets": [
                        {
                            "set_number": item["set_number"],
                            "reps": item["reps"],
                            "previous_weight": previous.get(
                                (exercise["exercise_id"], item["set_number"]), 0
                            ),
                        }
                        for item in exercise["sets"]
                    ],
                }
                for exercise in plan["exercises"]
            ],
        }
    )


async def handle_start(request: web.Request) -> web.Response:
    """Нажали «Начать тренировку» — строка появляется в БД прямо сейчас."""
    user_id = current_user_id(request)
    body = await _json_body(request)

    day_id = body.get("day_id")
    if not isinstance(day_id, int) or isinstance(day_id, bool):
        raise ApiError(400, "не указан day_id")

    weight = _number(body.get("body_weight_kg"), "вес", MIN_BODY_WEIGHT, MAX_BODY_WEIGHT)

    # Открыл тренировку второй раз, не закрыв первую, — отдаём ту же строку,
    # иначе в журнале копятся брошенные сессии, а веса разъезжаются по двум.
    active = await get_active_session(day_id, user_id)
    if active:
        logger.info("Возвращаем незакрытую session_id=%s", active["session_id"])
        return web.json_response(
            {"session_id": active["session_id"], "started_at": active["started_at"]}
        )

    others = [row for row in await list_open_sessions(user_id) if row["day_id"] != day_id]
    if others:
        raise ApiError(
            409,
            f"сначала заверши тренировку «{others[0]['workout_title']} / "
            f"{others[0]['day_title']}»",
        )

    try:
        started = await start_session(user_id, day_id, round(weight, 1))
    except PermissionError as err:
        raise ApiError(404, str(err)) from err

    return web.json_response(started)


async def handle_finish(request: web.Request) -> web.Response:
    """Нажали «Завершить» — закрываем тренировку и пишем рабочие веса."""
    user_id = current_user_id(request)
    body = await _json_body(request)

    session_id = body.get("session_id")
    if not isinstance(session_id, int) or isinstance(session_id, bool):
        raise ApiError(400, "не указан session_id")

    session = await get_session(session_id, user_id)
    if session is None:
        raise ApiError(404, "тренировка не найдена")

    comment = body.get("comment")
    if comment is not None:
        if not isinstance(comment, str):
            raise ApiError(400, "комментарий не текст")
        comment = comment.strip()[:MAX_COMMENT] or None

    # Сверяем присланные подходы с планом: чего нет в программе — то не принимаем.
    plan = await get_day_plan(session["day_id"], user_id)
    known = {
        (exercise["exercise_id"], item["set_number"]): item["reps"]
        for exercise in plan["exercises"]
        for item in exercise["sets"]
    }

    raw_sets = body.get("sets")
    if not isinstance(raw_sets, list):
        raise ApiError(400, "подходы пришли не списком")

    sets = []
    for raw in raw_sets:
        if not isinstance(raw, dict):
            raise ApiError(400, "подход пришёл не объектом")
        key = (raw.get("exercise_id"), raw.get("set_number"))
        if key not in known:
            raise ApiError(400, "подход не из программы этого дня")
        # Подход без веса — дыра в журнале: следующая тренировка покажет 0
        # вместо реального веса. Мини-апп такое не отправляет, но запрос мог
        # прийти и от старой версии страницы, осевшей в кэше Telegram.
        weight = raw.get("weight_kg")
        if weight is None:
            raise ApiError(400, "у подхода не указан вес")

        sets.append(
            {
                "exercise_id": key[0],
                "set_number": key[1],
                "reps": known[key],
                "weight_kg": round(_number(weight, "вес", 0, MAX_SET_WEIGHT), 1),
            }
        )

    # Тренировка закрывается целиком: недосланные подходы — та же дыра в журнале,
    # что и подход без веса, только заметить её потом ещё труднее.
    # Считаем по ключам, а не по длине списка: один и тот же подход, присланный
    # дважды, иначе закрыл бы тренировку за соседний и упал бы на UNIQUE при вставке.
    missing = len(known) - len({(item["exercise_id"], item["set_number"]) for item in sets})
    if missing > 0:
        raise ApiError(400, f"не присланы все подходы тренировки (не хватает {missing})")

    try:
        finished_at = await finish_session(session_id, user_id, comment, sets)
    except PermissionError as err:
        raise ApiError(409, str(err)) from err

    return web.json_response({"finished_at": finished_at, "sets": len(sets)})


async def handle_progress(request: web.Request) -> web.Response:
    """Автосохранение: веса складываются в базу, не дожидаясь «Завершить»."""
    user_id = current_user_id(request)
    body = await _json_body(request)

    session_id = body.get("session_id")
    if not isinstance(session_id, int) or isinstance(session_id, bool):
        raise ApiError(400, "не указан session_id")

    session = await get_session(session_id, user_id)
    if session is None:
        raise ApiError(404, "тренировка не найдена")

    plan = await get_day_plan(session["day_id"], user_id)
    if plan is None:
        raise ApiError(404, "тренировочный день не найден")

    known = {
        (exercise["exercise_id"], item["set_number"]): item["reps"]
        for exercise in plan["exercises"]
        for item in exercise["sets"]
    }

    raw_sets = body.get("sets")
    if not isinstance(raw_sets, list):
        raise ApiError(400, "подходы пришли не списком")

    sets = []
    for raw in raw_sets:
        if not isinstance(raw, dict):
            raise ApiError(400, "подход пришёл не объектом")
        key = (raw.get("exercise_id"), raw.get("set_number"))
        if key not in known:
            raise ApiError(400, "подход не из программы этого дня")

        # В отличие от завершения, пустой вес здесь нормален: человек ещё в процессе.
        weight = raw.get("weight_kg")
        sets.append(
            {
                "exercise_id": key[0],
                "set_number": key[1],
                "reps": known[key],
                "weight_kg": (
                    None if weight is None else round(_number(weight, "вес", 0, MAX_SET_WEIGHT), 1)
                ),
            }
        )

    try:
        await save_progress(session_id, user_id, sets)
    except PermissionError as err:
        raise ApiError(409, str(err)) from err

    return web.json_response({"saved": len(sets)})


async def handle_save_days(request: web.Request) -> web.Response:
    """Конструктор прислал новые тренировочные дни.

    Раньше это приезжало через sendData, но мини-апп с кнопки клавиатуры не
    получает подписи Telegram и не может ничего прочитать с сервера. Теперь
    страница открывается инлайн-кнопкой и сохраняет сама.
    """
    user_id = current_user_id(request)
    body = await _json_body(request)

    try:
        workout_title, days = parse_payload(json.dumps(body))
    except PayloadError as err:
        raise ApiError(400, str(err)) from err

    for day in days:
        await save_training_day(
            user_id=user_id,
            workout_title=workout_title,
            day_title=day["title"],
            exercises=day["exercises"],
            source_code=SOURCE_USER,
        )

    return web.json_response(
        {
            "workout_title": workout_title,
            "days": [
                {
                    "title": day["title"],
                    "exercises": len(day["exercises"]),
                    "sets": sum(len(exercise["sets"]) for exercise in day["exercises"]),
                }
                for day in days
            ],
        }
    )


async def handle_update_day(request: web.Request) -> web.Response:
    """Конструктор прислал правку существующего дня."""
    user_id = current_user_id(request)
    body = await _json_body(request)

    try:
        day_id = int(request.match_info["day_id"])
    except ValueError as err:
        raise ApiError(400, "некорректный day_id") from err

    body = dict(body, id=day_id)
    try:
        _, day_title, exercises = parse_edit_payload(json.dumps(body))
    except PayloadError as err:
        raise ApiError(400, str(err)) from err

    try:
        await update_training_day(user_id, day_id, day_title, exercises)
    except PermissionError as err:
        raise ApiError(404, str(err)) from err

    return web.json_response(
        {
            "day_title": day_title,
            "exercises": len(exercises),
            "sets": sum(len(exercise["sets"]) for exercise in exercises),
        }
    )


async def handle_workouts(request: web.Request) -> web.Response:
    """Активные папки — конструктору, чтобы положить день в существующую."""
    user_id = current_user_id(request)
    workouts = await list_workouts(user_id)
    return web.json_response(
        {"workouts": [{"workout_id": w["workout_id"], "title": w["title"]} for w in workouts]}
    )


async def handle_stats(request: web.Request) -> web.Response:
    """Завершённые тренировки за полгода — сырьё для графика веса и списка."""
    user_id = current_user_id(request)
    since = datetime.now(timezone.utc) - timedelta(days=STATS_DAYS)

    sessions = await list_finished_sessions(user_id, since.strftime("%Y-%m-%d %H:%M:%S"))

    # Вес из анкеты — первая точка графика: до первой тренировки других нет.
    user = await get_user(user_id)
    profile = None
    if user and user["weight_kg"] is not None:
        profile = {"weight_kg": user["weight_kg"], "measured_at": user["created_at"]}

    return web.json_response({"days": STATS_DAYS, "sessions": sessions, "profile": profile})


async def handle_stats_session(request: web.Request) -> web.Response:
    """Одна тренировка целиком — для кнопки «Посмотреть»."""
    user_id = current_user_id(request)
    try:
        session_id = int(request.match_info["session_id"])
    except ValueError as err:
        raise ApiError(400, "некорректный session_id") from err

    detail = await get_session_detail(session_id, user_id)
    if detail is None:
        raise ApiError(404, "тренировка не найдена")
    return web.json_response(detail)


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except json.JSONDecodeError as err:
        raise ApiError(400, "тело запроса не JSON") from err
    if not isinstance(body, dict):
        raise ApiError(400, "ожидался объект")
    return body


@web.middleware
async def access_log_middleware(request: web.Request, handler):
    """Строка на каждый запрос — видно, дошёл ли мини-апп до сервера."""
    started = time.monotonic()
    response = await handler(request)
    logger.info(
        "%s %s -> %s за %.0f мс (%s)",
        request.method,
        request.path_qs,
        response.status,
        (time.monotonic() - started) * 1000,
        request.headers.get("User-Agent", "?")[:40],
    )
    return response


@web.middleware
async def errors_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except ApiError as err:
        if err.status == 401:
            logger.warning("%s %s -> 401 %s", request.method, request.path, err.message)
        return web.json_response({"error": err.message}, status=err.status)
    except Exception:
        logger.exception("Unhandled API error on %s %s", request.method, request.path)
        return web.json_response({"error": "внутренняя ошибка"}, status=500)


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """Страница живёт на другом домене, поэтому браузер требует CORS-заголовки.

    Origin разрешаем любой: доступ защищает подпись initData, а не источник запроса.
    """
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    # X-Pinggy-No-Screen шлёт мини-апп, чтобы туннель не подсунул страницу-заглушку;
    # незаявленный здесь заголовок браузер зарубит ещё на preflight.
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, X-Telegram-Init-Data, X-Pinggy-No-Screen"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def create_app() -> web.Application:
    app = web.Application(
        middlewares=[cors_middleware, access_log_middleware, errors_middleware]
    )
    app.router.add_get("/api/day/{day_id}", handle_day)
    app.router.add_post("/api/session/start", handle_start)
    app.router.add_post("/api/session/finish", handle_finish)
    app.router.add_post("/api/session/progress", handle_progress)
    app.router.add_get("/api/workouts", handle_workouts)
    app.router.add_post("/api/days", handle_save_days)
    app.router.add_post("/api/day/{day_id}", handle_update_day)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/stats/session/{session_id}", handle_stats_session)
    app.router.add_get("/api/health", lambda request: web.json_response({"ok": True}))
    app.router.add_route("OPTIONS", "/api/{tail:.*}", lambda request: web.Response(status=204))
    return app


async def start_api() -> web.AppRunner:
    """Поднимает сервер рядом с polling и возвращает runner для остановки."""
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()
    logger.info("API listening on http://%s:%s", API_HOST, API_PORT)
    return runner
