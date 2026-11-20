"""Движок SQLAlchemy и фабрика сессий."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=0,
    # Ожидание соединения короче, чем таймаут генератора нагрузки:
    # иначе запрос виснет до конца ступени и отказ в отчёт не попадает.
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {"search_path": f"{settings.db_schema},public"},
        "command_timeout": settings.db_command_timeout,
    },
)

Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with Session() as session:
        yield session
