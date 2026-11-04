"""Connector role heuristics, without touching the network."""

from kora.connectors.openalex import OpenAlexConnector
from kora.connectors.openlibrary import OpenLibraryConnector
from kora.models import Confidence, LinkedIdentity, Person, RawPerson, WorkRole


def person(source: str, source_id: str, name: str = "Chinua Achebe") -> Person:
    return Person(
        name,
        [
            LinkedIdentity(
                RawPerson(source, source_id, name, works_count=10),
                Confidence.HARD_ID,
                ["test"],
            )
        ],
    )


def openlibrary_doc(
    title: str, keys: list[str], names: list[str], subject: list[str] | None = None
) -> dict:
    doc = {"title": title, "author_key": keys, "author_name": names}
    if subject:
        doc["subject"] = subject
    return doc


def test_openlibrary_roles():
    connector = OpenLibraryConnector(http=None)
    p = person("openlibrary", "OL1A")

    assert connector._role_for(
        openlibrary_doc("Things Fall Apart", ["OL1A"], ["Chinua Achebe"]), p
    ) == WorkRole.AUTHOR

    assert connector._role_for(
        openlibrary_doc(
            "African Short Stories",
            ["OL1A", "OL2A"],
            ["Chinua Achebe", "C. L. Innes"],
        ),
        p,
    ) == WorkRole.EDITOR

    assert connector._role_for(
        openlibrary_doc("Poems of Black Africa", ["OL1A"], ["Chinua Achebe"]), p
    ) == WorkRole.EDITOR

    assert connector._role_for(
        openlibrary_doc("African Theatre", ["OL1A"], ["Chinua Achebe"]), p
    ) == WorkRole.EDITOR

    assert connector._role_for(
        openlibrary_doc(
            "Winds of Change",
            ["OL1A"],
            ["Chinua Achebe"],
            subject=["Anthologie", "Short stories, African (English)"],
        ),
        p,
    ) == WorkRole.EDITOR

    assert connector._role_for(
        openlibrary_doc(
            "Tapestry",
            ["OL2A", "OL1A"],
            ["Alan C. Purves", "Chinua Achebe"],
            subject=["Collections", "Literature", "Multicultural education"],
        ),
        p,
    ) == WorkRole.CONTRIBUTOR

    assert connector._role_for(
        openlibrary_doc(
            "Collected Poems",
            ["OL1A"],
            ["Chinua Achebe"],
            subject=["Collections", "Nigerian poetry"],
        ),
        p,
    ) == WorkRole.AUTHOR

    assert connector._role_for(
        openlibrary_doc(
            "A Month and A Day & Letters",
            ["OL2A", "OL1A"],
            ["Ken Saro-Wiwa", "Chinua Achebe"],
        ),
        p,
    ) == WorkRole.CONTRIBUTOR

    assert connector._role_for(
        openlibrary_doc(
            "'O' Level Literature in English Texts",
            ["OL1A"],
            ["Chinua Achebe"],
        ),
        p,
    ) == WorkRole.CONTRIBUTOR

    assert connector._role_for(
        openlibrary_doc(
            "Imprisoning a Revolution",
            ["OL2A", "OL1A"],
            ["Collective Antigone", "Chinua Achebe"],
        ),
        p,
    ) == WorkRole.CONTRIBUTOR

    assert connector._role_for(
        openlibrary_doc(
            "Prentice Hall Literature",
            ["OL2A", "OL1A"],
            ["Some Editor", "Chinua Achebe"],
        ),
        p,
    ) == WorkRole.CONTRIBUTOR

    assert connector._role_for(
        openlibrary_doc(
            "Another Africa",
            ["OL2A", "OL1A"],
            ["Robert Lyons", "Chinua Achebe"],
        ),
        p,
    ) == WorkRole.AUTHOR

    assert connector._role_for(
        openlibrary_doc(
            "Critical Fictions",
            ["OL2A", "OL3A", "OL1A", "OL4A"],
            ["Philomena Mariani", "Ama Ata Aidoo", "Chinua Achebe", "Someone Else"],
        ),
        p,
    ) == WorkRole.CONTRIBUTOR


def openalex_work(title: str, author_ids: list[str], work_type: str = "book") -> dict:
    return {
        "display_name": title,
        "type": work_type,
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/{author_id}"},
                "author_position": "first" if i == 0 else "middle",
            }
            for i, author_id in enumerate(author_ids)
        ],
    }


def test_openalex_roles():
    connector = OpenAlexConnector(http=None)
    p = person("openalex", "A1")

    assert connector._role_for(
        openalex_work("African Short Stories", ["A1", "A2"]), p
    ) == WorkRole.EDITOR

    assert connector._role_for(
        openalex_work("Poems of Black Africa", ["A1"]), p
    ) == WorkRole.EDITOR

    assert connector._role_for(
        openalex_work("Prentice Hall Literature", ["A2", "A1"]), p
    ) == WorkRole.CONTRIBUTOR

    corporate = openalex_work("Imprisoning a Revolution", ["A2", "A1"])
    corporate["authorships"][0]["author"]["display_name"] = "Collective Antigone"
    corporate["authorships"][1]["author"]["display_name"] = "Chinua Achebe"
    assert connector._role_for(corporate, p) == WorkRole.CONTRIBUTOR

    assert connector._role_for(
        openalex_work("Critical Fictions", ["A2", "A3", "A1", "A4"]), p
    ) == WorkRole.CONTRIBUTOR

    assert connector._role_for(
        openalex_work("A Multi-Author Article", ["A2", "A1", "A3", "A4"], "article"), p
    ) == WorkRole.AUTHOR
