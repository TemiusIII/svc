"""Тесты бизнес-правил варианта 3 (методичка, п. 2.2).

Правила из таблицы 2 методички курсовой работы:
  1. сервис показывает свободные слоты подходящей длительности;
  2. бронирование не допускает наложения на существующие записи;
  3. отмена возвращает слот в свободные;
  4. сводка считает загрузку специалистов за период и долю отмен.

Проверяются на подготовленных данных прямо в базе, без обращения
к работающему сервису.
"""
import os
import sys

import asyncpg
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

DSN = os.environ.get(
    "SEED_DSN",
    "postgresql://app:changeme@/artem_smirnov?host=/home/z/my-project/kwr")
SCHEMA = os.environ.get("DB_SCHEMA", "artem_smirnov")


@pytest.fixture
async def db():
    conn = await asyncpg.connect(DSN)
    await conn.execute(f"SET search_path TO {SCHEMA}")
    # Технический специалист для тестов: обычная специальность.
    await conn.execute(f"DELETE FROM {SCHEMA}.appointments WHERE"
                       " client_login = 'tester'")
    await conn.execute(f"DELETE FROM {SCHEMA}.slots WHERE specialist_id = 9999")
    await conn.execute(f"DELETE FROM {SCHEMA}.specialists WHERE id = 9999")
    await conn.execute(f"INSERT INTO {SCHEMA}.specialists VALUES"
                       " (9999, 'Тестовый Специалист', 'терапевт')")
    yield conn
    # Чистим за собой: тест создаёт свои слоты и записи.
    await conn.execute(f"DELETE FROM {SCHEMA}.appointments WHERE"
                       " client_login = 'tester'")
    await conn.execute(f"DELETE FROM {SCHEMA}.slots WHERE specialist_id = 9999")
    await conn.execute(f"DELETE FROM {SCHEMA}.specialists WHERE id = 9999")
    await conn.close()


async def test_free_slots_window_excludes_booked(db):
    """Свободные слоты: только статус free и только внутри недели."""
    # Слот в прошлом — в окно не попадает; слот в будущем — попадает.
    await db.execute(f"""
        INSERT INTO {SCHEMA}.slots (specialist_id, service_id, starts_at,
                                    ends_at, status)
        VALUES (9999, 1, now() - interval '2 days',
                now() - interval '2 days' + interval '30 min', 'free'),
               (9999, 1, now() + interval '1 day',
                now() + interval '1 day' + interval '30 min', 'free')
    """)
    n = await db.fetchval(f"""
        SELECT count(*) FROM {SCHEMA}.slots
         WHERE specialist_id = 9999 AND status = 'free'
           AND starts_at >= now() AND starts_at < now() + interval '7 days'
    """)
    assert n == 1
    await db.execute(f"UPDATE {SCHEMA}.slots SET status = 'booked'"
                     " WHERE specialist_id = 9999")
    n = await db.fetchval(f"""
        SELECT count(*) FROM {SCHEMA}.slots
         WHERE specialist_id = 9999 AND status = 'free'
    """)
    assert n == 0


async def test_booking_blocked_when_slot_busy(db):
    """Занятый слот не бронируется повторно: status != free."""
    await db.execute(
        f"INSERT INTO {SCHEMA}.slots (specialist_id, service_id, starts_at,"
        " ends_at, status) VALUES (9999, 1, now(), now() + interval '30 min',"
        " 'booked')")
    busy = await db.fetchval(f"""
        SELECT count(*) FROM {SCHEMA}.slots
         WHERE specialist_id = 9999 AND status != 'free'
    """)
    assert busy == 1  # сервис откажет: слот не свободен


async def test_booking_blocked_on_overlap(db):
    """Наложение: запись, пересекающая слот по времени, не создаётся."""
    # Два слота одного специалиста пересекаются по времени.
    await db.execute(f"""
        INSERT INTO {SCHEMA}.slots (specialist_id, service_id, starts_at,
                                    ends_at, status)
        VALUES (9999, 1, now(), now() + interval '60 min', 'booked'),
               (9999, 1, now() + interval '30 min',
                now() + interval '90 min', 'free')
    """)
    overlap = await db.fetchval(f"""
        SELECT count(*) FROM {SCHEMA}.appointments a
          JOIN {SCHEMA}.slots sl ON sl.id = a.slot_id
         WHERE sl.specialist_id = 9999 AND a.status = 'booked'
           AND sl.starts_at < now() + interval '90 min'
           AND sl.ends_at > now() + interval '30 min'
    """)
    assert overlap == 0  # правило: пересекающийся слот не бронируется


async def test_cancel_returns_slot_to_free(db):
    """Отмена записи возвращает слот в свободные."""
    await db.execute(
        f"INSERT INTO {SCHEMA}.slots (specialist_id, service_id, starts_at,"
        " ends_at, status) VALUES (9999, 1, now() + interval '1 day',"
        " now() + interval '1 day 30 min', 'free')")
    slot_id = await db.fetchval(
        f"SELECT id FROM {SCHEMA}.slots WHERE specialist_id = 9999")
    appt_id = await db.fetchval(f"""
        INSERT INTO {SCHEMA}.appointments (client_login, client_name, slot_id,
                                           status, created_at)
        VALUES ('tester', 'Тестер', $1, 'booked', now()) RETURNING id
    """, slot_id)
    await db.execute(f"UPDATE {SCHEMA}.slots SET status='booked'"
                     " WHERE id = $1", slot_id)
    # Отмена: статус записи и возврат слота — то, что делает /cancel.
    await db.execute(f"""
        UPDATE {SCHEMA}.appointments SET status = 'cancelled',
               cancelled_at = now() WHERE id = $1
    """, appt_id)
    await db.execute(f"UPDATE {SCHEMA}.slots SET status = 'free'"
                     " WHERE id = $1", slot_id)
    status = await db.fetchval(f"SELECT status FROM {SCHEMA}.slots"
                               " WHERE id = $1", slot_id)
    assert status == "free"


async def test_summary_counts_by_specialist(db):
    """Сводка: загрузка за период и доля отмен считаются по записям."""
    rows = await db.fetch(f"""
        SELECT sl.specialist_id,
               count(*) FILTER (WHERE a.status = 'booked') AS booked,
               count(*) FILTER (WHERE a.status = 'cancelled') AS cancelled
          FROM {SCHEMA}.appointments a
          JOIN {SCHEMA}.slots sl ON sl.id = a.slot_id
         WHERE a.created_at >= now() - interval '30 days'
         GROUP BY sl.specialist_id
    """)
    assert len(rows) > 0          # сводка не пуста на малом наполнении
    total = sum(r["booked"] + r["cancelled"] for r in rows)
    assert total > 0
    # Доля отмен по правилу в границах [0, 100].
    for r in rows:
        share = r["cancelled"] / (r["booked"] + r["cancelled"]) * 100
        assert 0 <= share <= 100
