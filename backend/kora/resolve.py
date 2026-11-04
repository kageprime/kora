"""Entity resolution: source identities -> canonical persons; records -> works.

Strategy (see architecture plan section 5):
1. Hard identifiers first. A Wikidata person is a hub whose ID claims
   (Open Library, OpenAlex, ORCID, ...) attach source identities deterministically.
2. Soft evidence second: name similarity plus dates and affiliations.
3. Grey zone (name-only matches) goes to a pluggable `Disambiguator`; this is
   where the LLM agent of section 10b plugs in. The default keeps them as
   GREY so they stay visible and reviewable.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Protocol

from kora.models import (
    AccessLink,
    Confidence,
    LinkedIdentity,
    Person,
    RawPerson,
    RawWork,
    Relation,
    Work,
    WorkCategory,
    WorkRole,
)
from kora.normalize import (
    best_name_similarity,
    fold,
    is_anthology_title,
    is_derivative_title,
    is_edited_anthology_title,
    is_generic_title,
    is_junk_title,
    name_key,
    name_tokens,
    strip_trailing_author,
    title_key,
)

NAME_MATCH = 90.0  # min name similarity to consider two identities related
SPAM_TITLES = {"updating doi via the form"}
ABOUT_TITLE_PREFIXES = (
    "conversations with",
    "interviews with",
    "an interview with",
    "interview with",
    "critical perspectives on",
    "a tribute to",
    "homage to",
    "reading ",
    "the cambridge companion to",
    "the novels of",
    "the writings of",
    "a biography of",
    "portrait of",
)
_ALTERNATIVE_MARKERS = (
    "vv.aa", "vv aa", "vvaa", "et al", "foreword by", "introduction by",
    "edited by", "unknown", "anonymous", " & ", " and ",
)


# --------------------------------------------------------------------------- #
# Disambiguation hook (AI layer seam)
# --------------------------------------------------------------------------- #
class Disambiguator(Protocol):
    def decide(self, hub: RawPerson, candidate: RawPerson, evidence: list[str]) -> Confidence | None:
        """Return HIGH/CONFLICT to override a grey-zone decision, or None to abstain."""
        ...


class NoopDisambiguator:
    def decide(self, hub: RawPerson, candidate: RawPerson, evidence: list[str]) -> Confidence | None:
        return None


# --------------------------------------------------------------------------- #
# Person resolution
# --------------------------------------------------------------------------- #
def _names(p: RawPerson) -> list[str]:
    return [p.name, *p.alt_names]


def _shares_hard_id(hub: RawPerson, cand: RawPerson) -> str | None:
    """Identifier evidence linking a hub to a candidate, if any."""
    if cand.source_id in hub.identifiers.get(cand.source, []):
        return f"{hub.source} {hub.source_id} lists {cand.source} ID {cand.source_id}"
    for scheme, values in cand.identifiers.items():
        shared = set(values) & set(hub.identifiers.get(scheme, []))
        if shared:
            return f"shared {scheme} {sorted(shared)[0]}"
    return None


def _year_evidence(a: RawPerson, b: RawPerson) -> tuple[list[str], bool]:
    """(supporting evidence, conflict?) from birth/death years."""
    support: list[str] = []
    for label, x, y in (("birth", a.birth_year, b.birth_year), ("death", a.death_year, b.death_year)):
        if x and y:
            if abs(x - y) <= 1:
                support.append(f"{label} year {y} matches")
            else:
                return [], True
    return support, False


def _affiliation_evidence(a: RawPerson, b: RawPerson) -> list[str]:
    fa = {fold(x) for x in a.affiliations}
    hits = [x for x in b.affiliations if fold(x) in fa]
    return [f"affiliation '{h}' matches" for h in hits[:2]]


def _alias_evidence(hub: RawPerson, cand: RawPerson) -> str | None:
    """Exact match on a multi-token alias, e.g. Wikidata's 'James Ngugi'.

    The hub's primary name is excluded: a plain name match should still be grey
    unless dates/affiliations corroborate it.
    """
    primary = name_key(hub.name)
    hub_keys = {
        name_key(n) for n in hub.alt_names
        if len(name_tokens(n)) >= 2 and name_key(n) != primary
    }
    cand_keys = {name_key(n) for n in _names(cand) if len(name_tokens(n)) >= 2}
    shared = hub_keys & cand_keys
    return f"alias '{sorted(shared)[0]}' matches" if shared else None


def score_pair(hub: RawPerson, cand: RawPerson) -> tuple[Confidence | None, list[str]]:
    """Classify how `cand` relates to `hub`. None means unrelated."""
    hard = _shares_hard_id(hub, cand)
    if hard:
        return Confidence.HARD_ID, [hard]
    alias = _alias_evidence(hub, cand)
    if alias:
        years, conflict = _year_evidence(hub, cand)
        if conflict:
            return Confidence.CONFLICT, [alias + " but life dates differ"]
        return Confidence.HIGH, [alias, *years]
    sim = best_name_similarity(_names(hub), _names(cand))
    if sim < NAME_MATCH:
        return None, []
    years, conflict = _year_evidence(hub, cand)
    if conflict:
        return Confidence.CONFLICT, [f"name {sim:.0f}% similar but life dates differ"]
    evidence = [f"name {sim:.0f}% similar", *years, *_affiliation_evidence(hub, cand)]
    if len(evidence) > 1:
        return Confidence.HIGH, evidence
    return Confidence.GREY, evidence


def _person_from_hub(hub: RawPerson) -> Person:
    return Person(
        display_name=hub.name,
        identities=[LinkedIdentity(hub, Confidence.HARD_ID, ["identity hub"])],
        description=hub.description,
        birth_year=hub.birth_year,
        death_year=hub.death_year,
        wikipedia_title=hub.wikipedia_title,
    )


def resolve_people(
    query: str,
    candidates: list[RawPerson],
    disambiguator: Disambiguator | None = None,
    attach_grey: bool = True,
) -> list[Person]:
    """Cluster raw identities into ranked canonical persons.

    Wikidata humans act as hubs. Every other candidate attaches to the best hub
    (hard ID > high > grey). Grey matches attach only if exactly one hub is
    name-compatible (unambiguous). Leftovers are clustered among themselves.
    """
    disambiguator = disambiguator or NoopDisambiguator()
    query_tokens = set(name_tokens(query))

    # Drop empty shells (e.g. Open Library authors with zero works).
    usable = [c for c in candidates if c.source == "wikidata" or (c.works_count or 0) > 0]

    hubs = [c for c in usable if c.source == "wikidata"]
    others = [c for c in usable if c.source != "wikidata"]
    persons = [_person_from_hub(h) for h in hubs]
    leftovers: list[RawPerson] = []

    for cand in others:
        scored = [(i, *score_pair(h, cand)) for i, h in enumerate(hubs)]
        scored = [(i, conf, ev) for i, conf, ev in scored if conf and conf != Confidence.CONFLICT]
        hard = [s for s in scored if s[1] == Confidence.HARD_ID]
        high = [s for s in scored if s[1] == Confidence.HIGH]
        grey = [s for s in scored if s[1] == Confidence.GREY]

        choice = hard[0] if hard else (high[0] if len(high) == 1 else None)
        if choice is None and not high and len(grey) == 1:
            i, conf, ev = grey[0]
            override = disambiguator.decide(hubs[i], cand, ev)
            if override == Confidence.HIGH:
                choice = (i, Confidence.HIGH, [*ev, "confirmed by disambiguator"])
            elif override != Confidence.CONFLICT and attach_grey:
                choice = grey[0]

        if choice:
            i, conf, ev = choice
            persons[i].identities.append(LinkedIdentity(cand, conf, ev))
        else:
            leftovers.append(cand)

    persons.extend(_cluster_leftovers(leftovers))
    # Only keep persons plausibly matching the query.
    persons = [p for p in persons if _matches_query(p, query_tokens)]
    persons.sort(key=_rank_key, reverse=True)
    return persons


def _cluster_leftovers(cands: list[RawPerson]) -> list[Person]:
    clusters: list[list[RawPerson]] = []
    for c in sorted(cands, key=lambda p: -(p.works_count or 0)):
        for cl in clusters:
            seed = cl[0]
            if seed.source == c.source:
                continue  # same source split already means "different" there
            conf, _ = score_pair(seed, c)
            if conf in (Confidence.HIGH, Confidence.HARD_ID):
                cl.append(c)
                break
        else:
            clusters.append([c])
    out = []
    for cl in clusters:
        seed = cl[0]
        p = Person(
            display_name=seed.name,
            identities=[LinkedIdentity(seed, Confidence.GREY, ["no identity hub"])],
            description=seed.description,
            birth_year=seed.birth_year,
            death_year=seed.death_year,
        )
        for c in cl[1:]:
            _, ev = score_pair(seed, c)
            p.identities.append(LinkedIdentity(c, Confidence.HIGH, ev))
        out.append(p)
    return out


def _matches_query(p: Person, query_tokens: set[str]) -> bool:
    if not query_tokens:
        return True
    for ident in p.identities:
        for n in _names(ident.person):
            folded = fold(n)
            # Contributor lists and corporate labels leak in as OpenAlex aliases.
            if any(marker in folded for marker in _ALTERNATIVE_MARKERS):
                continue
            toks = set(name_tokens(n))
            if len(toks) > 8:
                continue
            if query_tokens <= toks or best_name_similarity([n], [" ".join(query_tokens)]) >= NAME_MATCH:
                return True
    return False


def _rank_key(p: Person) -> tuple[int, int, int]:
    has_hub = int(any(i.person.source == "wikidata" for i in p.identities))
    linked = len(p.identities)
    popularity = sum(i.person.popularity for i in p.identities)
    return (has_hub * min(linked, 3), linked, popularity)


# --------------------------------------------------------------------------- #
# Work deduplication (FRBR-lite: many source records -> one Work)
# --------------------------------------------------------------------------- #
class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def merge_works(records: list[RawWork]) -> list[Work]:
    """Group records describing the same work (by DOI, ISBN or compatible titles)."""
    uf = _UnionFind(len(records))
    index: dict[str, int] = {}

    def link(key: str, i: int) -> None:
        if key in index:
            uf.union(index[key], i)
        else:
            index[key] = i

    # Exact identifiers always win, even when sources disagree about the type.
    for i, r in enumerate(records):
        if r.doi:
            link(f"doi:{r.doi}", i)
        for isbn in r.isbns:
            link(f"isbn:{isbn}", i)

    # Title-only matching is deliberately conservative: it must not merge a book
    # with a review of it, or a novel with its study guide.
    buckets: dict[tuple[str, str], list[int]] = {}
    for i, r in enumerate(records):
        key = title_key(strip_trailing_author(r.title, r.authors))
        if key:
            buckets.setdefault((r.relation.value, key), []).append(i)

    for idxs in buckets.values():
        for a_pos, a_idx in enumerate(idxs):
            for b_idx in idxs[a_pos + 1:]:
                if _can_merge_by_title(records[a_idx], records[b_idx]):
                    uf.union(a_idx, b_idx)

    groups: dict[int, list[RawWork]] = {}
    for i, r in enumerate(records):
        groups.setdefault(uf.find(i), []).append(r)
    return [_build_work(g) for g in groups.values()]


def _can_merge_by_title(a: RawWork, b: RawWork) -> bool:
    if a.relation != b.relation or a.category != b.category:
        return False

    key = title_key(strip_trailing_author(a.title, a.authors))
    if is_generic_title(key):
        return a.year == b.year and fold(a.venue or "") == fold(b.venue or "")

    derivative_a = is_derivative_title(a.title)
    derivative_b = is_derivative_title(b.title)
    if derivative_a != derivative_b:
        return False
    if derivative_a and derivative_b:
        return _year_close(a, b) and _first_surname(a.authors) == _first_surname(b.authors)

    if a.relation == Relation.ABOUT:
        return _first_surname(a.authors) == _first_surname(b.authors)

    if a.category == WorkCategory.BOOK:
        return True

    # Articles/theses with the same title in the same year window are usually the
    # same record reported by two sources; without that, keep them separate.
    return _year_close(a, b) and _first_surname(a.authors) == _first_surname(b.authors)


def _year_close(a: RawWork, b: RawWork) -> bool:
    if a.year and b.year:
        return abs(a.year - b.year) <= 1
    return True


def _first_surname(authors: list[str]) -> str:
    if not authors:
        return ""
    tokens = name_tokens(authors[0])
    return tokens[-1] if tokens else ""


_ROLE_RANK = {WorkRole.AUTHOR: 0, WorkRole.EDITOR: 1, WorkRole.CONTRIBUTOR: 2}
_BOOK_SOURCE_RANK = {"openlibrary": 0, "openalex": 1}
_ARTICLE_SOURCE_RANK = {"openalex": 0, "crossref": 1, "openlibrary": 9}


def _primary_key(r: RawWork) -> tuple[int, int, int]:
    role_rank = _ROLE_RANK.get(r.role, 3)
    if r.category == WorkCategory.BOOK:
        return (role_rank, _BOOK_SOURCE_RANK.get(r.source, 9), r.year or 9999)
    return (role_rank, _ARTICLE_SOURCE_RANK.get(r.source, 9), -(r.cited_by or 0))


_CATEGORY_PRIORITY = [
    WorkCategory.BOOK, WorkCategory.THESIS, WorkCategory.ARTICLE,
    WorkCategory.DATASET, WorkCategory.OTHER,
]
_LINK_PRIORITY = {"oa_pdf": 0, "borrow": 1, "publisher": 2, "library": 3, "landing": 4}


def _build_work(group: list[RawWork]) -> Work:
    group = sorted(group, key=_primary_key)
    primary = group[0]
    years = [r.year for r in group if r.year]
    categories = {r.category for r in group}
    category = next(c for c in _CATEGORY_PRIORITY if c in categories or c == WorkCategory.OTHER)
    relation = Relation.BY if any(r.relation == Relation.BY for r in group) else Relation.ABOUT
    roles = {r.role for r in group}
    author_records = [r for r in group if r.role == WorkRole.AUTHOR]
    contributor_records = [r for r in group if r.role == WorkRole.CONTRIBUTOR]
    if WorkRole.EDITOR in roles and (
        is_anthology_title(primary.title) or is_edited_anthology_title(primary.title)
    ):
        # Sources disagree about whether an anthology's compiler is an author;
        # an explicit editor signal plus an anthology title should win.
        role = WorkRole.EDITOR
    elif author_records and contributor_records and max(
        len(r.authors) for r in contributor_records
    ) > max(len(r.authors) for r in author_records):
        # OpenAlex often truncates a book's author list to the person alone;
        # Open Library's longer contributor list is the better signal.
        role = WorkRole.CONTRIBUTOR
    elif WorkRole.AUTHOR in roles:
        role = WorkRole.AUTHOR
    elif WorkRole.EDITOR in roles:
        role = WorkRole.EDITOR
    else:
        role = WorkRole.CONTRIBUTOR

    links: list[AccessLink] = []
    seen_urls: set[str] = set()
    for r in group:
        for link in r.links:
            if link.url not in seen_urls:
                seen_urls.add(link.url)
                links.append(link)
    links.sort(key=lambda l: _LINK_PRIORITY.get(l.kind, 9))

    def uniq(values: list[str]) -> list[str]:
        return list(dict.fromkeys(v for v in values if v))

    authors = primary.authors or next((r.authors for r in group if r.authors), [])
    return Work(
        title=primary.title.strip() or _best_title(group),
        category=category,
        relation=relation,
        year=min(years) if years else None,
        role=role,
        records=group,
        authors=authors[:10],
        venue=primary.venue,
        dois=uniq([r.doi for r in group if r.doi]),
        isbns=uniq([i for r in group for i in r.isbns]),
        languages=uniq([lang for r in group for lang in r.languages]),
        cover_url=next((r.cover_url for r in group if r.cover_url), None),
        cited_by=sum(r.cited_by or 0 for r in group),
        edition_count=max([r.edition_count or 0 for r in group] + [len(group)]),
        links=links,
    )


def _best_title(group: list[RawWork]) -> str:
    """Most common title among records, preferring Open Library's casing for books."""
    for r in group:
        if r.source == "openlibrary":
            return r.title
    counts = Counter(r.title.strip() for r in group)
    return counts.most_common(1)[0][0]


def title_overlap(confirmed: list[RawWork], titles: list[str]) -> list[str]:
    """Distinctive titles shared between a confirmed bibliography and a candidate's titles."""
    known = {title_key(r.title) for r in confirmed if r.relation == Relation.BY}
    known = {k for k in known if k and not is_generic_title(k)}
    shared: list[str] = []
    for t in titles:
        k = title_key(t)
        if k in known and k not in shared:
            shared.append(k)
    return shared


MIN_SHARED_TITLES = 2


def promote_by_title_overlap(identity: LinkedIdentity, shared: list[str]) -> bool:
    """Grey -> HIGH when the candidate shares enough distinctive titles."""
    if identity.confidence != Confidence.GREY or len(shared) < MIN_SHARED_TITLES:
        return False
    sample = ", ".join(f"'{s}'" for s in shared[:3])
    identity.confidence = Confidence.HIGH
    identity.evidence.append(f"{len(shared)} shared work titles ({sample})")
    return True


def flag_suspect_records(person: Person, records: list[RawWork]) -> tuple[list[RawWork], list[RawWork]]:
    """Split records into (kept, flagged) using cheap sanity rules.

    Aggregated author IDs (especially OpenAlex) contain misattributions. A non-book
    work 'by' someone dated >10 years after their death, before they could have
    published, in the future, or carrying a known spam title is almost certainly
    wrong. Flagged records stay inspectable (and are a natural task for the AI
    disambiguation agent) but are excluded from the bibliography.
    """
    kept: list[RawWork] = []
    flagged: list[RawWork] = []
    death, birth = person.death_year, person.birth_year
    current_year = datetime.now().year
    for r in records:
        reason = None
        if r.relation == Relation.BY:
            if r.title.strip().lower() in SPAM_TITLES:
                reason = "metadata spam"
            elif is_junk_title(r.title):
                reason = "metadata junk"
            elif r.year and r.year > current_year + 1:
                reason = "future-dated"
            elif death and r.category != WorkCategory.BOOK and r.year and r.year > death + 10:
                reason = "posthumous"
            elif birth and r.year and r.year < birth:
                # Impossible metadata year (e.g. Soyinka's "The Strong Breed"
                # dated 1900); repair it rather than discard a real work.
                r.year = None
            elif birth and r.year and r.year < birth + 18:
                # No category exemption: a book published before the author was
                # 18 is almost always a namesake/conflation.
                reason = "pre-birth"
        if reason:
            flagged.append(r)
        else:
            kept.append(r)
    return kept, flagged


def _drop_person_from_authors(authors: list[str], person_name: str | None) -> list[str]:
    """Reviews are often attributed to the book's author; do not show them as author."""
    if not person_name or not authors:
        return authors
    key = name_key(person_name)
    kept = [a for a in authors if name_key(a) != key]
    return kept or authors


def _surname(name: str) -> str:
    text = fold(name).replace("’", "'")
    text = text.split(";")[-1].strip()
    text = re.sub(r"\b(1[5-9]\d\d|20\d\d)\b.*$", "", text).strip(" .,;:()[]")
    if "," in text:
        text = text.split(",")[0].strip()
    parts = text.split()
    return parts[-1].strip(".,;:()[]") if parts else ""


def _plausible_person_name(name: str) -> bool:
    folded = fold(name)
    if any(marker in folded for marker in _ALTERNATIVE_MARKERS):
        return False
    if ";" in name:
        return False
    return 1 <= len(name_tokens(name)) <= 6


def _title_is_about_person(title: str, person_name: str | None) -> bool:
    """Spot biographies, interview collections, proceedings and study notes.

    Open Library author records are often conflated with titles *about* the
    author ("Soyinka", "Notes on Soyinka's ...", "The Essential Soyinka").
    """
    if not person_name:
        return False
    ft = fold(title)
    fn = fold(person_name)
    fs = _surname(person_name)
    if not fn:
        return False
    if ft.strip(" :") in {fn, fs}:
        return True
    if is_derivative_title(title) and (fn in ft or fs in ft):
        return True
    if ft.startswith((f"{fs}'s", f"{fs}’s", f"{fs} as ", f"{fs} speaks", f"{fn} speaks")):
        return True
    if ft.startswith((f"the essential {fs}", f"essential {fs}")):
        return True
    if "a life in full" in ft:
        return True
    if fn in ft:
        if is_anthology_title(title) or ft.startswith(ABOUT_TITLE_PREFIXES):
            return True
        if "symposium" in ft or "proceedings" in ft:
            return True
        if ":" in title:
            return True
    return False


def reclassify_reviews(records: list[RawWork], person_name: str | None = None) -> int:
    """OpenAlex often attributes *reviews of* a book to the book's author.

    Run before `merge_works`: a record 'by' the person whose title matches one of
    their own books is really about them if it is a review, a derivative study
    guide, or written by someone else. Returns count changed.
    """
    own_books: dict[str, RawWork] = {}
    for r in records:
        if r.relation != Relation.BY or r.category != WorkCategory.BOOK:
            continue
        if is_derivative_title(r.title):
            continue
        key = title_key(strip_trailing_author(r.title, r.authors))
        if key:
            own_books.setdefault(key, r)

    changed = 0
    for r in records:
        if r.relation != Relation.BY:
            continue
        if _title_is_about_person(r.title, person_name):
            r.relation = Relation.ABOUT
            r.authors = _drop_person_from_authors(r.authors, person_name)
            changed += 1
            continue
        key = title_key(strip_trailing_author(r.title, r.authors))
        book = own_books.get(key)
        if not book or r is book:
            continue
        derivative = is_derivative_title(r.title)
        review = r.raw_type in ("book-review", "review")
        different_first = bool(_first_surname(r.authors)) and (
            _first_surname(r.authors) != _first_surname(book.authors)
        )
        if derivative or review or (r.category != WorkCategory.BOOK and different_first):
            r.relation = Relation.ABOUT
            r.authors = _drop_person_from_authors(r.authors, person_name)
            changed += 1
    return changed


def is_credible_alternative(
    person: Person,
    query: str | None = None,
    known_names: list[str] | None = None,
) -> bool:
    """Filter one-work shells and unrelated names out of the 'did you mean' list.

    The authoritative search still returns title-like author strings
    ("VV.AA. - WOLE SOYINKA") and unrelated researchers whose names OpenAlex
    fuzzy-matched. Obscure researchers still appear as the primary result; this
    only controls suggestions.
    """
    folded_name = fold(person.display_name)
    if any(marker in folded_name for marker in _ALTERNATIVE_MARKERS):
        return False

    if query:
        names = [
            n for n in [query, *(known_names or [])] if _plausible_person_name(n)
        ]
        candidates = [
            n
            for n in [
                person.display_name,
                *(i.person.name for i in person.identities),
                *(n for i in person.identities for n in i.person.alt_names),
            ]
            if _plausible_person_name(n)
        ]
        exact = {name_key(n) for n in names if name_tokens(n)} & {
            name_key(c) for c in candidates if name_tokens(c)
        }
        if not exact:
            query_surnames = {_surname(n) for n in names if _surname(n)}
            candidate_surnames = {_surname(c) for c in candidates if _surname(c)}
            same_surname = any(
                best_name_similarity([q], [c]) >= 85
                for q in query_surnames
                for c in candidate_surnames
            )
            if not same_surname or best_name_similarity(names, candidates) < 85:
                return False

    if any(i.person.source == "wikidata" for i in person.identities):
        return True
    if len(person.identities) >= 2:
        return True
    works = sum(i.person.works_count or 0 for i in person.identities)
    return works >= 3 or bool(person.description)
