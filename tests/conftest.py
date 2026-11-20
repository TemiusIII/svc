"""Обвязка тестов: приложение поднимается в тестовом режиме.

Тесты двух видов (методичка ДЗ 1, п. 2.2):
  * бизнес-правила — логика варианта без обращения к сервису;
  * операции интерфейса — поведение контракта живого приложения.

Приложение поднимается на порту 8900 с малым наполнением в базе;
тесты интерфейса ходят к нему по HTTP от имени демо-учётной записи.
"""
import asyncio
import os

import httpx
import pytest_asyncio

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8900")
DSN = os.environ.get(
    "SEED_DSN",
    "postgresql://app:changeme@/artem_smirnov?host=/home/z/my-project/kwr")


@pytest_asyncio.fixture
async def app():
    """Поднять приложение для каждого теста (просто и надёжно)."""
    proc = await asyncio.create_subprocess_exec(
        "python3", "api/run.py",
        env={**os.environ, "APP_PORT": "8900"},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.STDOUT)
    await asyncio.sleep(3)
    yield
    proc.terminate()


@pytest_asyncio.fixture
async def client(app):
    """Гость: без входа."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0,
                                 follow_redirects=False) as c:
        yield c


@pytest_asyncio.fixture
async def demo(app):
    """Вошедший пользователь demo."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0,
                                 follow_redirects=False) as c:
        await c.post("/login", data={"login": "demo", "password": "demo"})
        yield c
