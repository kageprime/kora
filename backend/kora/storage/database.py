"""Database settings and async engine helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from kora import __version__
from kora.aggregator import default_cache_dir
from kora.storage.tables import Base

DEFAULT_DATABASE_URL = "postgresql+psycopg://kora:kora@localhost:5432/kora"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _env_cache_dir() -> Path | None:
    raw = os.getenv("KORA_CACHE_DIR")
    if raw is None:
        return default_cache_dir()
    if raw.strip().casefold() in {"", "none", "off", "0"}:
        return None
    return Path(raw).expanduser()


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    auto_create_schema: bool = True
    cache_dir: Path | None = field(default_factory=default_cache_dir)
    title: str = "Kora API"
    version: str = __version__

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("KORA_DATABASE_URL", DEFAULT_DATABASE_URL),
            auto_create_schema=_env_bool("KORA_AUTO_CREATE_SCHEMA", True),
            cache_dir=_env_cache_dir(),
        )


def build_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict = {"pool_pre_ping": True}
    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(settings.database_url, **kwargs)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def database_ok(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
