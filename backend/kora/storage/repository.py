"""Persistence and reconstruction for resolved profiles."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from kora.normalize import fold, name_key, title_key
from kora.storage import tables as t


def scholar_key(person: Person) -> str:
    """Stable natural key for a resolved person."""
    for scheme in ("wikidata", "orcid", "openlibrary", "openalex"):
        ids = person.ids(scheme)
        if ids:
            return f"{scheme}:{ids[0]}"
    return f"name:{name_key(person.display_name)}:{person.birth_year or ''}"


def work_key(work: Work) -> str:
    """Stable key for a merged work.

    Books deliberately omit the year: the resolver merges same-title books across
    editions, and a corrected first-publication year must not create a duplicate.
    Articles and theses include the year because same-titled papers can recur.
    """
    title = title_key(work.title) or fold(work.title)
    first_author = name_key(work.authors[0]) if work.authors else ""
    year = "" if work.category == WorkCategory.BOOK else str(work.year or "")
    payload = "|".join([work.category.value, title, year, first_author])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


REVIEW_KINDS = ("grey_identity", "flagged_record")
REVIEW_STATUSES = ("pending", "resolved", "dismissed", "superseded")


def review_fingerprint(kind: str, source: str, source_id: str) -> str:
    """Stable identity for a review item, independent of mutable payload text."""
    payload = f"{kind}|{source}|{source_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# JSON helpers for snapshot-only fields
# --------------------------------------------------------------------------- #
def _raw_person_to_json(person: RawPerson) -> dict[str, Any]:
    return dataclasses.asdict(person)


def _raw_person_from_json(data: dict[str, Any]) -> RawPerson:
    return RawPerson(
        source=data["source"],
        source_id=data["source_id"],
        name=data.get("name") or "",
        alt_names=list(data.get("alt_names") or []),
        description=data.get("description"),
        birth_year=data.get("birth_year"),
        death_year=data.get("death_year"),
        works_count=data.get("works_count"),
        affiliations=list(data.get("affiliations") or []),
        identifiers={k: list(v) for k, v in (data.get("identifiers") or {}).items()},
        url=data.get("url"),
        popularity=data.get("popularity") or 0,
        wikipedia_title=data.get("wikipedia_title"),
    )


def _person_to_json(person: Person) -> dict[str, Any]:
    return dataclasses.asdict(person)


def _person_from_json(data: dict[str, Any]) -> Person:
    identities = [
        LinkedIdentity(
            person=_raw_person_from_json(item["person"]),
            confidence=Confidence(item["confidence"]),
            evidence=list(item.get("evidence") or []),
        )
        for item in data.get("identities") or []
    ]
    return Person(
        display_name=data["display_name"],
        identities=identities,
        description=data.get("description"),
        birth_year=data.get("birth_year"),
        death_year=data.get("death_year"),
        wikipedia_title=data.get("wikipedia_title"),
    )


def _raw_work_to_json(work: RawWork) -> dict[str, Any]:
    return dataclasses.asdict(work)


def _raw_work_from_json(data: dict[str, Any]) -> RawWork:
    return RawWork(
        source=data["source"],
        source_id=data["source_id"],
        title=data.get("title") or "(untitled)",
        relation=Relation(data.get("relation") or Relation.BY),
        category=WorkCategory(data.get("category") or WorkCategory.OTHER),
        role=WorkRole(data.get("role") or WorkRole.AUTHOR),
        year=data.get("year"),
        authors=list(data.get("authors") or []),
        venue=data.get("venue"),
        doi=data.get("doi"),
        isbns=list(data.get("isbns") or []),
        languages=list(data.get("languages") or []),
        cover_url=data.get("cover_url"),
        cited_by=data.get("cited_by"),
        edition_count=data.get("edition_count"),
        links=[
            AccessLink(link["url"], link["kind"], link["label"])
            for link in data.get("links") or []
        ],
        raw_type=data.get("raw_type"),
    )


# --------------------------------------------------------------------------- #
# Save
# --------------------------------------------------------------------------- #
async def save_profile(session: AsyncSession, profile: Profile) -> int:
    """Upsert one resolved profile and return the scholar id."""
    key = scholar_key(profile.person)
    scholar = await session.scalar(select(t.Scholar).where(t.Scholar.scholar_key == key))
    if scholar is None:
        scholar = t.Scholar(
            scholar_key=key,
            display_name=profile.person.display_name,
            name_key=name_key(profile.person.display_name),
        )
        session.add(scholar)
        await session.flush()
    else:
        scholar.display_name = profile.person.display_name
        scholar.name_key = name_key(profile.person.display_name)

    scholar.description = profile.person.description
    scholar.birth_year = profile.person.birth_year
    scholar.death_year = profile.person.death_year
    scholar.wikipedia_title = profile.person.wikipedia_title

    await _save_identities(session, scholar, profile.person)
    work_rows = []
    for work in profile.works:
        row = await _save_work(session, work)
        work_rows.append((work, row))

    await session.execute(delete(t.ScholarWork).where(t.ScholarWork.scholar_id == scholar.id))
    for work, row in work_rows:
        session.add(
            t.ScholarWork(
                scholar_id=scholar.id,
                work_id=row.id,
                relation=work.relation.value,
                role=work.role.value,
            )
        )

    snapshot = await session.scalar(
        select(t.ScholarProfile).where(t.ScholarProfile.scholar_id == scholar.id)
    )
    if snapshot is None:
        snapshot = t.ScholarProfile(scholar_id=scholar.id)
        session.add(snapshot)
    snapshot.query = profile.query
    snapshot.bio = profile.bio
    snapshot.bio_url = profile.bio_url
    snapshot.source_status = dict(profile.source_status)
    snapshot.raw_work_count = profile.raw_work_count
    snapshot.alternatives = [_person_to_json(p) for p in profile.alternatives]
    snapshot.flagged = [_raw_work_to_json(r) for r in profile.flagged]
    snapshot.refreshed_at = func.now()
    snapshot.last_attempted_at = func.now()
    snapshot.refresh_error = None

    await _sync_review_items(session, scholar, profile)

    await session.commit()
    return scholar.id


async def _sync_review_items(
    session: AsyncSession, scholar: t.Scholar, profile: Profile
) -> None:
    """Upsert the current grey identities and flagged records as review items."""
    wanted: dict[tuple[str, str], dict[str, Any]] = {}
    for identity in profile.person.identities:
        if identity.confidence != Confidence.GREY:
            continue
        raw = identity.person
        kind = "grey_identity"
        fingerprint = review_fingerprint(kind, raw.source, raw.source_id)
        wanted[(kind, fingerprint)] = {
            "title": f"{raw.name} — {raw.source}:{raw.source_id}"[:1000],
            "payload": {
                "person": _raw_person_to_json(raw),
                "evidence": list(identity.evidence),
            },
        }

    for record in profile.flagged:
        kind = "flagged_record"
        fingerprint = review_fingerprint(kind, record.source, record.source_id)
        wanted[(kind, fingerprint)] = {
            "title": record.title[:1000],
            "payload": {"record": _raw_work_to_json(record)},
        }

    existing = (
        await session.scalars(
            select(t.ReviewItem).where(t.ReviewItem.scholar_id == scholar.id)
        )
    ).all()
    by_key = {(row.kind, row.fingerprint): row for row in existing}

    for (kind, fingerprint), data in wanted.items():
        row = by_key.get((kind, fingerprint))
        if row is None:
            session.add(
                t.ReviewItem(
                    scholar_id=scholar.id,
                    kind=kind,
                    status="pending",
                    fingerprint=fingerprint,
                    title=data["title"],
                    payload=data["payload"],
                )
            )
            continue
        row.title = data["title"]
        row.payload = data["payload"]
        if row.status == "superseded":
            row.status = "pending"
            row.resolved_at = None

    for row in existing:
        if (row.kind, row.fingerprint) in wanted:
            continue
        if row.status == "pending":
            row.status = "superseded"
            row.resolved_at = func.now()


async def _save_identities(session: AsyncSession, scholar: t.Scholar, person: Person) -> None:
    existing_ids = set(
        (await session.scalars(
            select(t.Identity.id).where(t.Identity.scholar_id == scholar.id)
        )).all()
    )
    keep_ids: set[int] = set()
    for linked in person.identities:
        raw = linked.person
        row = await session.scalar(
            select(t.Identity).where(
                t.Identity.source == raw.source,
                t.Identity.source_id == raw.source_id,
            )
        )
        if row is None:
            row = t.Identity(
                scholar_id=scholar.id,
                source=raw.source,
                source_id=raw.source_id,
                name=raw.name,
                confidence=linked.confidence.value,
            )
            session.add(row)
        row.scholar_id = scholar.id
        row.name = raw.name
        row.alt_names = list(raw.alt_names)
        row.confidence = linked.confidence.value
        row.evidence = list(linked.evidence)
        row.description = raw.description
        row.birth_year = raw.birth_year
        row.death_year = raw.death_year
        row.works_count = raw.works_count
        row.affiliations = list(raw.affiliations)
        row.identifiers = {k: list(v) for k, v in raw.identifiers.items()}
        row.url = raw.url
        row.popularity = raw.popularity
        row.wikipedia_title = raw.wikipedia_title
        if row.id is None:
            await session.flush()
        keep_ids.add(row.id)

    stale = existing_ids - keep_ids
    if stale:
        await session.execute(delete(t.Identity).where(t.Identity.id.in_(stale)))


async def _save_work(session: AsyncSession, work: Work) -> t.Work:
    key = work_key(work)
    row = await session.scalar(select(t.Work).where(t.Work.work_key == key))
    if row is None:
        row = t.Work(
            work_key=key,
            title=work.title,
            title_key=title_key(work.title) or fold(work.title),
            category=work.category.value,
        )
        session.add(row)
    row.title = work.title
    row.title_key = title_key(work.title) or fold(work.title)
    row.category = work.category.value
    row.year = work.year
    row.venue = work.venue
    row.cover_url = work.cover_url
    row.cited_by = work.cited_by
    row.edition_count = work.edition_count
    if row.id is None:
        await session.flush()

    await session.execute(delete(t.WorkRecord).where(t.WorkRecord.work_id == row.id))
    for record in work.records:
        session.add(
            t.WorkRecord(
                work_id=row.id,
                source=record.source,
                source_id=record.source_id,
                title=record.title,
                category=record.category.value,
                role=record.role.value,
                year=record.year,
                authors=list(record.authors),
                venue=record.venue,
                doi=record.doi,
                isbns=list(record.isbns),
                languages=list(record.languages),
                cover_url=record.cover_url,
                cited_by=record.cited_by,
                edition_count=record.edition_count,
                links=[dataclasses.asdict(link) for link in record.links],
                raw_type=record.raw_type,
            )
        )

    await session.execute(delete(t.WorkLink).where(t.WorkLink.work_id == row.id))
    for position, link in enumerate(work.links):
        session.add(
            t.WorkLink(
                work_id=row.id,
                url=link.url,
                kind=link.kind,
                label=link.label,
                position=position,
            )
        )
    await session.flush()
    return row


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
async def get_profile(session: AsyncSession, scholar_id: int) -> Profile | None:
    scholar = await session.get(t.Scholar, scholar_id)
    if scholar is None:
        return None
    snapshot = await session.scalar(
        select(t.ScholarProfile).where(t.ScholarProfile.scholar_id == scholar_id)
    )
    identities = (
        await session.scalars(
            select(t.Identity)
            .where(t.Identity.scholar_id == scholar_id)
            .order_by(t.Identity.id)
        )
    ).all()
    person = Person(
        display_name=scholar.display_name,
        identities=[
            LinkedIdentity(
                person=RawPerson(
                    source=i.source,
                    source_id=i.source_id,
                    name=i.name,
                    alt_names=list(i.alt_names or []),
                    description=i.description,
                    birth_year=i.birth_year,
                    death_year=i.death_year,
                    works_count=i.works_count,
                    affiliations=list(i.affiliations or []),
                    identifiers=dict(i.identifiers or {}),
                    url=i.url,
                    popularity=i.popularity or 0,
                    wikipedia_title=i.wikipedia_title,
                ),
                confidence=Confidence(i.confidence),
                evidence=list(i.evidence or []),
            )
            for i in identities
        ],
        description=scholar.description,
        birth_year=scholar.birth_year,
        death_year=scholar.death_year,
        wikipedia_title=scholar.wikipedia_title,
    )

    associations = (
        await session.scalars(
            select(t.ScholarWork).where(t.ScholarWork.scholar_id == scholar_id)
        )
    ).all()
    work_ids = [a.work_id for a in associations]
    work_rows = {}
    records: dict[int, list[t.WorkRecord]] = {}
    links: dict[int, list[t.WorkLink]] = {}
    if work_ids:
        work_rows = {
            w.id: w
            for w in (
                await session.scalars(select(t.Work).where(t.Work.id.in_(work_ids)))
            ).all()
        }
        for record in (
            await session.scalars(
                select(t.WorkRecord)
                .where(t.WorkRecord.work_id.in_(work_ids))
                .order_by(t.WorkRecord.id)
            )
        ).all():
            records.setdefault(record.work_id, []).append(record)
        for link in (
            await session.scalars(
                select(t.WorkLink)
                .where(t.WorkLink.work_id.in_(work_ids))
                .order_by(t.WorkLink.position, t.WorkLink.id)
            )
        ).all():
            links.setdefault(link.work_id, []).append(link)

    works: list[Work] = []
    for assoc in associations:
        row = work_rows.get(assoc.work_id)
        if row is None:
            continue
        raw_records = [
            _record_from_row(r, Relation(assoc.relation))
            for r in records.get(assoc.work_id, [])
        ]
        work = Work(
            title=row.title,
            category=WorkCategory(row.category),
            relation=Relation(assoc.relation),
            year=row.year,
            role=WorkRole(assoc.role),
            records=raw_records,
            authors=list(raw_records[0].authors) if raw_records else [],
            venue=row.venue,
            dois=list(dict.fromkeys(r.doi for r in raw_records if r.doi)),
            isbns=list(dict.fromkeys(i for r in raw_records for i in r.isbns)),
            languages=list(dict.fromkeys(lang for r in raw_records for lang in r.languages)),
            cover_url=row.cover_url,
            cited_by=row.cited_by,
            edition_count=row.edition_count,
            links=[
                AccessLink(link.url, link.kind, link.label)
                for link in links.get(assoc.work_id, [])
            ],
        )
        works.append(work)

    alternatives = [
        _person_from_json(item) for item in (snapshot.alternatives if snapshot else [])
    ]
    flagged = [
        _raw_work_from_json(item) for item in (snapshot.flagged if snapshot else [])
    ]
    works.sort(
        key=lambda w: (
            w.relation != Relation.BY,
            w.role == WorkRole.CONTRIBUTOR,
            -(w.edition_count + w.cited_by),
        )
    )
    return Profile(
        query=snapshot.query if snapshot else scholar.display_name,
        person=person,
        works=works,
        alternatives=alternatives,
        bio=snapshot.bio if snapshot else None,
        bio_url=snapshot.bio_url if snapshot else None,
        source_status=dict(snapshot.source_status or {}) if snapshot else {},
        raw_work_count=snapshot.raw_work_count if snapshot else 0,
        flagged=flagged,
    )


def _record_from_row(row: t.WorkRecord, relation: Relation) -> RawWork:
    return RawWork(
        source=row.source,
        source_id=row.source_id,
        title=row.title,
        relation=relation,
        category=WorkCategory(row.category),
        role=WorkRole(row.role),
        year=row.year,
        authors=list(row.authors or []),
        venue=row.venue,
        doi=row.doi,
        isbns=list(row.isbns or []),
        languages=list(row.languages or []),
        cover_url=row.cover_url,
        cited_by=row.cited_by,
        edition_count=row.edition_count,
        links=[
            AccessLink(link["url"], link["kind"], link["label"])
            for link in (row.links or [])
        ],
        raw_type=row.raw_type,
    )


async def list_scholars(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    by_count = (
        select(func.count())
        .select_from(t.ScholarWork)
        .where(
            t.ScholarWork.scholar_id == t.Scholar.id,
            t.ScholarWork.relation == Relation.BY.value,
        )
        .correlate(t.Scholar)
        .scalar_subquery()
    )
    about_count = (
        select(func.count())
        .select_from(t.ScholarWork)
        .where(
            t.ScholarWork.scholar_id == t.Scholar.id,
            t.ScholarWork.relation == Relation.ABOUT.value,
        )
        .correlate(t.Scholar)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(
                t.Scholar,
                t.ScholarProfile,
                by_count.label("work_count"),
                about_count.label("about_count"),
            )
            .outerjoin(
                t.ScholarProfile, t.ScholarProfile.scholar_id == t.Scholar.id
            )
            .order_by(t.Scholar.updated_at.desc(), t.Scholar.display_name)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        {
            "id": scholar.id,
            "display_name": scholar.display_name,
            "birth_year": scholar.birth_year,
            "death_year": scholar.death_year,
            "description": scholar.description,
            "work_count": work_count or 0,
            "about_count": about_count_value or 0,
            "updated_at": scholar.updated_at,
            "refreshed_at": snapshot.refreshed_at if snapshot else None,
            "refresh_error": snapshot.refresh_error if snapshot else None,
        }
        for scholar, snapshot, work_count, about_count_value in rows
    ]


async def mark_refresh_failed(
    session: AsyncSession, scholar_id: int, error: str
) -> None:
    """Record a failed refresh without disturbing the last successful snapshot."""
    snapshot = await session.scalar(
        select(t.ScholarProfile).where(t.ScholarProfile.scholar_id == scholar_id)
    )
    if snapshot is None:
        scholar = await session.get(t.Scholar, scholar_id)
        if scholar is None:
            return
        snapshot = t.ScholarProfile(
            scholar_id=scholar_id,
            query=scholar.display_name,
            source_status={},
            raw_work_count=0,
            alternatives=[],
            flagged=[],
        )
        session.add(snapshot)
    snapshot.last_attempted_at = func.now()
    snapshot.refresh_error = error[:2000]
    await session.commit()


async def list_refresh_candidates(
    session: AsyncSession,
    *,
    limit: int = 50,
    stale_hours: int | None = None,
    scholar_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(t.Scholar, t.ScholarProfile)
        .outerjoin(t.ScholarProfile, t.ScholarProfile.scholar_id == t.Scholar.id)
        .order_by(
            t.ScholarProfile.last_attempted_at.asc().nullsfirst(),
            t.Scholar.display_name,
        )
        .limit(limit)
    )
    if scholar_ids:
        statement = statement.where(t.Scholar.id.in_(scholar_ids))
    if stale_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
        statement = statement.where(
            or_(
                t.ScholarProfile.last_attempted_at.is_(None),
                t.ScholarProfile.last_attempted_at < cutoff,
            )
        )
    rows = (await session.execute(statement)).all()
    return [
        {
            "id": scholar.id,
            "scholar_key": scholar.scholar_key,
            "display_name": scholar.display_name,
            "query": snapshot.query if snapshot else scholar.display_name,
            "last_attempted_at": (
                snapshot.last_attempted_at if snapshot else None
            ),
        }
        for scholar, snapshot in rows
    ]


async def list_review_items(
    session: AsyncSession,
    *,
    status: str | None = "pending",
    kind: str | None = None,
    scholar_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[t.ReviewItem], int]:
    filters = []
    if status is not None and status != "all":
        filters.append(t.ReviewItem.status == status)
    if kind is not None:
        filters.append(t.ReviewItem.kind == kind)
    if scholar_id is not None:
        filters.append(t.ReviewItem.scholar_id == scholar_id)

    total = await session.scalar(
        select(func.count()).select_from(t.ReviewItem).where(*filters)
    )
    rows = (
        await session.scalars(
            select(t.ReviewItem)
            .where(*filters)
            .order_by(t.ReviewItem.created_at.desc(), t.ReviewItem.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), total or 0


async def get_review_item(
    session: AsyncSession, item_id: int
) -> t.ReviewItem | None:
    return await session.get(t.ReviewItem, item_id)


async def update_review_item(
    session: AsyncSession,
    item_id: int,
    *,
    status: str,
    note: str | None = None,
) -> t.ReviewItem | None:
    item = await session.get(t.ReviewItem, item_id)
    if item is None:
        return None
    item.status = status
    if note is not None:
        item.note = note[:2000]
    item.resolved_at = func.now() if status != "pending" else None
    await session.commit()
    await session.refresh(item)
    return item
