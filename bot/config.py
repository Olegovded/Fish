"""Конфигурация бота. Все значения читаются из переменных окружения.

Ничего секретного в коде не хранится — токен и прочее задаются через .env
(см. .env.example). Это упрощает и локальный запуск, и деплой.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(
            f"Не задана обязательная переменная окружения {name}. "
            f"Скопируйте .env.example в .env и заполните её."
        )
    return value or ""


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    # Размер ячейки сетки в метрах. Локация рыбака всегда округляется до центра
    # ячейки — точный пин наружу никогда не отдаётся (принцип из брифа).
    grid_size_m: int
    # Публичный HTTPS-URL мини-приложения (Telegram WebApp работает только по https).
    # Для MVP можно оставить пустым — тогда кнопка «Карта» не показывается,
    # а дневник отдаётся списком прямо в чате.
    webapp_url: str
    # Хост/порт для локального веб-сервера мини-приложения.
    web_host: str
    web_port: int
    # Имя бота для водяного знака на карточке шеринга.
    bot_username: str

    @staticmethod
    def load() -> "Config":
        try:
            from dotenv import load_dotenv

            load_dotenv(BASE_DIR / ".env")
        except ImportError:
            pass  # dotenv не обязателен, если переменные заданы в окружении
        return Config(
            bot_token=_get("BOT_TOKEN", required=True),
            db_path=_get("DB_PATH", str(BASE_DIR / "fishing.db")),
            grid_size_m=int(_get("GRID_SIZE_M", "1000")),
            webapp_url=_get("WEBAPP_URL", ""),
            web_host=_get("WEB_HOST", "0.0.0.0"),
            web_port=int(_get("WEB_PORT", "8080")),
            bot_username=_get("BOT_USERNAME", "fishing_bot"),
        )
