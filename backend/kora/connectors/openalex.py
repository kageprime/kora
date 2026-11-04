"""OpenAlex connector: scholarly works, disambiguated (but often split) authors.

Docs: https://docs.openalex.org. Set OPENALEX_API_KEY for reliable access;
anonymous `search` requests may be rate-limited under load, so author lookup
falls back to the autocomplete endpoint.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from kora.connectors.base import BaseConnector
from kora.models import (
    AccessLink,
    Person,
    RawPerson,
    RawWork,
    Relation,
    WorkCategory,
    WorkRole,
)
from kora.normalize import (
    is_anthology_title,
    is_collective_author,
    is_edited_anthology_title,
    normalize_doi,
    normalize_language,
    years_in_names,
)

log = logging.getLogger(__name__)

BASE = "https://api.openalex.org"
WORK_FIELDS = (
    "id,doi,display_name,publication_year,type,primary_location,open_access,"
    "cited_by_count,authorships,language"
)

TYPE_MAP = {
    "book": WorkCategory.BOOK,
    "dissertation": WorkCategory.THESIS,
    "dataset": WorkCategory.DATASET,
    "article": WorkCategory.ARTICLE,
    "book-chapter": WorkCategory.ARTICLE,
    "review": WorkCategory.ARTICLE,
    "book-review": WorkCategory.ARTICLE,
    "preprint": WorkCategory.ARTICLE,
    "letter": WorkCategory.ARTICLE,
    "editorial": WorkCategory.ARTICLE,
    "report": WorkCategory.ARTICLE,
    "reference-entry": WorkCategory.ARTICLE,
}


def short_id(openalex_id: str) -> str:
    """'https://openalex.org/A123' -> 'A123'."""
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


class OpenAlexConnector(BaseConnector):
    name = "openalex"
    max_works = 600

    def _params(self, **params: Any) -> dict[str, Any]:
        key = os.getenv("OPENALEX_API_KEY")
        if key:
            params["api_key"] = key
        mailto = os.getenv("KORA_MAILTO")
        if mailto:
            params["mailto"] = mailto
        return params

    # ---------------------------------------------------------------- people
    async def search_people(self, query: str) -> list[RawPerson]:
        try:
            data = await self.http.get_json(
                f"{BASE}/authors",
                self._params(
                    search=query,
                    per_page=10,
                    select="id,display_name,display_name_alternatives,works_count,"
                    "cited_by_count,orcid,last_known_institutions",
                ),
            )
            return [self._person(a) for a in data.get("results", [])]
        except Exception as exc:  # search may be rate-limited -> autocomplete
            log.info("openalex author search failed (%s); using autocomplete", exc)
            data = await self.http.get_json(
                f"{BASE}/autocomplete/authors", self._params(q=query)
            )
            return [self._person_from_autocomplete(a) for a in data.get("results", [])]

    def _person(self, a: dict[str, Any]) -> RawPerson:
        alts = a.get("display_name_alternatives") or []
        birth, death = years_in_names(alts)
        orcid = a.get("orcid")
        ids: dict[str, list[str]] = {}
        if orcid:
            ids["orcid"] = [orcid.rsplit("/", 1)[-1]]
        insts = [i.get("display_name") for i in a.get("last_known_institutions") or []]
        return RawPerson(
            source=self.name,
            source_id=short_id(a["id"]),
            name=a.get("display_name") or "",
            alt_names=alts,
            birth_year=birth,
            death_year=death,
            works_count=a.get("works_count"),
            affiliations=[i for i in insts if i],
            identifiers=ids,
            url=a["id"],
            popularity=a.get("cited_by_count") or 0,
        )

    def _person_from_autocomplete(self, a: dict[str, Any]) -> RawPerson:
        ids: dict[str, list[str]] = {}
        ext = a.get("external_id") or ""
        if "orcid.org" in ext:
            ids["orcid"] = [ext.rsplit("/", 1)[-1]]
        hint = a.get("hint")
        return RawPerson(
            source=self.name,
            source_id=short_id(a["id"]),
            name=a.get("display_name") or "",
            works_count=a.get("works_count"),
            affiliations=[hint] if hint else [],
            identifiers=ids,
            url=a["id"],
            popularity=a.get("cited_by_count") or 0,
        )

    # ----------------------------------------------------------------- works
    async def sample_titles(self, source_id: str, limit: int = 50) -> list[str]:
        data = await self.http.get_json(
            f"{BASE}/works",
            self._params(
                filter=f"author.id:{source_id}",
                sort="cited_by_count:desc",
                per_page=min(limit, 200),
                select="display_name",
            ),
        )
        return [w.get("display_name") or "" for w in data.get("results", [])]

    async def works_by(self, person: Person) -> list[RawWork]:
        ids = person.ids(self.name)
        if not ids:
            return []
        flt = "author.id:" + "|".join(ids[:50])
        return await self._paged_works(flt, Relation.BY, self.max_works, person)

    def _role_for(self, w: dict[str, Any], person: Person) -> WorkRole:
        """Use OpenAlex authorship position; book anthologies need contributor filtering."""
        authorships = w.get("authorships") or []
        own = set(person.ids(self.name))
        idx = next(
            (
                i
                for i, a in enumerate(authorships)
                if ((a.get("author") or {}).get("id") or "")
                and short_id(a["author"]["id"]) in own
            ),
            None,
        )
        if idx is None:
            return WorkRole.AUTHOR

        n = len(authorships)
        title = w.get("display_name") or ""
        is_book = TYPE_MAP.get(w.get("type") or "", WorkCategory.OTHER) == WorkCategory.BOOK
        first_author = ((authorships[0].get("author") or {}).get("display_name") or "") if authorships else ""
        if is_book and idx > 0 and is_collective_author(first_author):
            return WorkRole.CONTRIBUTOR
        if is_book and idx > 0 and " & " in title:
            return WorkRole.CONTRIBUTOR
        if is_book and re.search(r"\b[oa]'? level\b.*\bliterature\b", title, re.IGNORECASE):
            return WorkRole.CONTRIBUTOR
        if is_book and (is_anthology_title(title) or is_edited_anthology_title(title)):
            if idx == 0 and (n > 1 or is_edited_anthology_title(title)):
                return WorkRole.EDITOR
            if idx > 0:
                return WorkRole.CONTRIBUTOR
        if not is_book:
            return WorkRole.AUTHOR
        if idx == 0:
            return WorkRole.AUTHOR
        if n <= 2:
            return WorkRole.AUTHOR
        return WorkRole.CONTRIBUTOR

    async def works_about(self, person: Person) -> list[RawWork]:
        """Works discussing the person.

        Primary: full-text search of titles/abstracts for the name. Anonymous search is
        sometimes rate-limited, so we fall back to works that *cite* the person's most
        cited works (pure filter queries, which are not search-limited).
        """
        own_ids = person.ids(self.name)[:20]
        exclusions = [f"author.id:!{i}" for i in own_ids]
        name = person.display_name.replace('"', "")
        try:
            data = await self.http.get_json(
                f"{BASE}/works",
                self._params(
                    # A title mention is a much stronger "about" signal than an
                    # abstract mention, which mostly returns works that cite him.
                    filter=",".join([f'title.search:"{name}"', *exclusions]),
                    sort="cited_by_count:desc",
                    per_page=40,
                    select=WORK_FIELDS,
                ),
            )
        except Exception as exc:
            if not own_ids:
                raise
            log.info("openalex about-search failed (%s); using citation fallback", exc)
            top = await self.http.get_json(
                f"{BASE}/works",
                self._params(
                    filter="author.id:" + "|".join(own_ids),
                    sort="cited_by_count:desc",
                    per_page=8,
                    select="id",
                ),
            )
            cited = [short_id(w["id"]) for w in top.get("results", [])]
            if not cited:
                return []
            data = await self.http.get_json(
                f"{BASE}/works",
                self._params(
                    filter=",".join(["cites:" + "|".join(cited), *exclusions]),
                    sort="cited_by_count:desc",
                    per_page=40,
                    select=WORK_FIELDS,
                ),
            )
        return [self._work(w, Relation.ABOUT) for w in data.get("results", [])]

    async def _paged_works(
        self,
        flt: str,
        relation: Relation,
        limit: int,
        person: Person | None = None,
    ) -> list[RawWork]:
        # Basic page= paging (works anonymously up to 10k results); cursor paging
        # requires an API key and is only needed for bulk harvesting.
        out: list[RawWork] = []
        per_page = 200
        page = 1
        while len(out) < limit:
            data = await self.http.get_json(
                f"{BASE}/works",
                self._params(
                    filter=flt,
                    per_page=per_page,
                    page=page,
                    sort="cited_by_count:desc",
                    select=WORK_FIELDS,
                ),
            )
            results = data.get("results", [])
            out.extend(
                self._work(
                    w,
                    relation,
                    self._role_for(w, person) if person else WorkRole.AUTHOR,
                )
                for w in results
            )
            if len(results) < per_page:
                break
            page += 1
        return out[:limit]

    def _work(
        self,
        w: dict[str, Any],
        relation: Relation,
        role: WorkRole = WorkRole.AUTHOR,
    ) -> RawWork:
        loc = w.get("primary_location") or {}
        source = loc.get("source") or {}
        oa = w.get("open_access") or {}
        doi = normalize_doi(w.get("doi"))
        links: list[AccessLink] = []
        if oa.get("is_oa") and oa.get("oa_url"):
            links.append(AccessLink(oa["oa_url"], "oa_pdf", "Free (open access)"))
        if doi:
            links.append(AccessLink(f"https://doi.org/{doi}", "publisher", "Publisher (DOI)"))
        elif loc.get("landing_page_url"):
            links.append(AccessLink(loc["landing_page_url"], "landing", "Source page"))
        links.append(AccessLink(w["id"], "landing", "OpenAlex record"))
        raw_type = w.get("type")
        lang = normalize_language(w.get("language"))
        return RawWork(
            source=self.name,
            source_id=short_id(w["id"]),
            title=w.get("display_name") or "(untitled)",
            relation=relation,
            category=TYPE_MAP.get(raw_type or "", WorkCategory.OTHER),
            role=role,
            year=w.get("publication_year"),
            authors=[
                (a.get("author") or {}).get("display_name", "")
                for a in (w.get("authorships") or [])[:10]
            ],
            venue=source.get("display_name"),
            doi=doi,
            languages=[lang] if lang else [],
            cited_by=w.get("cited_by_count"),
            links=links,
            raw_type=raw_type,
        )
