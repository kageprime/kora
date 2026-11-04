"""SQLAlchemy schema for canonical scholars, identities, works and records.

The Phase 1 schema is intentionally scholar-centric but already separates global
works from the person-work relation. A work can be linked to several scholars
with a different relation/role (for example, a book and its reviewer).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Scholar(Base):
    __tablename__ = "scholars"

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(500))
    name_key: Mapped[str] = mapped_column(String(500), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    death_year: Mapped[int | None] = mapped_column(Integer)
    wikipedia_title: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    identities: Mapped[list[Identity]] = relationship(
        back_populates="scholar", cascade="all, delete-orphan"
    )
    works: Mapped[list[ScholarWork]] = relationship(
        back_populates="scholar", cascade="all, delete-orphan"
    )
    profile: Mapped[ScholarProfile | None] = relationship(
        back_populates="scholar", cascade="all, delete-orphan", uselist=False
    )
    review_items: Mapped[list[ReviewItem]] = relationship(
        back_populates="scholar", cascade="all, delete-orphan"
    )


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_identity_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int] = mapped_column(
        ForeignKey("scholars.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(500))
    alt_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    death_year: Mapped[int | None] = mapped_column(Integer)
    works_count: Mapped[int | None] = mapped_column(Integer)
    affiliations: Mapped[list[str]] = mapped_column(JSON, default=list)
    identifiers: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    url: Mapped[str | None] = mapped_column(Text)
    popularity: Mapped[int] = mapped_column(Integer, default=0)
    wikipedia_title: Mapped[str | None] = mapped_column(String(500))

    scholar: Mapped[Scholar] = relationship(back_populates="identities")


class Work(Base):
    __tablename__ = "works"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1000))
    title_key: Mapped[str] = mapped_column(String(1000), index=True)
    category: Mapped[str] = mapped_column(String(20))
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(1000))
    cover_url: Mapped[str | None] = mapped_column(Text)
    cited_by: Mapped[int] = mapped_column(Integer, default=0)
    edition_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    records: Mapped[list[WorkRecord]] = relationship(
        back_populates="work", cascade="all, delete-orphan"
    )
    links: Mapped[list[WorkLink]] = relationship(
        back_populates="work", cascade="all, delete-orphan"
    )
    scholars: Mapped[list[ScholarWork]] = relationship(
        back_populates="work", cascade="all, delete-orphan"
    )


class WorkRecord(Base):
    __tablename__ = "work_records"
    __table_args__ = (
        UniqueConstraint("work_id", "source", "source_id", name="uq_work_record_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(1000))
    category: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20))
    year: Mapped[int | None] = mapped_column(Integer)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    venue: Mapped[str | None] = mapped_column(String(1000))
    doi: Mapped[str | None] = mapped_column(String(255), index=True)
    isbns: Mapped[list[str]] = mapped_column(JSON, default=list)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    cover_url: Mapped[str | None] = mapped_column(Text)
    cited_by: Mapped[int | None] = mapped_column(Integer)
    edition_count: Mapped[int | None] = mapped_column(Integer)
    links: Mapped[list[dict]] = mapped_column(JSON, default=list)
    raw_type: Mapped[str | None] = mapped_column(String(100))

    work: Mapped[Work] = relationship(back_populates="records")


class WorkLink(Base):
    __tablename__ = "work_links"
    __table_args__ = (UniqueConstraint("work_id", "url", name="uq_work_link_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)

    work: Mapped[Work] = relationship(back_populates="links")


class ScholarWork(Base):
    __tablename__ = "scholar_works"
    __table_args__ = (
        UniqueConstraint("scholar_id", "work_id", name="uq_scholar_work"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int] = mapped_column(
        ForeignKey("scholars.id", ondelete="CASCADE"), index=True
    )
    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20))

    scholar: Mapped[Scholar] = relationship(back_populates="works")
    work: Mapped[Work] = relationship(back_populates="scholars")


class ScholarProfile(Base):
    __tablename__ = "scholar_profiles"
    __table_args__ = (UniqueConstraint("scholar_id", name="uq_scholar_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int] = mapped_column(
        ForeignKey("scholars.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(Text)
    bio_url: Mapped[str | None] = mapped_column(Text)
    source_status: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    raw_work_count: Mapped[int] = mapped_column(Integer, default=0)
    alternatives: Mapped[list[dict]] = mapped_column(JSON, default=list)
    flagged: Mapped[list[dict]] = mapped_column(JSON, default=list)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_error: Mapped[str | None] = mapped_column(Text)

    scholar: Mapped[Scholar] = relationship(back_populates="profile")


class ReviewItem(Base):
    """A durable queue item for an ambiguous identity or a suspect record.

    Items are scoped to a scholar and identified by a stable fingerprint so a
    repeated profile resolution updates the same item instead of duplicating it.
    Resolved/dismissed decisions survive later refreshes; pending items that no
    longer reproduce are marked ``superseded`` rather than deleted.
    """

    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint(
            "scholar_id", "kind", "fingerprint", name="uq_review_item"
        ),
        Index("ix_review_items_status_kind", "status", "kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scholar_id: Mapped[int] = mapped_column(
        ForeignKey("scholars.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    fingerprint: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(1000))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scholar: Mapped[Scholar] = relationship(back_populates="review_items")
