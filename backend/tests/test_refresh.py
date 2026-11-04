"""Refresh-job tests with a fake source layer and SQLite."""

from __future__ import annotations

import copy

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from kora.refresh import refresh_scholars
from kora.storage.repository import list_scholars, save_profile
from kora.storage.tables import Base


class FakeAggregator:
    def __init__(self, profile=None, error: Exception | None = None):
        self.profile = profile
        self.error = error
        self.calls: list[str] = []

    async def build_profile(self, query, pick=0, include_about=True):
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return self.profile


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'refresh-test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed(factory, profile) -> int:
    async with factory() as session:
        return await save_profile(session, profile)


async def test_refresh_success_updates_snapshot(session_factory, sample_profile):
    scholar_id = await _seed(session_factory, sample_profile)
    aggregator = FakeAggregator(sample_profile)

    results = await refresh_scholars(
        session_factory, aggregator, scholar_ids=[scholar_id]
    )

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].work_count == 4
    assert aggregator.calls == ["Chinua Achebe"]

    async with session_factory() as session:
        summary = (await list_scholars(session))[0]
        assert summary["refresh_error"] is None
        assert summary["refreshed_at"] is not None


async def test_refresh_failure_keeps_existing_profile(session_factory, sample_profile):
    scholar_id = await _seed(session_factory, sample_profile)
    aggregator = FakeAggregator(profile=None)

    results = await refresh_scholars(
        session_factory, aggregator, scholar_ids=[scholar_id]
    )

    assert len(results) == 1
    assert results[0].ok is False
    assert "no person found" in (results[0].error or "")

    async with session_factory() as session:
        summary = (await list_scholars(session))[0]
        assert summary["work_count"] == 3
        assert "no person found" in (summary["refresh_error"] or "")
        assert summary["refreshed_at"] is not None


async def test_refresh_refuses_identity_change(session_factory, sample_profile):
    scholar_id = await _seed(session_factory, sample_profile)
    changed = copy.deepcopy(sample_profile)
    changed.person.identities[0].person.source_id = "Q999999"
    aggregator = FakeAggregator(changed)

    results = await refresh_scholars(
        session_factory, aggregator, scholar_ids=[scholar_id]
    )

    assert results[0].ok is False
    assert "identity changed" in (results[0].error or "")
    async with session_factory() as session:
        summaries = await list_scholars(session)
        assert len(summaries) == 1
        assert summaries[0]["display_name"] == "Chinua Achebe"
        assert "identity changed" in (summaries[0]["refresh_error"] or "")
