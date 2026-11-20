"""Генератор данных сервиса записи на приём.

Два объёма: small (малое наполнение) и full (рабочее). Наполнение
детерминированное: random.seed(42), повторный запуск даёт тот же результат.

    python db/seed.py small   # 10 специалистов, 30 услуг… сотни записей
    python db/seed.py full    # рабочее наполнение: 200 000 слотов,
                              # 60 000 записей
    python db/seed.py counts  # сколько записей в каждой таблице сейчас

Схема и данные создаются заново: перед каждым испытанием база наполняется
свежим состоянием (ДЗ 2, п. 2.3).
"""
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import asyncpg

random.seed(42)

DSN = os.environ.get("SEED_DSN",
                     "postgresql://app:changeme@/artem_smirnov?host=/home/z/my-project/kwr")
SCHEMA = os.environ.get("DB_SCHEMA", "artem_smirnov")

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
# Дата зафиксирована, а не now(): от неё отсчитываются слоты и записи,
# иначе данные стареют вместе с календарём и «свободная неделя»
# уезжает в прошлое.

SMALL = dict(specialists=10, services=10, slots=500, appointments=300)
FULL = dict(specialists=200, services=30, slots=200_000, appointments=60_000)
# При 200 специалистах окно 120 дней даёт ~102 тыс. слотов; чтобы выйти
# на 200 тыс., берём 1–2 слота внутри часа (шаг 30 минут).
SLOT_SPLIT_MIN = 30

SPECIALITIES = ["терапевт", "кардиолог", "невролог", "офтальмолог",
                "хирург", "стоматолог", "эндокринолог", "отоларинголог"]
FIRST = ["Анна", "Борис", "Вера", "Глеб", "Дарья", "Ефим", "Жанна", "Захар",
         "Ирина", "Кирилл", "Лидия", "Максим", "Надежда", "Олег", "Полина"]
LAST = ["Смирнов", "Иванов", "Кузнецов", "Соколов", "Морозов", "Волков",
        "Павлов", "Семёнов", "Голубев", "Виноградов", "Богданов", "Воробьёв"]
SERVICE_NAMES = ["Первичный приём", "Повторный приём", "Консультация",
                 "УЗИ", "ЭКГ", "Анализ крови", "Массаж", "Физиотерапия",
                 "Вакцинация", "Профилактический осмотр", "Рентген",
                 "Допплерография", "Спирометрия", "Гастроскопия",
                 "Кардиотокография", "Нейромиография", "Офтальмоскопия",
                 "Лазерная коррекция", "Чистка зубов", "Удаление зуба",
                 "Пломбирование", "Протезирование", "Диагностика",
                 "Биопсия", "Эндоскопия", "Колоноскопия", "МРТ", "КТ",
                 "Лечение каналов", "Реминерализация"]
DURATIONS = [15, 20, 30, 40, 45, 60]


async def recreate(conn):
    await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    await conn.execute(f"CREATE SCHEMA {SCHEMA}")
    sql = open(os.path.join(os.path.dirname(__file__), "schema.sql")).read()
    # По одному оператору на исполнение; комментарии в schema.sql
    # отрезаются (asyncpg simple query не принимает statement с '--'
    # перед первым оператором через подготовленный путь).
    import re as _re
    for stmt in sql.split(";"):
        stripped = _re.sub(r"--[^\n]*", "", stmt).strip()
        if not stripped:
            continue
        stripped = _re.sub(
            r"\b(specialist_services|specialists|services|slots|"
            r"appointments|users)\b",
            lambda m: f"{SCHEMA}.{m.group(1)}", stripped)
        await conn.execute(stripped)


async def fill(conn, volume: dict):
    n_spec = volume["specialists"]
    n_srv = volume["services"]

    # Специалисты.
    specs = [(f"{random.choice(LAST)} {random.choice(FIRST)} "
              f"{random.choice(LAST[0] + 'овичевна')}").strip()
             for _ in range(n_spec)]
    # Уникальные ФИО: фамилия+имя+отчество с индексом при совпадении.
    seen = set()
    for i, name in enumerate(specs):
        base = name if name not in seen else f"{name} {i}"
        seen.add(base)
        await conn.execute(
            f"INSERT INTO {SCHEMA}.specialists (id, full_name, speciality)"
            " VALUES ($1, $2, $3)",
            i + 1, base, SPECIALITIES[i % len(SPECIALITIES)])

    # Услуги.
    for i in range(n_srv):
        name = SERVICE_NAMES[i % len(SERVICE_NAMES)]
        name = name if i < len(SERVICE_NAMES) else f"{name} №{i // len(SERVICE_NAMES) + 1}"
        await conn.execute(
            f"INSERT INTO {SCHEMA}.services (id, name, duration_min)"
            " VALUES ($1, $2, $3)",
            i + 1, name, DURATIONS[i % len(DURATIONS)])

    # Кто какую услугу оказывает: каждый специалист ведёт 3–5 услуг.
    for spec_id in range(1, n_spec + 1):
        for srv_id in sorted(random.sample(range(1, n_srv + 1),
                                            k=min(random.randint(3, 5), n_srv))):
            await conn.execute(
                f"INSERT INTO {SCHEMA}.specialist_services VALUES ($1, $2)",
                spec_id, srv_id)

    # Слоты: рабочие часы 9:00–18:00 по 30 минут. Окно: 90 дней назад
    # и 30 вперёд от NOW. Квота на специалиста раскладывается равномерно
    # по всему окну (шаг по сетке «день, час, полчаса»), иначе первые
    # же дни забирают квоту и будущая неделя остаётся пустой.
    slot_rows = []
    slot_id = 1
    quota = volume["slots"] // n_spec
    for spec_id in range(1, n_spec + 1):
        srvs = await conn.fetch(
            f"SELECT service_id FROM {SCHEMA}.specialist_services"
            " WHERE specialist_id = $1", spec_id)
        # Сетка: рабочий день × час × полчаса, пропуская 25 % «занятых» часов.
        grid = []
        for day in range(-90, 30):
            d = NOW + timedelta(days=day)
            if d.weekday() >= 5:
                continue
            for start_h in range(9, 17):
                if random.random() < 0.25:
                    continue
                for half in (0, SLOT_SPLIT_MIN):
                    grid.append((d, start_h, half))
        step = max(len(grid) // quota, 1)
        picked = [grid[i] for i in range(0, min(len(grid), quota * step), step)]
        for d, start_h, half in picked[:quota]:
            srv = random.choice(srvs)["service_id"]
            dur = DURATIONS[(srv - 1) % len(DURATIONS)]
            starts = d.replace(hour=start_h, minute=half, second=0,
                               microsecond=0)
            ends = starts + timedelta(minutes=dur)
            slot_rows.append((slot_id, spec_id, srv, starts, ends, "free"))
            slot_id += 1

    # Записи: часть слотов забронирована, ~8 % записей отменены.
    appt_rows = []
    appt_id = 1
    chosen = random.sample(range(len(slot_rows)), k=volume["appointments"])
    for idx in chosen:
        slot = slot_rows[idx]
        if slot[3] < NOW:               # прошедший слот — запись была
            status = "cancelled" if random.random() < 0.08 else "booked"
        else:                            # будущий слот — действующая запись
            status = "booked"
        created = slot[3] - timedelta(days=random.randint(0, 7))
        appt_rows.append((appt_id, "demo", "Демо Пользователь", slot[0],
                          status, created,
                          NOW if status == "cancelled" else None))
        # Слот занятой записи не показывается свободным.
        slot_rows[idx] = (slot[0], slot[1], slot[2], slot[3], slot[4],
                          "booked" if status == "booked" else "free")
        appt_id += 1

    # copy_records_to_table не принимает имя со схемой (экранирует его
    # как один идентификатор) — поэтому перед ним выставляется search_path.
    await conn.execute(f"SET search_path TO {SCHEMA}")
    await conn.copy_records_to_table(
        "slots",
        columns=["id", "specialist_id", "service_id", "starts_at",
                 "ends_at", "status"],
        records=slot_rows)
    await conn.copy_records_to_table(
        "appointments",
        columns=["id", "client_login", "client_name", "slot_id", "status",
                 "created_at", "cancelled_at"],
        records=appt_rows)
    # Нумераторы за серийными ключами.
    await conn.execute(
        f"SELECT setval('{SCHEMA}.slots_id_seq', (SELECT max(id) FROM {SCHEMA}.slots))")
    await conn.execute(
        f"SELECT setval('{SCHEMA}.appointments_id_seq', (SELECT max(id) FROM {SCHEMA}.appointments))")


async def counts(conn):
    for table in ("specialists", "services", "specialist_services",
                  "slots", "appointments", "users"):
        n = await conn.fetchval(f"SELECT count(*) FROM {SCHEMA}.{table}")
        print(f"{table:20s} {n}")


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "counts"
    conn = await asyncpg.connect(DSN)
    await conn.execute(f"SET search_path TO {SCHEMA}")
    if mode in ("small", "full"):
        await recreate(conn)
        await fill(conn, SMALL if mode == "small" else FULL)
        print(f"наполнение {mode}: готово")
    await counts(conn)
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
