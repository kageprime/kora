"""Shared synthetic data for API and storage tests."""

from __future__ import annotations

import pytest

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


def build_profile() -> Profile:
    wikidata = RawPerson(
        "wikidata",
        "Q302910",
        "Chinua Achebe",
        alt_names=["Albert Chinualumogu Achebe"],
        description="Nigerian writer",
        birth_year=1930,
        death_year=2013,
        identifiers={"openlibrary": ["OL1A"], "openalex": ["A1"]},
        popularity=100,
        wikipedia_title="Chinua Achebe",
    )
    openlibrary = RawPerson("openlibrary", "OL1A", "Chinua Achebe", works_count=200)
    openalex = RawPerson("openalex", "A1", "Chinua Achebe", works_count=500)
    grey = RawPerson("openalex", "A-grey", "C. Achebe", works_count=3)
    person = Person(
        "Chinua Achebe",
        identities=[
            LinkedIdentity(wikidata, Confidence.HARD_ID, ["identity hub"]),
            LinkedIdentity(openlibrary, Confidence.HARD_ID, ["shared openlibrary ID"]),
            LinkedIdentity(openalex, Confidence.HIGH, ["name 100% similar"]),
            LinkedIdentity(grey, Confidence.GREY, ["name-only match"]),
        ],
        description="Nigerian writer",
        birth_year=1930,
        death_year=2013,
        wikipedia_title="Chinua Achebe",
    )

    things_record_ol = RawWork(
        "openlibrary",
        "OLW1",
        "Things Fall Apart",
        category=WorkCategory.BOOK,
        role=WorkRole.AUTHOR,
        year=1958,
        authors=["Chinua Achebe"],
        isbns=["9780385474542"],
        languages=["en"],
        edition_count=50,
        links=[
            AccessLink("https://openlibrary.org/works/OLW1", "library", "Open Library"),
            AccessLink("https://archive.org/details/thingsfallapart", "borrow", "Borrow"),
        ],
    )
    things_record_oa = RawWork(
        "openalex",
        "W1",
        "Things Fall Apart",
        category=WorkCategory.BOOK,
        role=WorkRole.AUTHOR,
        year=1958,
        authors=["Chinua Achebe"],
        languages=["en"],
        cited_by=1200,
        links=[AccessLink("https://openalex.org/W1", "landing", "OpenAlex record")],
    )
    works = [
        Work(
            title="Things Fall Apart",
            category=WorkCategory.BOOK,
            relation=Relation.BY,
            year=1958,
            role=WorkRole.AUTHOR,
            records=[things_record_ol, things_record_oa],
            authors=["Chinua Achebe"],
            isbns=["9780385474542"],
            languages=["en"],
            edition_count=50,
            cited_by=1200,
            links=[*things_record_ol.links, *things_record_oa.links],
        ),
        Work(
            title="Winds of Change",
            category=WorkCategory.BOOK,
            relation=Relation.BY,
            year=1977,
            role=WorkRole.EDITOR,
            records=[
                RawWork(
                    "openlibrary",
                    "OLW2",
                    "Winds of Change",
                    category=WorkCategory.BOOK,
                    role=WorkRole.EDITOR,
                    year=1977,
                    authors=["Chinua Achebe"],
                    links=[AccessLink("https://openlibrary.org/works/OLW2", "library", "Open Library")],
                )
            ],
            authors=["Chinua Achebe"],
            languages=["en"],
        ),
        Work(
            title="Tapestry",
            category=WorkCategory.BOOK,
            relation=Relation.BY,
            year=1994,
            role=WorkRole.CONTRIBUTOR,
            records=[
                RawWork(
                    "openlibrary",
                    "OLW3",
                    "Tapestry",
                    category=WorkCategory.BOOK,
                    role=WorkRole.CONTRIBUTOR,
                    year=1994,
                    authors=["Alan C. Purves", "Chinua Achebe"],
                )
            ],
            authors=["Alan C. Purves", "Chinua Achebe"],
            languages=["en"],
        ),
        Work(
            title="Conversations with Chinua Achebe",
            category=WorkCategory.BOOK,
            relation=Relation.ABOUT,
            year=1997,
            role=WorkRole.AUTHOR,
            records=[
                RawWork(
                    "openlibrary",
                    "OLW4",
                    "Conversations with Chinua Achebe",
                    relation=Relation.ABOUT,
                    category=WorkCategory.BOOK,
                    year=1997,
                    authors=["Bernth Lindfors"],
                )
            ],
            authors=["Bernth Lindfors"],
            languages=["en"],
        ),
    ]
    alternative = Person("Chinua Achebe (critic)", description="Different person")
    flagged = RawWork(
        "openalex",
        "W404",
        "A Future Book",
        category=WorkCategory.BOOK,
        year=2099,
        authors=["Chinua Achebe"],
    )
    return Profile(
        query="Chinua Achebe",
        person=person,
        works=works,
        alternatives=[alternative],
        bio="Chinua Achebe was a Nigerian novelist.",
        bio_url="https://en.wikipedia.org/wiki/Chinua_Achebe",
        source_status={"openlibrary.by": "ok (2 in 0.1s)", "openalex.by": "ok (2 in 0.2s)"},
        raw_work_count=4,
        flagged=[flagged],
    )


@pytest.fixture
def sample_profile() -> Profile:
    return build_profile()
