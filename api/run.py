"""Запуск сервиса: uvicorn на APP_PORT (по умолчанию 8080)."""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1",
                port=settings.app_port, log_level="warning")
