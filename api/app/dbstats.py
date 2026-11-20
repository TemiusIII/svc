"""Счётчик обращений к базе для разложения времени по слоям (ДЗ 1, п. 2.6).

Собственные отметки времени вокруг обращений к базе — способ прямо
из методички. Хук на движке считает выполнения запросов и суммарное время
внутри базы; обнуляется перед операцией и читается сразу после.
Включается переменной DB_STATS=1 — под нагрузкой ДЗ 2 счётчик выключен,
чтобы не портить замеры.
"""
import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

_queries = 0
_db_time = 0.0


def reset() -> None:
    global _queries, _db_time
    _queries, _db_time = 0, 0.0


def snapshot() -> dict:
    return {"queries": _queries, "db_ms": round(_db_time * 1000.0, 1)}


def attach(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        context._kwr_start = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        global _queries, _db_time
        _queries += 1
        _db_time += time.perf_counter() - context._kwr_start
