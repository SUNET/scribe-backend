# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin
#
# This file is part of Sunet Scribe.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re

from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from sqlalchemy import create_engine, schema
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel
from typing import AsyncGenerator, Generator
from utils.log import get_logger
from utils.settings import get_settings


log = get_logger()
settings = get_settings()


def make_async_url(url: str) -> str:
    """
    Convert a sync database URL to its async driver equivalent.

    postgresql+psycopg2://... -> postgresql+asyncpg://...
    postgresql://...          -> postgresql+asyncpg://...
    sqlite:///...             -> sqlite+aiosqlite:///...
    """

    url = re.sub(r"^postgresql(\+psycopg2)?://", "postgresql+asyncpg://", url)
    url = re.sub(r"^sqlite:///", "sqlite+aiosqlite:///", url)
    return url


def make_sync_url(url: str) -> str:
    """
    Ensure a database URL uses a sync driver.

    postgresql+asyncpg://... -> postgresql+psycopg2://...
    sqlite+aiosqlite:///...  -> sqlite:///...
    """

    url = re.sub(r"^postgresql(\+asyncpg)?://", "postgresql+psycopg2://", url)
    url = re.sub(r"^sqlite\+aiosqlite:///", "sqlite:///", url)
    return url


# ---------------------------------------------------------------------------
# Sync engine / session  (kept for APScheduler background tasks + Alembic)
# ---------------------------------------------------------------------------

@lru_cache
def get_sessionmaker() -> sessionmaker:
    """
    Get a SQLAlchemy sessionmaker.
    Uses lru_cache to ensure only one instance is created.

    Returns:
        sessionmaker: A SQLAlchemy sessionmaker instance.
    """

    if not settings.API_DATABASE_URL.startswith("sqlite"):
        pool_opts = {
            "pool_size": 3,       # 3 × 8 = 24 base
            "max_overflow": 2,    # burst to 5 × 8 = 40 max
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        }
    else:
        pool_opts = {}

    sync_url = make_sync_url(settings.API_DATABASE_URL)
    engine = create_engine(sync_url, **pool_opts)

    with engine.connect() as connection:
        if connection.dialect.name != "sqlite":
            if not connection.dialect.has_schema(connection, "transcribe"):
                log.info("Creating 'transcribe' schema in the database.")
                connection.execute(schema.CreateSchema("transcribe"))
                connection.commit()

    SQLModel.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Provide a transactional scope around a series of operations.

    Yields:
        Session: A SQLAlchemy session.
    """

    db_session_factory = get_sessionmaker()
    session: Session = db_session_factory()

    try:
        yield session
    except Exception:
        log.error("Session rollback because of exception", exc_info=True)
        session.rollback()
        raise
    finally:
        session.commit()
        session.close()


# ---------------------------------------------------------------------------
# Async engine / session  (used by FastAPI endpoints)
# ---------------------------------------------------------------------------

_async_sessionmaker_instance: async_sessionmaker[AsyncSession] | None = None


async def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """
    Get an async SQLAlchemy sessionmaker (singleton).
    Cannot use @lru_cache because the first call performs async I/O.
    """

    global _async_sessionmaker_instance
    if _async_sessionmaker_instance is not None:
        return _async_sessionmaker_instance

    async_url = make_async_url(settings.API_DATABASE_URL)

    if not async_url.startswith("sqlite"):
        pool_opts = {
            "pool_size": 3,
            "max_overflow": 2,
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        }
    else:
        pool_opts = {}

    engine = create_async_engine(async_url, **pool_opts)

    async with engine.begin() as conn:
        if not async_url.startswith("sqlite"):
            has_schema = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.has_schema(sync_conn, "transcribe")
            )
            if not has_schema:
                log.info("Creating 'transcribe' schema in the database.")
                await conn.execute(schema.CreateSchema("transcribe"))

        await conn.run_sync(SQLModel.metadata.create_all)

    _async_sessionmaker_instance = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    return _async_sessionmaker_instance


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an async transactional scope around a series of operations.

    Yields:
        AsyncSession: An async SQLAlchemy session.
    """

    factory = await get_async_sessionmaker()
    session: AsyncSession = factory()

    try:
        yield session
    except Exception:
        log.error("Async session rollback because of exception", exc_info=True)
        await session.rollback()
        raise
    finally:
        await session.commit()
        await session.close()
