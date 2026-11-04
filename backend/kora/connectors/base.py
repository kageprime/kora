"""Source connector interface.

Every data source (OpenAlex, Open Library, Wikidata, later AJOL, university
OAI-PMH repositories, ...) implements this protocol. Adding a new source means
writing one class; the resolver and aggregator stay unchanged.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kora.http import HttpClient
from kora.models import Person, RawPerson, RawWork


@runtime_checkable
class SourceConnector(Protocol):
    name: str

    async def search_people(self, query: str) -> list[RawPerson]:
        """Candidate identities matching a free-text person query."""
        ...

    async def works_by(self, person: Person) -> list[RawWork]:
        """Works authored by the (already resolved) canonical person."""
        ...

    async def works_about(self, person: Person) -> list[RawWork]:
        """Works about / discussing the person (criticism, theses, reviews)."""
        ...


class BaseConnector:
    name = "base"

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def search_people(self, query: str) -> list[RawPerson]:
        return []

    async def works_by(self, person: Person) -> list[RawWork]:
        return []

    async def works_about(self, person: Person) -> list[RawWork]:
        return []

    async def sample_titles(self, source_id: str, limit: int = 50) -> list[str]:
        """Titles of a source identity's top works (used to corroborate grey matches)."""
        return []
