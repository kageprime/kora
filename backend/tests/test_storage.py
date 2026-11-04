"""Persistence round-trip tests against SQLite (no Postgres required)."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from kora.models import Relation, WorkRole
from kora.storage import tables as t
from kora.storage.repository import (
    get_profile,
    list_scholars,
    save_profile,
    scholar_key,
    work_key,
)
from kora.storage.tables import Base


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'kora-test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_save_load_and_idempotent_upsert(session_factory, sample_profile):
    async with session_factory() as session:
        first_id = await save_profile(session, sample_profile)
        second_id = await save_profile(session, sample_profile)
        assert first_id == second_id
        assert scholar_key(sample_profile.person) == "wikidata:Q302910"

        scholar_count = await session.scalar(select(func.count()).select_from(t.Scholar))
        assert scholar_count == 1

        loaded = await get_profile(session, first_id)
        assert loaded is not None
        assert loaded.person.display_name == "Chinua Achebe"
        assert loaded.person.birth_year == 1930
        assert len(loaded.person.identities) == 3
        assert any(i.person.alt_names for i in loaded.person.identities)
        assert loaded.query == "Chinua Achebe"
        assert loaded.bio == sample_profile.bio
        assert loaded.raw_work_count == 4
        assert loaded.alternatives[0].display_name == "Chinua Achebe (critic)"
        assert loaded.flagged[0].title == "A Future Book"

        works = {work.title: work for work in loaded.works}
        assert set(works) == {
            "Things Fall Apart",
            "Winds of Change",
            "Tapestry",
            "Conversations with Chinua Achebe",
        }
        things = works["Things Fall Apart"]
        assert things.role == WorkRole.AUTHOR
        assert things.relation == Relation.BY
        assert things.sources == ["openalex", "openlibrary"]
        assert len(things.records) == 2
        assert len(things.links) == 3
        assert any(record.links for record in things.records)
        assert things.cited_by == 1200
        assert works["Winds of Change"].role == WorkRole.EDITOR
        assert works["Tapestry"].role == WorkRole.CONTRIBUTOR
        assert works["Conversations with Chinua Achebe"].relation == Relation.ABOUT
        assert all(
            record.relation == Relation.ABOUT
            for record in works["Conversations with Chinua Achebe"].records
        )
        assert work_key(things) == work_key(sample_profile.works[0])

    async with session_factory() as session:
        summaries = await list_scholars(session)
        assert len(summaries) == 1
        assert summaries[0]["display_name"] == "Chinua Achebe"
        assert summaries[0]["work_count"] == 3
        assert summaries[0]["about_count"] == 1
