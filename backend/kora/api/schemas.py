"""Pydantic API contracts for the Phase 1 service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kora.models import (
    AccessLink,
    Confidence,
    LinkedIdentity,
    Person,
    Profile,
    RawPerson,
    RawWork,
    Relation,
    Work,
    WorkCategory,
    WorkRole,
)


class AccessLinkOut(BaseModel):
    url: str
    kind: str
    label: str

    @classmethod
    def from_model(cls, link: AccessLink) -> "AccessLinkOut":
        return cls(url=link.url, kind=link.kind, label=link.label)


class RawWorkOut(BaseModel):
    source: str
    source_id: str
    title: str
    relation: Relation
    category: WorkCategory
    role: WorkRole
    year: int | None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    doi: str | None = None
    isbns: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    cover_url: str | None = None
    cited_by: int | None = None
    edition_count: int | None = None
    links: list[AccessLinkOut] = Field(default_factory=list)
    raw_type: str | None = None

    @classmethod
    def from_model(cls, work: RawWork) -> "RawWorkOut":
        return cls(
            source=work.source,
            source_id=work.source_id,
            title=work.title,
            relation=work.relation,
            category=work.category,
            role=work.role,
            year=work.year,
            authors=work.authors,
            venue=work.venue,
            doi=work.doi,
            isbns=work.isbns,
            languages=work.languages,
            cover_url=work.cover_url,
            cited_by=work.cited_by,
            edition_count=work.edition_count,
            links=[AccessLinkOut.from_model(link) for link in work.links],
            raw_type=work.raw_type,
        )

    def to_model(self) -> RawWork:
        return RawWork(
            source=self.source,
            source_id=self.source_id,
            title=self.title,
            relation=self.relation,
            category=self.category,
            role=self.role,
            year=self.year,
            authors=list(self.authors),
            venue=self.venue,
            doi=self.doi,
            isbns=list(self.isbns),
            languages=list(self.languages),
            cover_url=self.cover_url,
            cited_by=self.cited_by,
            edition_count=self.edition_count,
            links=[AccessLink(link.url, link.kind, link.label) for link in self.links],
            raw_type=self.raw_type,
        )


class WorkOut(BaseModel):
    title: str
    category: WorkCategory
    relation: Relation
    year: int | None
    role: WorkRole
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    dois: list[str] = Field(default_factory=list)
    isbns: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    cover_url: str | None = None
    cited_by: int = 0
    edition_count: int = 0
    links: list[AccessLinkOut] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    records: list[RawWorkOut] = Field(default_factory=list)

    @classmethod
    def from_model(cls, work: Work) -> "WorkOut":
        return cls(
            title=work.title,
            category=work.category,
            relation=work.relation,
            year=work.year,
            role=work.role,
            authors=work.authors,
            venue=work.venue,
            dois=work.dois,
            isbns=work.isbns,
            languages=work.languages,
            cover_url=work.cover_url,
            cited_by=work.cited_by,
            edition_count=work.edition_count,
            links=[AccessLinkOut.from_model(link) for link in work.links],
            sources=work.sources,
            records=[RawWorkOut.from_model(record) for record in work.records],
        )

    def to_model(self) -> Work:
        return Work(
            title=self.title,
            category=self.category,
            relation=self.relation,
            year=self.year,
            role=self.role,
            records=[record.to_model() for record in self.records],
            authors=list(self.authors),
            venue=self.venue,
            dois=list(self.dois),
            isbns=list(self.isbns),
            languages=list(self.languages),
            cover_url=self.cover_url,
            cited_by=self.cited_by,
            edition_count=self.edition_count,
            links=[AccessLink(link.url, link.kind, link.label) for link in self.links],
        )


class RawPersonOut(BaseModel):
    source: str
    source_id: str
    name: str
    alt_names: list[str] = Field(default_factory=list)
    description: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    works_count: int | None = None
    affiliations: list[str] = Field(default_factory=list)
    identifiers: dict[str, list[str]] = Field(default_factory=dict)
    url: str | None = None
    popularity: int = 0
    wikipedia_title: str | None = None

    @classmethod
    def from_model(cls, person: RawPerson) -> "RawPersonOut":
        return cls(
            source=person.source,
            source_id=person.source_id,
            name=person.name,
            alt_names=person.alt_names,
            description=person.description,
            birth_year=person.birth_year,
            death_year=person.death_year,
            works_count=person.works_count,
            affiliations=person.affiliations,
            identifiers=person.identifiers,
            url=person.url,
            popularity=person.popularity,
            wikipedia_title=person.wikipedia_title,
        )

    def to_model(self) -> RawPerson:
        return RawPerson(
            source=self.source,
            source_id=self.source_id,
            name=self.name,
            alt_names=list(self.alt_names),
            description=self.description,
            birth_year=self.birth_year,
            death_year=self.death_year,
            works_count=self.works_count,
            affiliations=list(self.affiliations),
            identifiers={k: list(v) for k, v in self.identifiers.items()},
            url=self.url,
            popularity=self.popularity,
            wikipedia_title=self.wikipedia_title,
        )


class LinkedIdentityOut(BaseModel):
    person: RawPersonOut
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)

    @classmethod
    def from_model(cls, identity: LinkedIdentity) -> "LinkedIdentityOut":
        return cls(
            person=RawPersonOut.from_model(identity.person),
            confidence=identity.confidence,
            evidence=identity.evidence,
        )

    def to_model(self) -> LinkedIdentity:
        return LinkedIdentity(
            person=self.person.to_model(),
            confidence=self.confidence,
            evidence=list(self.evidence),
        )


class PersonOut(BaseModel):
    display_name: str
    identities: list[LinkedIdentityOut] = Field(default_factory=list)
    description: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    wikipedia_title: str | None = None

    @classmethod
    def from_model(cls, person: Person) -> "PersonOut":
        return cls(
            display_name=person.display_name,
            identities=[LinkedIdentityOut.from_model(i) for i in person.identities],
            description=person.description,
            birth_year=person.birth_year,
            death_year=person.death_year,
            wikipedia_title=person.wikipedia_title,
        )

    def to_model(self) -> Person:
        return Person(
            display_name=self.display_name,
            identities=[identity.to_model() for identity in self.identities],
            description=self.description,
            birth_year=self.birth_year,
            death_year=self.death_year,
            wikipedia_title=self.wikipedia_title,
        )


class ProfileOut(BaseModel):
    query: str
    person: PersonOut
    works: list[WorkOut] = Field(default_factory=list)
    alternatives: list[PersonOut] = Field(default_factory=list)
    bio: str | None = None
    bio_url: str | None = None
    source_status: dict[str, str] = Field(default_factory=dict)
    raw_work_count: int = 0
    flagged: list[RawWorkOut] = Field(default_factory=list)
    scholar_id: int | None = None
    stored: bool = False

    @classmethod
    def from_model(cls, profile: Profile, *, scholar_id: int | None = None, stored: bool = False) -> "ProfileOut":
        return cls(
            query=profile.query,
            person=PersonOut.from_model(profile.person),
            works=[WorkOut.from_model(work) for work in profile.works],
            alternatives=[PersonOut.from_model(person) for person in profile.alternatives],
            bio=profile.bio,
            bio_url=profile.bio_url,
            source_status=profile.source_status,
            raw_work_count=profile.raw_work_count,
            flagged=[RawWorkOut.from_model(record) for record in profile.flagged],
            scholar_id=scholar_id,
            stored=stored,
        )

    def to_model(self) -> Profile:
        return Profile(
            query=self.query,
            person=self.person.to_model(),
            works=[work.to_model() for work in self.works],
            alternatives=[person.to_model() for person in self.alternatives],
            bio=self.bio,
            bio_url=self.bio_url,
            source_status=dict(self.source_status),
            raw_work_count=self.raw_work_count,
            flagged=[record.to_model() for record in self.flagged],
        )


class ResolveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    pick: int = Field(default=0, ge=0)
    include_about: bool = True
    persist: bool = True


class ScholarSummary(BaseModel):
    id: int
    display_name: str
    birth_year: int | None = None
    death_year: int | None = None
    description: str | None = None
    work_count: int = 0
    about_count: int = 0
    updated_at: datetime | None = None
    refreshed_at: datetime | None = None
    refresh_error: str | None = None


class ReviewItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scholar_id: int
    kind: str
    status: str
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None


class ReviewQueueOut(BaseModel):
    items: list[ReviewItemOut] = Field(default_factory=list)
    total: int = 0


class ReviewItemUpdate(BaseModel):
    status: str = Field(pattern="^(pending|resolved|dismissed)$")
    note: str | None = Field(default=None, max_length=2000)


class HealthOut(BaseModel):
    status: str
    version: str
    database: str
