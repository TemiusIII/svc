"""Страницы сервиса записи на приём: HTTP-операции и шаблоны.

Здесь же сидят закономерные следствия «обычного» кода, из-за которых
возникают узкие места третьего задания: чтение связанных сущностей
в цикле и подсчёт в коде приложения. В ДЗ 1 они только измеряются.
"""
import logging
from datetime import date, datetime, timedelta

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .dbstats import reset, snapshot

log = logging.getLogger("booking")
templates: Jinja2Templates | None = None

PAGE_SIZE = 20

from fastapi import APIRouter  # noqa: E402

router = APIRouter()


async def current_user(request: Request, session: AsyncSession):
    """Пользователь по куке сессии. Нет куки — нет пользователя."""
    login = request.cookies.get("booking_user")
    if not login:
        return None
    row = (await session.execute(text("""
        SELECT login, full_name FROM users WHERE login = :l
    """), {"l": login})).mappings().first()
    return dict(row) if row else None


def render(request, name, user, **context):
    return templates.TemplateResponse(
        request, name, {"user": user, **context})


# ────────────────────────────── вход и выход ───────────────────────────────

async def login_form(request: Request, session: AsyncSession = Depends(get_session)):
    accounts = (await session.execute(text("""
        SELECT login, full_name FROM users ORDER BY id
    """))).mappings().all()
    return templates.TemplateResponse(
        request, "login.html", {"user": None, "accounts": accounts})


async def login(request: Request, login: str = Form(...),
                password: str = Form(...),
                session: AsyncSession = Depends(get_session)):
    found = (await session.execute(
        text("SELECT login FROM users WHERE login = :l AND password = :p"),
        {"l": login, "p": password})).first()
    if not found:
        return RedirectResponse("/login?error=1", status_code=302)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie("booking_user", login, max_age=60 * 60 * 24 * 30)
    return response


async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("booking_user")
    return response


# ─────────────────────────────── справочники ───────────────────────────────

async def home(request: Request, session: AsyncSession = Depends(get_session)):
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)
    services = (await session.execute(text(
        "SELECT id, name, duration_min FROM services ORDER BY id"
    ))).mappings().all()
    return render(request, "home.html", user, services=services)


async def specialists(request: Request, session: AsyncSession = Depends(get_session)):
    """Список специалистов — экран 1 (фильтр и постраничный вывод)."""
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)
    speciality = request.query_params.get("speciality", "")
    page = max(int(request.query_params.get("page", "1") or 1), 1)

    params: dict = {}
    where = ""
    if speciality:
        where = "WHERE s.speciality = :speciality"
        params["speciality"] = speciality
    total = (await session.execute(text(f"""
        SELECT count(*) FROM specialists s {where}
    """), params)).scalar_one()
    params["limit"], params["offset"] = PAGE_SIZE, (page - 1) * PAGE_SIZE
    rows = (await session.execute(text(f"""
        SELECT s.id, s.full_name, s.speciality
          FROM specialists s {where}
         ORDER BY s.id
         LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    specialities = (await session.execute(text(
        "SELECT DISTINCT speciality FROM specialists ORDER BY speciality"
    ))).scalars().all()
    return render(request, "specialists.html", user, items=rows, total=total,
                  page=page, pages=(total + PAGE_SIZE - 1) // PAGE_SIZE,
                  speciality=speciality, specialities=specialities)


async def specialist_card(specialist_id: int, request: Request,
                           session: AsyncSession = Depends(get_session)):
    """Карточка специалиста — экран 2, со связанными сущностями.

    Услуги и следующие 10 записей читаются отдельными запросами: у специалиста
    их немного, и при малом объёме это незаметно.
    """
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)
    person = (await session.execute(text("""
        SELECT id, full_name, speciality FROM specialists WHERE id = :id
    """), {"id": specialist_id})).mappings().first()
    if not person:
        return RedirectResponse("/specialists", status_code=302)
    services = (await session.execute(text("""
        SELECT sv.id, sv.name, sv.duration_min
          FROM services sv
          JOIN specialist_services ss ON ss.service_id = sv.id
         WHERE ss.specialist_id = :id
         ORDER BY sv.id
    """), {"id": specialist_id})).mappings().all()
    upcoming = (await session.execute(text("""
        SELECT a.id, sl.starts_at, sl.ends_at, a.status, sv.name AS service_name
          FROM appointments a
          JOIN slots sl ON sl.id = a.slot_id
          JOIN services sv ON sv.id = sl.service_id
         WHERE sl.specialist_id = :id AND a.status = 'booked'
         ORDER BY sl.starts_at DESC LIMIT 10
    """), {"id": specialist_id})).mappings().all()
    return render(request, "specialist.html", user, person=dict(person),
                  services=services, upcoming=upcoming)


# ───────────────────────── свободные слоты и бронирование ──────────────────

async def free_slots(request: Request, session: AsyncSession = Depends(get_session)):
    """Свободные слоты по услуге — экран 2б.

    Слоты, уже занятые записью со статусом booked, не показываются.
    Длительность услуги для фильтра читается отдельным запросом.
    """
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)
    service_id = request.query_params.get("service")
    date_from = request.query_params.get("from", "")
    if not service_id:
        return RedirectResponse("/", status_code=302)
    service = (await session.execute(text("""
        SELECT id, name, duration_min FROM services WHERE id = :id
    """), {"id": int(service_id)})).mappings().first()
    if not service:
        return RedirectResponse("/", status_code=302)
    # Окно поиска: неделя от указанной даты (или от сегодня).
    start_day = date.fromisoformat(date_from) if date_from else date.today()
    window_start = datetime.combine(start_day, datetime.min.time())
    window_end = window_start + timedelta(days=7)
    slots = (await session.execute(text("""
        SELECT sl.id, sl.specialist_id, sl.starts_at, sl.ends_at,
               sp.full_name AS specialist_name, sp.speciality
          FROM slots sl
          JOIN specialists sp ON sp.id = sl.specialist_id
         WHERE sl.service_id = :service
           AND sl.starts_at >= :wstart AND sl.starts_at < :wend
           AND sl.status = 'free'
         ORDER BY sl.starts_at
    """), {"service": int(service_id), "wstart": window_start,
           "wend": window_end})).mappings().all()
    # Каждой услуге соответствует своё множество специалистов: показать
    # только тех, кто её оказывает.
    return render(request, "slots.html", user, service=dict(service),
                  slots=slots, date_from=start_day.isoformat())


async def book(request: Request, slot_id: int = Form(...),
               client_name: str = Form(""),
               session: AsyncSession = Depends(get_session)):
    """Бронирование слота — основная операция варианта.

    Правило: слот бронируется, только если он свободен и не пересекается
    с существующими записями этого специалиста. Пересечение проверяется
    запросом; при нарушении — 409 и запись не создаётся.
    """
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)

    slot = (await session.execute(text("""
        SELECT id, specialist_id, service_id, starts_at, ends_at, status
          FROM slots WHERE id = :id
    """), {"id": slot_id})).mappings().first()
    if not slot:
        return JSONResponse({"error": "slot_not_found"}, status_code=404)
    if slot["status"] != "free":
        return JSONResponse({"error": "slot_busy"}, status_code=409)

    # Наложение: уже есть запись этого специалиста, пересекающая слот по времени.
    overlap = (await session.execute(text("""
        SELECT count(*) FROM appointments a
          JOIN slots sl ON sl.id = a.slot_id
         WHERE sl.specialist_id = :sp AND a.status = 'booked'
           AND sl.starts_at < :ends AND sl.ends_at > :starts
    """), {"sp": slot["specialist_id"], "ends": slot["ends_at"],
           "starts": slot["starts_at"]})).scalar_one()
    if overlap:
        return JSONResponse({"error": "slot_overlap"}, status_code=409)

    new_id = (await session.execute(text("""
        INSERT INTO appointments (client_login, client_name, slot_id,
                                  status, created_at, cancelled_at)
        VALUES (:login, :name, :slot, 'booked', now(), NULL)
        RETURNING id
    """), {"login": user["login"], "name": client_name or user["full_name"],
           "slot": slot_id})).scalar_one()
    (await session.execute(text(
        "UPDATE slots SET status = 'booked' WHERE id = :id"
    ), {"id": slot_id}))
    await session.commit()
    return JSONResponse({"ok": True, "appointment_id": new_id}, status_code=201)


async def cancel(request: Request, appointment_id: int = Form(...),
                 session: AsyncSession = Depends(get_session)):
    """Отмена записи: слот возвращается в свободные."""
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)
    row = (await session.execute(text("""
        SELECT a.id, a.slot_id, a.status, a.client_login
          FROM appointments a WHERE a.id = :id
    """), {"id": appointment_id})).mappings().first()
    if not row or row["client_login"] != user["login"]:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if row["status"] != "booked":
        return JSONResponse({"error": "already_cancelled"}, status_code=409)
    (await session.execute(text("""
        UPDATE appointments SET status = 'cancelled', cancelled_at = now()
         WHERE id = :id
    """), {"id": appointment_id}))
    (await session.execute(text(
        "UPDATE slots SET status = 'free' WHERE id = :id"
    ), {"id": row["slot_id"]}))
    await session.commit()
    return JSONResponse({"ok": True}, status_code=200)


async def my_appointments(request: Request,
                          session: AsyncSession = Depends(get_session)):
    """Список записей пользователя — постранично."""
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)
    page = max(int(request.query_params.get("page", "1") or 1), 1)
    total = (await session.execute(text("""
        SELECT count(*) FROM appointments WHERE client_login = :l
    """), {"l": user["login"]})).scalar_one()
    rows = (await session.execute(text("""
        SELECT a.id, a.status, a.created_at, sv.name AS service_name,
               sl.starts_at, sl.ends_at, sp.full_name AS specialist_name
          FROM appointments a
          JOIN slots sl ON sl.id = a.slot_id
          JOIN services sv ON sv.id = sl.service_id
          JOIN specialists sp ON sp.id = sl.specialist_id
         WHERE a.client_login = :l
         ORDER BY a.created_at DESC
         LIMIT :limit OFFSET :offset
    """), {"l": user["login"], "limit": PAGE_SIZE,
           "offset": (page - 1) * PAGE_SIZE})).mappings().all()
    return render(request, "appointments.html", user, items=rows, total=total,
                  page=page, pages=(total + PAGE_SIZE - 1) // PAGE_SIZE)


# ─────────────────────────────── сводка ────────────────────────────────────

async def summary(request: Request, session: AsyncSession = Depends(get_session)):
    """Сводка — экран 3: загрузка специалистов за период и доля отмен.

    Считается в коде приложения: записи выгружаются целиком и сворачиваются
    в Python. При малом объёме это «понятно и работает», при рабочем —
    основное узкое место. Именно здесь профиль под нагрузкой покажет
    горячую функцию.
    """
    user = await current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=302)
    days = request.query_params.get("days", "30")
    days = max(min(int(days), 365), 1)
    period_start = datetime.now() - timedelta(days=days)

    rows = (await session.execute(text("""
        SELECT sl.specialist_id, sp.full_name AS specialist_name,
               a.status, a.created_at
          FROM appointments a
          JOIN slots sl ON sl.id = a.slot_id
          JOIN specialists sp ON sp.id = sl.specialist_id
         WHERE a.created_at >= :since
    """), {"since": period_start})).mappings().all()

    # Подсчёт в приложении: словарь на каждого специалиста.
    stats: dict = {}
    for row in rows:
        entry = stats.setdefault(row["specialist_id"], {
            "specialist_id": row["specialist_id"],
            "specialist_name": row["specialist_name"],
            "booked": 0, "cancelled": 0})
        if row["status"] == "cancelled":
            entry["cancelled"] += 1
        else:
            entry["booked"] += 1
    items = []
    total_booked = total_cancelled = 0
    for entry in sorted(stats.values(), key=lambda e: -e["booked"]):
        total = entry["booked"] + entry["cancelled"]
        entry["total"] = total
        entry["cancel_share"] = round(entry["cancelled"] / total * 100, 1) if total else 0.0
        items.append(entry)
        total_booked += entry["booked"]
        total_cancelled += entry["cancelled"]
    grand_total = total_booked + total_cancelled
    return render(request, "summary.html", user, items=items, days=days,
                  total_booked=total_booked, total_cancelled=total_cancelled,
                  grand_total=grand_total,
                  cancel_share=round(total_cancelled / grand_total * 100, 1) if grand_total else 0.0)


# ─────────────────────────── сборка маршрутов ──────────────────────────────

router.add_api_route("/login", login_form, methods=["GET"])
router.add_api_route("/login", login, methods=["POST"])
router.add_api_route("/logout", logout, methods=["POST"])
router.add_api_route("/", home, methods=["GET"])
router.add_api_route("/specialists", specialists, methods=["GET"])
router.add_api_route("/specialists/{specialist_id}", specialist_card, methods=["GET"])
router.add_api_route("/slots", free_slots, methods=["GET"])
router.add_api_route("/book", book, methods=["POST"])
router.add_api_route("/cancel", cancel, methods=["POST"])
router.add_api_route("/appointments", my_appointments, methods=["GET"])
router.add_api_route("/summary", summary, methods=["GET"])
