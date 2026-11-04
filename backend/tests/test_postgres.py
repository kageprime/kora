"""Postgres-only persistence checks, enabled by KORA_TEST_DATABASE_URL.

CI points this at a disposable database. The fixture recreates the schema, so
never set KORA_TEST_DATABASE_URL to a database you care about.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from kora.models import Relation
from kora.storage.repository import (
    get_profile,
    list_review_items,
    save_profile,
    update_review_item,
)
from kora.storage.tables import Base

pytestmark = pytest.mark.postgres

DATABASE_URL = os.getenv("KORA_TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def session_factory():
    if not DATABASE_URL:
        pytest.skip("set KORA_TEST_DATABASE_URL to run Postgres tests")
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_postgres_roundtrip_and_review_queue(session_factory, sample_profile):
    async with session_factory() as session:
        scholar_id = await save_profile(session, sample_profile)
        loaded = await get_profile(session, scholar_id)
        assert loaded is not None
        assert loaded.person.display_name == "Chinua Achebe"
        assert len(loaded.person.identities) == 4
        assert len(loaded.works) == 4
        assert any(work.relation == Relation.ABOUT for work in loaded.works)

        items, total = await list_review_items(session)
        assert total == 2
        item = next(item for item in items if item.kind == "grey_identity")
        updated = await update_review_item(
            session, item.id, status="resolved", note="ORCID confirmed"
        )
        assert updated is not None
        assert updated.status == "resolved"
        assert updated.resolved_at is not None
