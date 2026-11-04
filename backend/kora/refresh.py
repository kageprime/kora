"""Refresh stored scholar profiles without silently changing their identity.

The refresh job is deliberately conservative: a live resolution may return a
different top person than the one stored. In that case the job records the
failure and keeps the existing profile instead of overwriting it or creating a
duplicate scholar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kora.aggregator import Aggregator
from kora.storage.repository import (
    list_refresh_candidates,
    mark_refresh_failed,
    save_profile,
    scholar_key,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshResult:
    scholar_id: int
    display_name: str
    ok: bool
    work_count: int = 0
    error: str | None = None


async def refresh_scholars(
    session_factory: async_sessionmaker[AsyncSession],
    aggregator: Aggregator,
    *,
    limit: int = 50,
    stale_hours: int | None = None,
    scholar_ids: list[int] | None = None,
) -> list[RefreshResult]:
    """Refresh a batch of stored scholars and report one result per scholar."""
    async with session_factory() as session:
        candidates: list[dict[str, Any]] = await list_refresh_candidates(
            session,
            limit=limit,
            stale_hours=stale_hours,
            scholar_ids=scholar_ids,
        )

    results: list[RefreshResult] = []
    for candidate in candidates:
        scholar_id = candidate["id"]
        display_name = candidate["display_name"]
        try:
            profile = await aggregator.build_profile(
                candidate["query"], include_about=True
            )
            if profile is None:
                raise LookupError(
                    f"no person found for stored query {candidate['query']!r}"
                )

            expected = candidate["scholar_key"]
            actual = scholar_key(profile.person)
            if actual != expected:
                raise ValueError(
                    "identity changed "
                    f"({expected} -> {actual}); refusing to overwrite"
                )

            async with session_factory() as session:
                await save_profile(session, profile)
            results.append(
                RefreshResult(
                    scholar_id=scholar_id,
                    display_name=display_name,
                    ok=True,
                    work_count=len(profile.works),
                )
            )
            log.info("refreshed %s (%s works)", display_name, len(profile.works))
        except Exception as exc:  # noqa: BLE001 - one scholar must not stop the batch
            message = str(exc).splitlines()[0][:500] or type(exc).__name__
            log.warning("refresh failed for %s: %s", display_name, message)
            async with session_factory() as session:
                await mark_refresh_failed(session, scholar_id, message)
            results.append(
                RefreshResult(
                    scholar_id=scholar_id,
                    display_name=display_name,
                    ok=False,
                    error=message,
                )
            )
    return results
