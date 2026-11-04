"""End-to-end aggregator test with fake connectors (no network)."""

from kora.aggregator import Aggregator
from kora.connectors.base import BaseConnector
from kora.models import Person, RawPerson, RawWork, Relation, WorkCategory


class FakeWikidata(BaseConnector):
    name = "wikidata"

    async def search_people(self, query):
        return [RawPerson("wikidata", "Q302910", "Ngũgĩ wa Thiong'o", birth_year=1938,
                          death_year=2025, identifiers={"openlibrary": ["OL41631A"]}, popularity=90)]


class FakeOpenLibrary(BaseConnector):
    name = "openlibrary"

    async def search_people(self, query):
        return [RawPerson("openlibrary", "OL41631A", "Ngũgĩ wa Thiongʼo", works_count=67)]

    async def works_by(self, person):
        assert person.ids("openlibrary") == ["OL41631A"]
        return [
            RawWork("openlibrary", "OL1", "Decolonising the Mind", category=WorkCategory.BOOK, year=1986),
            RawWork("openlibrary", "OL2", "Petals of Blood", category=WorkCategory.BOOK, year=1977),
        ]


class FakeOpenAlex(BaseConnector):
    name = "openalex"

    async def search_people(self, query):
        return [RawPerson("openalex", "A1", "Ngugi wa Thiongo", works_count=205),
                RawPerson("openalex", "A2", "Ngugi wa Thiongo", works_count=2)]

    async def sample_titles(self, source_id, limit=50):
        return {"A1": ["Decolonising the mind", "Petals of blood", "Moving the Centre"],
                "A2": ["Soil chemistry of Kiambu"]}[source_id]

    async def works_by(self, person: Person):
        ids = person.ids("openalex")
        assert ids == ["A1"], ids  # only promoted identity, never the grey A2
        return [
            RawWork("openalex", "W1", "Decolonising the Mind", category=WorkCategory.BOOK, year=1986,
                    cited_by=5000),
            RawWork("openalex", "W2", "Moving the Centre", category=WorkCategory.ARTICLE, year=1993),
        ]

    async def works_about(self, person):
        raise RuntimeError("rate limited")  # must degrade gracefully


async def test_aggregator_resolves_promotes_and_merges():
    agg = Aggregator(http=None, connectors=[FakeWikidata(None), FakeOpenAlex(None), FakeOpenLibrary(None)])
    profile = await agg.build_profile("ngugi wa thiongo")
    assert profile is not None
    conf = {i.person.source_id: i.confidence for i in profile.person.identities}
    assert conf["A1"] == "high" and conf["A2"] == "grey"

    titles = {w.title: w for w in profile.works}
    assert set(titles) == {"Decolonising the Mind", "Petals of Blood", "Moving the Centre"}
    assert titles["Decolonising the Mind"].sources == ["openalex", "openlibrary"]
    assert all(w.relation == Relation.BY for w in profile.works)
    assert profile.source_status["openalex.about"].startswith("failed")
    assert profile.raw_work_count == 4
