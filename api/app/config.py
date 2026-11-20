"""Подключение к базе данных и настройки.

Единственная точка, где приложение знает, где база: переменные окружения
из .env. Схема своя у каждого студента: artem_smirnov.

Пул соединений настраивается переменными: APP_POOL_SIZE — размер пула.
Он вынесен в переменную сознательно — в ДЗ 2 с ним ставится опыт
(меньше пул — длиннее ожидание соединения, больше отказов).
"""
from collections.abc import AsyncIterator

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://app:changeme@localhost/artem_smirnov"
    db_host: str = "/home/z/my-project/kwr"  # unix-сокет стенда разработки
    app_port: int = 8080

    db_schema: str = "artem_smirnov"

    # Пул соединений к базе. Размер вынесен в переменную окружения: в ДЗ 2
    # ставится опыт с уменьшенным пулом, код не меняется.
    db_pool_size: int = 10
    db_pool_timeout: float = 5.0
    db_command_timeout: float = 25.0

    log_level: str = "WARNING"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
