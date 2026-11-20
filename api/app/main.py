"""Сервис записи на приём — учебный сервис курсовой работы.

Дисциплина «Оптимизация клиент-серверных приложений», НИТУ «МИСИС», вариант 3.
Хранит расписание специалистов слотами: по выбранной услуге показывает
свободные слоты подходящей длительности и бронирует один из них, не допуская
наложения на существующие записи. Отмена записи возвращает слот в свободные.
Сводка показывает загрузку специалистов за период и долю отменённых записей.
"""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import pages
from .db import engine
from .dbstats import attach

attach(engine)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

BASE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="Сервис записи на приём", docs_url=None, redoc_url=None,
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
pages.templates = Jinja2Templates(directory=str(BASE / "templates"))
app.include_router(pages.router)


@app.middleware("http")
async def response_time(request, call_next):
    """Заголовок X-Response-Time-ms — то, чем снимаются все замеры."""
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
    return response
