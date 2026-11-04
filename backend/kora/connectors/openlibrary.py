"""Open Library connector: books, editions, covers, borrowable scans.

Docs: https://openlibrary.org/developers/api
"""

from __future__ import annotations

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
    name_key,
    normalize_isbn,
    normalize_language,
)

BASE = "https://openlibrary.org"
WORK_FIELDS = (
    "key,title,subtitle,first_publish_year,edition_count,isbn,cover_i,language,"
    "ia,ebook_access,author_name,author_key,subject"
)


def _year(value: Any) -> int | None:
    if not value:
        return None
    m = re.search(r"(1[5-9]\d\d|20\d\d)", str(value))
    return int(m.group(1)) if m else None


class OpenLibraryConnector(BaseConnector):
    name = "openlibrary"
    per_author_limit = 150

    async def search_people(self, query: str) -> list[RawPerson]:
        data = await self.http.get_json(
            f"{BASE}/search/authors.json", {"q": query, "limit": 10}
        )
        out = []
        for d in data.get("docs", []):
            out.append(
                RawPerson(
                    source=self.name,
                    source_id=d["key"].rsplit("/", 1)[-1],
                    name=d.get("name") or "",
                    alt_names=d.get("alternate_names") or [],
                    birth_year=_year(d.get("birth_date")),
                    death_year=_year(d.get("death_date")),
                    works_count=d.get("work_count"),
                    description=f"Top work: {d['top_work']}" if d.get("top_work") else None,
                    url=f"{BASE}/authors/{d['key'].rsplit('/', 1)[-1]}",
                    popularity=d.get("work_count") or 0,
                )
            )
        return out

    async def works_by(self, person: Person) -> list[RawWork]:
        out: list[RawWork] = []
        seen: set[str] = set()
        for key in person.ids(self.name)[:5]:
            data = await self.http.get_json(
                f"{BASE}/search.json",
                {
                    "author_key": key,
                    "limit": self.per_author_limit,
                    "sort": "editions",
                    "fields": WORK_FIELDS,
                },
            )
            for d in data.get("docs", []):
                if d["key"] not in seen:
                    seen.add(d["key"])
                    out.append(self._work(d, Relation.BY, self._role_for(d, person)))
        return out

    def _role_for(self, d: dict[str, Any], person: Person) -> WorkRole:
        """Open Library lists every contributor, so position + title are the only signals."""
        keys = d.get("author_key") or []
        names = d.get("author_name") or []
        own_keys = set(person.ids(self.name))
        idx = next((i for i, key in enumerate(keys) if key in own_keys), None)
        if idx is None:
            own_names = {
                name_key(n)
                for ident in person.identities
                for n in [ident.person.name, *ident.person.alt_names]
            }
            idx = next((i for i, name in enumerate(names) if name_key(name) in own_names), None)
        if idx is None:
            return WorkRole.AUTHOR

        n = len(keys) or len(names)
        title = d.get("title") or ""
        if idx > 0 and names and is_collective_author(names[0]):
            return WorkRole.CONTRIBUTOR
        if idx > 0 and " & " in title:
            # Bound works ("A Month and A Day & Letters") list the second
            # author for an introduction, not co-authorship.
            return WorkRole.CONTRIBUTOR
        if re.search(r"\b[oa]'? level\b.*\bliterature\b", title, re.IGNORECASE):
            return WorkRole.CONTRIBUTOR
        subjects = " ".join(d.get("subject") or [])
        single_author_collection = bool(
            re.search(
                r"\b(collected|selected|complete)\s+(poems|plays|stories|essays|works)\b"
                r"|\b(trilogy|omnibus)\b",
                title,
                re.IGNORECASE,
            )
        )
        anthology_subject = not single_author_collection and bool(
            re.search(r"antholog", subjects, re.IGNORECASE)
            or re.search(r"textbook|multicultural education", subjects, re.IGNORECASE)
            or (
                re.search(r"collection", subjects, re.IGNORECASE)
                and re.search(r"literature", subjects, re.IGNORECASE)
            )
        )
        if is_anthology_title(title) or is_edited_anthology_title(title) or anthology_subject:
            if idx == 0 and (
                n > 1 or is_edited_anthology_title(title) or anthology_subject
            ):
                return WorkRole.EDITOR
            if idx > 0:
                return WorkRole.CONTRIBUTOR
        if idx == 0:
            return WorkRole.AUTHOR
        if n <= 2 and idx == 1:
            return WorkRole.AUTHOR
        return WorkRole.CONTRIBUTOR

    async def works_about(self, person: Person) -> list[RawWork]:
        """Books whose *subject* is the person (criticism, biographies, study guides)."""
        own_keys = set(person.ids(self.name))
        name = person.display_name.replace('"', "")
        data = await self.http.get_json(
            f"{BASE}/search.json",
            {"q": f'subject:"{name}"', "limit": 40, "fields": WORK_FIELDS},
        )
        out = []
        for d in data.get("docs", []):
            if own_keys & set(d.get("author_key") or []):
                continue  # his own book, already covered by works_by
            out.append(self._work(d, Relation.ABOUT))
        return out

    def _work(
        self,
        d: dict[str, Any],
        relation: Relation,
        role: WorkRole = WorkRole.AUTHOR,
    ) -> RawWork:
        key = d["key"].rsplit("/", 1)[-1]
        isbns: list[str] = []
        for raw in d.get("isbn") or []:
            n = normalize_isbn(raw)
            if n and n not in isbns:
                isbns.append(n)
        links = [AccessLink(f"{BASE}/works/{key}", "library", "Open Library")]
        access = d.get("ebook_access")
        ia = d.get("ia") or []
        if ia and access == "public":
            links.insert(0, AccessLink(f"https://archive.org/details/{ia[0]}", "oa_pdf", "Free full text (Internet Archive)"))
        elif ia and access == "borrowable":
            links.insert(0, AccessLink(f"https://archive.org/details/{ia[0]}", "borrow", "Borrow free (Internet Archive)"))
        cover = d.get("cover_i")
        title = d.get("title") or "(untitled)"
        return RawWork(
            source=self.name,
            source_id=key,
            title=title,
            relation=relation,
            category=WorkCategory.BOOK,
            role=role,
            year=d.get("first_publish_year"),
            authors=(d.get("author_name") or [])[:10],
            isbns=isbns[:60],
            languages=[
                lang
                for raw_lang in (d.get("language") or [])
                if (lang := normalize_language(raw_lang))
            ],
            cover_url=f"https://covers.openlibrary.org/b/id/{cover}-M.jpg" if cover else None,
            edition_count=d.get("edition_count"),
            links=links,
            raw_type="book",
        )
