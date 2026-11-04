"""Golden-check mechanics and fixture integrity (no network)."""

from pathlib import Path

from kora.golden import check_profile, load_fixture, profile_stats
from kora.models import (
    Person,
    Profile,
    Relation,
    Work,
    WorkCategory,
    WorkRole,
)

FIXTURE = Path(__file__).parent / "golden" / "authors.json"


def work(title: str, role: WorkRole = WorkRole.AUTHOR, relation: Relation = Relation.BY) -> Work:
    return Work(
        title=title,
        category=WorkCategory.BOOK,
        relation=relation,
        year=2000,
        role=role,
        languages=["en"],
    )


def minimal_profile() -> Profile:
    return Profile(
        query="Chinua Achebe",
        person=Person("Chinua Achebe", birth_year=1930, death_year=2013),
        works=[
            work("Things Fall Apart"),
            work("Tapestry", WorkRole.CONTRIBUTOR),
            work("Winds of Change", WorkRole.EDITOR),
            work("Conversations with Chinua Achebe", relation=Relation.ABOUT),
        ],
    )


def test_golden_fixture_is_valid():
    fixture = load_fixture(FIXTURE)
    queries = [a["query"] for a in fixture["authors"]]
    assert len(queries) == len(set(queries)) == 4
    assert {"Chinua Achebe", "Wole Soyinka", "Ngugi wa Thiong'o", "Wangari Maathai"} == set(queries)
    for author in fixture["authors"]:
        assert author["display_name"]
        assert isinstance(author["counts"], dict)


def test_check_profile_roles_counts_and_about():
    spec = {
        "display_name": "Chinua Achebe",
        "birth_year": 1930,
        "death_year": 2013,
        "must_have_authored": ["Things Fall Apart"],
        "must_have_edited": ["Winds of Change"],
        "must_have_contributor": ["Tapestry"],
        "must_be_about": ["Conversations with Chinua Achebe"],
        "must_not_be_authored": ["Tapestry", "Winds of Change"],
        "counts": {
            "authored_all_min": 1,
            "authored_all_max": 1,
            "contributor_min": 1,
            "about_min": 1,
            "flagged_max": 0,
        },
    }
    profile = minimal_profile()
    failures, stats = check_profile(spec, profile)
    assert failures == []
    assert stats["authored_all"] == 1
    assert profile_stats(profile)["about"] == 1

    spec["must_have_authored"] = ["Arrow of God"]
    failures, _ = check_profile(spec, profile)
    assert any("Arrow of God" in failure for failure in failures)


def test_check_profile_reports_failed_source_and_wrong_role():
    profile = minimal_profile()
    profile.source_status = {"openalex.by": "failed: timeout"}
    spec = {
        "must_not_be_authored": ["Things Fall Apart"],
        "counts": {"authored_all_max": 0},
    }
    failures, _ = check_profile(spec, profile)
    assert any("wrongly authored" in failure for failure in failures)
    assert any("openalex.by" in failure for failure in failures)
