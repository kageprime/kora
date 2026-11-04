"""Core data structures shared by connectors, resolution and presentation.

Raw* classes are what connectors emit (one per source record).
Person / Work are canonical, merged entities built by the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Confidence(StrEnum):
    """How sure we are that a source identity belongs to a canonical person."""

    HARD_ID = "hard-id"  # shared persistent identifier (Wikidata/ORCID/OL/OpenAlex)
    HIGH = "high"  # name match + corroborating evidence (dates, affiliation)
    GREY = "grey"  # name match only -> candidate for AI/human review
    CONFLICT = "conflict"  # contradicting evidence -> never merged


class WorkCategory(StrEnum):
    BOOK = "book"
    ARTICLE = "article"  # articles, essays, chapters, reviews
    THESIS = "thesis"
    DATASET = "dataset"
    OTHER = "other"


class Relation(StrEnum):
    BY = "by"  # authored by / connected to the person
    ABOUT = "about"  # about / discussing the person


class WorkRole(StrEnum):
    """The person's role in a work, used to separate bibliographies from anthologies."""

    AUTHOR = "author"
    EDITOR = "editor"
    CONTRIBUTOR = "contributor"  # one of many contributors to an anthology/textbook


@dataclass
class RawPerson:
    source: str  # "openalex" | "openlibrary" | "wikidata"
    source_id: str
    name: str
    alt_names: list[str] = field(default_factory=list)
    description: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    works_count: int | None = None
    affiliations: list[str] = field(default_factory=list)
    # scheme -> values, e.g. {"openlibrary": ["OL78910A"], "viaf": ["24596756"]}
    identifiers: dict[str, list[str]] = field(default_factory=dict)
    url: str | None = None
    popularity: int = 0  # e.g. Wikidata sitelink count, used for ranking
    wikipedia_title: str | None = None


@dataclass
class AccessLink:
    url: str
    kind: str  # "oa_pdf" | "publisher" | "library" | "borrow" | "landing"
    label: str


@dataclass
class RawWork:
    source: str
    source_id: str
    title: str
    relation: Relation = Relation.BY
    category: WorkCategory = WorkCategory.OTHER
    role: WorkRole = WorkRole.AUTHOR
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    doi: str | None = None
    isbns: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    cover_url: str | None = None
    cited_by: int | None = None
    edition_count: int | None = None
    links: list[AccessLink] = field(default_factory=list)
    raw_type: str | None = None  # source-native type, e.g. OpenAlex "book-review"


@dataclass
class LinkedIdentity:
    """A source identity attached to a canonical person, with the reason."""

    person: RawPerson
    confidence: Confidence
    evidence: list[str] = field(default_factory=list)


@dataclass
class Person:
    display_name: str
    identities: list[LinkedIdentity] = field(default_factory=list)
    description: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    wikipedia_title: str | None = None

    def ids(self, scheme: str, include_grey: bool = False) -> list[str]:
        """Identifiers of `scheme` for this person (deduplicated).

        Grey-zone identities (name-only matches) are excluded by default so that
        unconfirmed identities never pollute the bibliography.
        """
        out: list[str] = []
        for ident in self.identities:
            if ident.confidence == Confidence.CONFLICT:
                continue
            if ident.confidence == Confidence.GREY and not include_grey:
                continue
            p = ident.person
            values = list(p.identifiers.get(scheme, []))
            if p.source == scheme:
                values.append(p.source_id)
            for v in values:
                if v not in out:
                    out.append(v)
        return out

    @property
    def sources(self) -> list[str]:
        return sorted({i.person.source for i in self.identities})


@dataclass
class Work:
    """A canonical work (FRBR 'work' level) merged from many source records."""

    title: str
    category: WorkCategory
    relation: Relation
    year: int | None
    role: WorkRole = WorkRole.AUTHOR
    records: list[RawWork] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    dois: list[str] = field(default_factory=list)
    isbns: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    cover_url: str | None = None
    cited_by: int = 0
    edition_count: int = 0
    links: list[AccessLink] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return sorted({r.source for r in self.records})


@dataclass
class Profile:
    query: str
    person: Person
    works: list[Work]
    alternatives: list[Person] = field(default_factory=list)
    bio: str | None = None
    bio_url: str | None = None
    source_status: dict[str, str] = field(default_factory=dict)
    raw_work_count: int = 0
    flagged: list[RawWork] = field(default_factory=list)  # suspected misattributions
