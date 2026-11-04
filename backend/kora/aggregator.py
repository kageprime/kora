"""Orchestrates the live fan-out: search -> resolve -> fetch works -> merge."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar
from urllib.parse import quote

from kora.connectors import (
    BaseConnector,
    OpenAlexConnector,
    OpenLibraryConnector,
    WikidataConnector,
)
from kora.http import HttpClient
from kora.models import Confidence, Person, Profile, RawPerson, RawWork, Relation, WorkRole
from kora.resolve import (
    Disambiguator,
    flag_suspect_records,
    is_credible_alternative,
    merge_works,
    promote_by_title_overlap,
    reclassify_reviews,
    resolve_people,
    title_overlap,
)

log = logging.getLogger(__name__)
T = TypeVar("T")

DEFAULT_TIMEOUT = 25.0


class Aggregator:
    max_grey_checks = 6

    def __init__(
        self,
        http: HttpClient,
        connectors: list[BaseConnector] | None = None,
        disambiguator: Disambiguator | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.http = http
        self.connectors = connectors or [
            WikidataConnector(http),
            OpenAlexConnector(http),
            OpenLibraryConnector(http),
        ]
        self.disambiguator = disambiguator
        self.timeout = timeout
        self.status: dict[str, str] = {}

    @staticmethod
    def _supports(connector: BaseConnector, method: str) -> bool:
        """Skip the base-class no-op so source status stays meaningful."""
        return getattr(type(connector), method) is not getattr(BaseConnector, method)

    async def _guard(self, label: str, fn: Callable[[], Awaitable[list[T]]]) -> list[T]:
        """Run one source call with a timeout; never let one source break the search."""
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(fn(), self.timeout)
            self.status[label] = f"ok ({len(result)} in {time.perf_counter() - start:.1f}s)"
            return result
        except Exception as exc:  # noqa: BLE001 - report and degrade gracefully
            msg = str(exc).splitlines()[0][:120] if str(exc) else type(exc).__name__
            self.status[label] = f"failed: {msg}"
            log.warning("%s failed: %s", label, msg)
            return []

    async def find_people(self, query: str) -> list[Person]:
        results = await asyncio.gather(
            *(self._guard(f"{c.name}.people", lambda c=c: c.search_people(query)) for c in self.connectors)
        )
        candidates: list[RawPerson] = [p for batch in results for p in batch]
        return resolve_people(query, candidates, self.disambiguator)

    async def build_profile(self, query: str, pick: int = 0, include_about: bool = True) -> Profile | None:
        self.status = {}
        people = await self.find_people(query)
        if not people:
            return None
        pick = min(max(pick, 0), len(people) - 1)
        person = people[pick]

        tasks = [
            self._guard(f"{c.name}.by", lambda c=c: c.works_by(person))
            for c in self.connectors
            if self._supports(c, "works_by")
        ]
        if include_about:
            tasks += [
                self._guard(f"{c.name}.about", lambda c=c: c.works_about(person))
                for c in self.connectors
                if self._supports(c, "works_about")
            ]
        bio_task = self._wikipedia_summary(person)
        *batches, bio = await asyncio.gather(*tasks, bio_task)
        records: list[RawWork] = [w for batch in batches for w in batch]
        records += await self._corroborate_grey(person, records)
        raw_count = len(records)
        records, flagged = flag_suspect_records(person, records)
        reclassify_reviews(records, person.display_name)
        works = merge_works(records)
        works.sort(
            key=lambda w: (
                w.relation != Relation.BY,
                w.role == WorkRole.CONTRIBUTOR,
                -(w.edition_count + w.cited_by),
            )
        )
        hub_names = [person.display_name]
        hub_names += [
            n
            for ident in person.identities
            for n in [ident.person.name, *ident.person.alt_names]
        ]

        return Profile(
            query=query,
            person=person,
            works=works,
            alternatives=[
                p for i, p in enumerate(people)
                if i != pick and is_credible_alternative(p, query, hub_names)
            ][:8],
            bio=bio[0] if bio else None,
            bio_url=bio[1] if bio else None,
            source_status=dict(self.status),
            raw_work_count=raw_count,
            flagged=flagged,
        )

    async def _corroborate_grey(self, person: Person, confirmed: list[RawWork]) -> list[RawWork]:
        """Promote grey identities that share distinctive titles with the confirmed
        bibliography, then fetch their works. Returns the additional records."""
        by_name = {c.name: c for c in self.connectors}
        grey = sorted(
            (i for i in person.identities
             if i.confidence == Confidence.GREY and i.person.source in by_name),
            key=lambda i: -(i.person.works_count or 0),
        )[: self.max_grey_checks]
        if not grey or not confirmed:
            return []

        samples = await asyncio.gather(
            *(
                self._guard(
                    f"{i.person.source}.corroborate.{i.person.source_id}",
                    lambda i=i: by_name[i.person.source].sample_titles(i.person.source_id),
                )
                for i in grey
            )
        )
        promoted = [
            ident for ident, titles in zip(grey, samples)
            if promote_by_title_overlap(ident, title_overlap(confirmed, titles))
        ]
        if not promoted:
            return []

        extra_tasks = []
        for source in {i.person.source for i in promoted}:
            sub = Person(
                display_name=person.display_name,
                identities=[i for i in promoted if i.person.source == source],
            )
            extra_tasks.append(
                self._guard(f"{source}.by.promoted", lambda s=source, sub=sub: by_name[s].works_by(sub))
            )
        batches = await asyncio.gather(*extra_tasks)
        return [w for b in batches for w in b]

    async def _wikipedia_summary(self, person: Person) -> tuple[str, str] | None:
        if not person.wikipedia_title or self.http is None:
            return None
        title = quote(person.wikipedia_title.replace(" ", "_"), safe="")
        try:
            data = await self.http.get_json(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
            )
            url = ((data.get("content_urls") or {}).get("desktop") or {}).get("page", "")
            self.status["wikipedia.bio"] = "ok"
            return data.get("extract", ""), url
        except Exception as exc:  # noqa: BLE001
            self.status["wikipedia.bio"] = f"failed: {exc}"
            return None


def default_cache_dir() -> Path:
    return Path(__file__).resolve().parent.parent / ".cache"
