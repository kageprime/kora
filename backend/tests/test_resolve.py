from kora.models import (
    Confidence,
    LinkedIdentity,
    Person,
    RawPerson,
    RawWork,
    Relation,
    WorkCategory,
    WorkRole,
)
from kora.resolve import (
    flag_suspect_records,
    is_credible_alternative,
    merge_works,
    promote_by_title_overlap,
    reclassify_reviews,
    resolve_people,
    title_overlap,
)


def hub(**kw) -> RawPerson:
    base = dict(
        source="wikidata", source_id="Q155845", name="Chinua Achebe",
        alt_names=["Albert Chinualumogu Achebe"], birth_year=1930, death_year=2013,
        affiliations=["University of Ibadan"],
        identifiers={"openlibrary": ["OL78910A"], "viaf": ["24596756"]}, popularity=120,
    )
    base.update(kw)
    return RawPerson(**base)


def oa(source_id: str, **kw) -> RawPerson:
    base = dict(source="openalex", source_id=source_id, name="Chinua Achebe", works_count=10)
    base.update(kw)
    return RawPerson(**base)


# --------------------------------------------------------------------- people
def test_hard_id_links_open_library_author_to_wikidata_hub():
    ol = RawPerson("openlibrary", "OL78910A", "Chinua Achebe", works_count=271)
    [person] = resolve_people("chinua achebe", [hub(), ol])
    conf = {i.person.source_id: i.confidence for i in person.identities}
    assert conf["OL78910A"] == Confidence.HARD_ID
    assert person.ids("openlibrary") == ["OL78910A"]


def test_dates_or_affiliation_give_high_confidence_name_only_is_grey():
    a = oa("A1", alt_names=["Achebe, Chinua 1930-2013"], birth_year=1930, death_year=2013)
    b = oa("A2", affiliations=["University of Ibadan"])
    c = oa("A3")
    [person] = resolve_people("chinua achebe", [hub(), a, b, c])
    conf = {i.person.source_id: i.confidence for i in person.identities}
    assert conf == {"Q155845": "hard-id", "A1": "high", "A2": "high", "A3": "grey"}
    # Grey identities are visible but excluded from work fetching by default.
    assert person.ids("openalex") == ["A1", "A2"]
    assert person.ids("openalex", include_grey=True) == ["A1", "A2", "A3"]


def test_conflicting_life_dates_never_merge():
    other = oa("A9", birth_year=1985)
    people = resolve_people("chinua achebe", [hub(), other])
    hub_person = next(p for p in people if p.identities[0].person.source == "wikidata")
    assert all(i.person.source_id != "A9" for i in hub_person.identities)
    assert any(i.person.source_id == "A9" for p in people for i in p.identities)


def test_empty_shell_identities_are_dropped():
    shell = RawPerson("openlibrary", "OL1A", "Chinua Achebe", works_count=0)
    [person] = resolve_people("chinua achebe", [hub(), shell])
    assert all(i.person.source_id != "OL1A" for i in person.identities)


def test_grey_attaches_only_when_unambiguous():
    hub2 = hub(source_id="Q2", identifiers={}, birth_year=1990, death_year=None, affiliations=[])
    cand = oa("A5")
    people = resolve_people("chinua achebe", [hub(), hub2, cand])
    attached = [p for p in people if any(i.person.source_id == "A5" for i in p.identities)]
    # Two hubs are name-compatible, so the candidate stays on its own.
    assert len(attached) == 1 and attached[0].identities[0].person.source == "openalex"


def test_disambiguator_hook_can_confirm_grey():
    class Yes:
        def decide(self, hub, candidate, evidence):
            return Confidence.HIGH

    [person] = resolve_people("chinua achebe", [hub(), oa("A3")], disambiguator=Yes())
    ident = next(i for i in person.identities if i.person.source_id == "A3")
    assert ident.confidence == Confidence.HIGH
    assert "confirmed by disambiguator" in ident.evidence


def test_people_without_hub_cluster_across_sources():
    a = oa("A1", name="Ngozi Okafor", birth_year=1970, works_count=40)
    b = RawPerson("openlibrary", "OL5A", "Okafor, Ngozi", birth_year=1970, works_count=3)
    people = resolve_people("ngozi okafor", [a, b])
    assert len(people) == 1 and len(people[0].identities) == 2


def test_results_must_match_query():
    unrelated = oa("A7", name="Joachim von Braun")
    people = resolve_people("chinua achebe", [hub(), unrelated])
    assert [p.display_name for p in people] == ["Chinua Achebe"]


def test_wikidata_alias_merges_pen_name():
    h = hub(
        source_id="Q302910",
        name="Ngũgĩ wa Thiong'o",
        alt_names=["James Ngugi"],
        birth_year=1938,
        death_year=2025,
        identifiers={},
    )
    cand = RawPerson("openalex", "A1", "James Ngugi", works_count=10)
    [person] = resolve_people("ngugi wa thiong'o", [h, cand])
    ident = next(i for i in person.identities if i.person.source_id == "A1")
    assert ident.confidence == Confidence.HIGH
    assert "alias" in ident.evidence[0]


def test_alternatives_from_other_people_are_filtered():
    unrelated = Person("Joachim von Braun", [
        LinkedIdentity(
            oa("A1", name="Joachim von Braun", works_count=982),
            Confidence.GREY,
            ["no identity hub"],
        ),
    ])
    corporate = Person("VV.AA. - WOLE SOYINKA", [
        LinkedIdentity(
            oa("A2", name="VV.AA. - WOLE SOYINKA", works_count=1),
            Confidence.GREY,
            ["no identity hub"],
        ),
    ])
    assert not is_credible_alternative(unrelated, "Wole Soyinka", ["Wole Soyinka"])
    assert not is_credible_alternative(corporate, "Wole Soyinka", ["Wole Soyinka"])


# ---------------------------------------------------------------------- works
def w(source, sid, title, **kw) -> RawWork:
    return RawWork(source=source, source_id=sid, title=title, **kw)


def test_book_editions_merge_by_isbn_and_title_across_sources():
    recs = [
        w("openlibrary", "OL891786W", "Things Fall Apart", category=WorkCategory.BOOK,
          year=1958, isbns=["9780435905262"], edition_count=94),
        w("openalex", "W1", "Things fall apart", category=WorkCategory.BOOK, year=1994),
        w("openalex", "W2", "THINGS FALL APART: a novel", category=WorkCategory.BOOK, year=2009),
        w("openalex", "W3", "Arrow of God", category=WorkCategory.BOOK, year=1964),
    ]
    works = merge_works(recs)
    assert len(works) == 2
    tfa = next(x for x in works if x.title == "Things Fall Apart")
    assert tfa.year == 1958 and tfa.category == WorkCategory.BOOK
    assert tfa.sources == ["openalex", "openlibrary"] and tfa.edition_count == 94


def test_book_and_article_with_same_title_do_not_merge():
    recs = [
        w("openlibrary", "OL1", "The Trouble with Nigeria", category=WorkCategory.BOOK, year=1983),
        w("openalex", "W1", "The Trouble with Nigeria", year=1985),
    ]
    works = merge_works(recs)
    assert len(works) == 2
    book = next(x for x in works if x.category == WorkCategory.BOOK)
    assert book.title == "The Trouble with Nigeria"


def test_doi_merges_records_with_different_titles():
    recs = [
        w("openalex", "W1", "An Image of Africa", doi="10.1/x"),
        w("crossref", "C1", "An image of Africa: racism in Conrad", doi="10.1/x"),
    ]
    assert len(merge_works(recs)) == 1


def test_generic_titles_need_same_year_and_venue():
    recs = [
        w("openalex", "W1", "Introduction", year=1990, venue="Transition"),
        w("openalex", "W2", "Introduction", year=2001, venue="Callaloo"),
        w("openalex", "W3", "Introduction", year=1990, venue="Transition"),
    ]
    assert len(merge_works(recs)) == 2


def test_about_works_require_same_first_author():
    recs = [
        w("openalex", "W1", "Reading Achebe", relation=Relation.ABOUT, authors=["Simon Gikandi"]),
        w("openalex", "W2", "Reading Achebe", relation=Relation.ABOUT, authors=["Ada Ugah"]),
        w("openlibrary", "OL1", "Reading Achebe", relation=Relation.ABOUT, authors=["Simon Gikandi"]),
    ]
    assert len(merge_works(recs)) == 2


def test_best_access_link_prefers_open_access():
    from kora.models import AccessLink

    recs = [
        w("openlibrary", "OL1", "Home and Exile", category=WorkCategory.BOOK,
          links=[AccessLink("https://openlibrary.org/works/OL1", "library", "Open Library")]),
        w("openalex", "W1", "Home and Exile", category=WorkCategory.BOOK,
          links=[AccessLink("https://repo.example/pdf", "oa_pdf", "Free")]),
    ]
    [work] = merge_works(recs)
    assert work.links[0].kind == "oa_pdf"


def test_reviews_of_own_books_become_about():
    recs = [
        w("openlibrary", "OL1", "There Was a Country", category=WorkCategory.BOOK),
        w("openalex", "W1", "There was a country: a personal history of Biafra",
          category=WorkCategory.ARTICLE, raw_type="book-review"),
        w("openalex", "W2", "English and the African Writer", category=WorkCategory.ARTICLE,
          raw_type="article"),
    ]
    assert reclassify_reviews(recs) == 1
    assert recs[1].relation == Relation.ABOUT and recs[2].relation == Relation.BY


def test_posthumous_non_book_records_are_flagged():
    person = Person("Chinua Achebe", death_year=2013)
    recs = [
        w("openalex", "W1", "Updating DOI via the form", year=2026, category=WorkCategory.DATASET),
        w("openlibrary", "OL1", "Things Fall Apart", year=2020, category=WorkCategory.BOOK),
        w("openalex", "W2", "Arrow of God", year=2015, category=WorkCategory.ARTICLE),
        w("openalex", "W3", "A Future Book", year=2030, category=WorkCategory.BOOK),
    ]
    kept, flagged = flag_suspect_records(person, recs)
    assert [r.source_id for r in flagged] == ["W1", "W3"]
    assert [r.source_id for r in kept] == ["OL1", "W2"]


def test_longer_contributor_record_beats_single_author_record():
    recs = [
        w("openalex", "W1", "Theatre Matters", category=WorkCategory.BOOK,
          role=WorkRole.AUTHOR, authors=["Wole Soyinka"]),
        w("openlibrary", "OL1", "Theatre Matters", category=WorkCategory.BOOK,
          role=WorkRole.CONTRIBUTOR,
          authors=["Richard Boon", "Jane Plastow", "Wole Soyinka"]),
    ]
    [work] = merge_works(recs)
    assert work.role == WorkRole.CONTRIBUTOR


def test_primary_edition_supplies_authors_and_venue():
    recs = [
        w("openlibrary", "OL1", "Things Fall Apart", category=WorkCategory.BOOK,
          year=1958, authors=["Chinua Achebe"]),
        w("openlibrary", "OL2", "Things Fall Apart", category=WorkCategory.BOOK,
          year=1994, authors=["Chinua Achebe", "Peter Francis James"]),
        w("openalex", "W1", "Things Fall Apart", category=WorkCategory.BOOK,
          year=1994, authors=["Chinua Achebe", "Abiola Irele"], venue="Some Journal"),
    ]
    [work] = merge_works(recs)
    assert work.authors == ["Chinua Achebe"]
    assert work.venue is None


def test_review_is_reclassified_and_author_removed():
    recs = [
        w("openlibrary", "OL1", "The Trouble with Nigeria", category=WorkCategory.BOOK,
          year=1983, authors=["Chinua Achebe"]),
        w("openalex", "W1", "The Trouble with Nigeria", category=WorkCategory.ARTICLE,
          year=1985, authors=["Michael F. Thorpe", "Chinua Achebe"], raw_type="article"),
    ]
    assert reclassify_reviews(recs, "Chinua Achebe") == 1
    review = recs[1]
    assert review.relation == Relation.ABOUT
    assert review.authors == ["Michael F. Thorpe"]


def test_proceedings_about_person_are_reclassified():
    recs = [
        w("openalex", "W1",
          "Eagle on Iroko: Selected Papers from the Chinua Achebe International Symposium",
          category=WorkCategory.BOOK, authors=["Chinua Achebe", "Edith Ihekweazu"]),
    ]
    assert reclassify_reviews(recs, "Chinua Achebe") == 1
    assert recs[0].relation == Relation.ABOUT
    assert recs[0].authors == ["Edith Ihekweazu"]


def test_name_only_study_notes_and_reader_titles_are_about():
    recs = [
        w("openlibrary", "OL1", "Notes on Soyinka's Lion and the Jewel",
          category=WorkCategory.BOOK, authors=["Wole Soyinka"]),
        w("openlibrary", "OL2", "Soyinka", category=WorkCategory.BOOK,
          authors=["Wole Soyinka"]),
        w("openlibrary", "OL3", "The Essential Soyinka", category=WorkCategory.BOOK,
          authors=["Wole Soyinka"]),
        w("openlibrary", "OL4", "Soyinka as director", category=WorkCategory.BOOK,
          authors=["Wole Soyinka"]),
        w("openlibrary", "OL5", "Chinua Achebe Reading Things Fall Apart",
          category=WorkCategory.BOOK, authors=["Chinua Achebe"]),
    ]
    assert reclassify_reviews(recs, "Wole Soyinka") == 4
    assert all(r.relation == Relation.ABOUT for r in recs[:4])
    # A recording of the author reading his own work is still by the author.
    assert recs[4].relation == Relation.BY

    speaks = w("openlibrary", "OL6", "Ngũgĩ wa Thiong'o speaks",
               category=WorkCategory.BOOK, authors=["Ngũgĩ wa Thiong'o"])
    assert reclassify_reviews([speaks], "Ngũgĩ wa Thiong'o") == 1
    assert speaks.relation == Relation.ABOUT


def test_book_published_before_author_was_18_is_flagged():
    person = Person("Ngũgĩ wa Thiong'o", birth_year=1938)
    recs = [
        w("openlibrary", "OL1", "The relations between scientific research",
          category=WorkCategory.BOOK, year=1955),
    ]
    kept, flagged = flag_suspect_records(person, recs)
    assert not kept
    assert [r.source_id for r in flagged] == ["OL1"]


def test_impossible_pre_birth_year_is_repaired_not_dropped():
    person = Person("Wole Soyinka", birth_year=1934)
    recs = [
        w("openlibrary", "OL1", "The Strong Breed", category=WorkCategory.BOOK,
          year=1900),
    ]
    kept, flagged = flag_suspect_records(person, recs)
    assert not flagged
    assert [r.source_id for r in kept] == ["OL1"]
    assert kept[0].year is None


def test_low_signal_alternatives_are_filtered():
    weak = Person("Chinua Achebe ORLUOM", [
        LinkedIdentity(oa("A5005239460", name="Chinua Achebe ORLUOM", works_count=1),
                       Confidence.GREY, ["no identity hub"]),
    ])
    strong = Person("Chinua Achebe", [
        LinkedIdentity(oa("A1", works_count=10), Confidence.HIGH, ["name match"]),
    ])
    assert not is_credible_alternative(weak)
    assert is_credible_alternative(strong)


def test_title_overlap_promotes_grey_identity():
    confirmed = [
        w("openlibrary", "OL1", "Decolonising the Mind"),
        w("openlibrary", "OL2", "Petals of Blood"),
        w("openlibrary", "OL3", "Introduction"),
    ]
    ident = LinkedIdentity(oa("A1"), Confidence.GREY, ["name 100% similar"])
    shared = title_overlap(confirmed, ["Decolonising the mind: the politics", "Petals of blood", "Introduction"])
    assert shared == ["decolonising the mind", "petals of blood"]  # generic title ignored
    assert promote_by_title_overlap(ident, shared)
    assert ident.confidence == Confidence.HIGH

    lone = LinkedIdentity(oa("A2"), Confidence.GREY, [])
    assert not promote_by_title_overlap(lone, ["petals of blood"])
