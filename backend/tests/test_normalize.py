from kora.normalize import (
    best_name_similarity,
    fold,
    is_anthology_title,
    is_derivative_title,
    is_edited_anthology_title,
    is_generic_title,
    is_junk_title,
    name_key,
    name_similarity,
    normalize_doi,
    normalize_isbn,
    normalize_language,
    strip_trailing_author,
    title_key,
    years_in_names,
)


def test_fold_strips_african_diacritics():
    assert fold("Ṣóyínká") == "soyinka"
    assert fold("Ngũgĩ  wa Thiong'o") == "ngugi wa thiong'o"
    assert fold("Ọ̀kọ̀nkwọ") == "okonkwo"


def test_name_key_is_order_and_honorific_insensitive():
    assert name_key("Achebe, Chinua") == name_key("Chinua Achebe")
    assert name_key("Prof. Chief Wole Soyinka") == name_key("Soyinka, Wole")
    assert name_key("Achebe, Chinua 1930-2013") == name_key("chinua achebe")


def test_name_similarity_handles_initials_and_variants():
    assert name_similarity("C. Achebe", "Chinua Achebe") >= 88
    assert name_similarity("Ngugi wa Thiongo", "Ngũgĩ wa Thiong’o") >= 90
    assert name_similarity("Chinua Achebe", "Wole Soyinka") < 50
    assert name_similarity("K. Achebe", "Chinua Achebe") < 88
    assert best_name_similarity(["X Y", "Achebe, Chinua"], ["Chinua Achebe"]) == 100


def test_years_in_library_names():
    assert years_in_names(["Achebe, Chinua", "Achebe, Chinua 1930-2013"]) == (1930, 2013)
    assert years_in_names(["Soyinka, Wole, 1934-"]) == (1934, None)
    assert years_in_names(["No Dates"]) == (None, None)


def test_title_key_drops_subtitles_articles_and_punctuation():
    assert title_key("Things Fall Apart") == title_key("THINGS FALL APART: A Novel")
    assert title_key("The Trouble with Nigeria") == "trouble with nigeria"
    assert title_key("An Image of Africa (Penguin Great Ideas)") == "image of africa"
    assert is_generic_title(title_key("Introduction"))
    assert not is_generic_title(title_key("Arrow of God"))
    assert not is_generic_title(title_key("Aké"))


def test_comma_subtitles_merge_but_omnibus_titles_do_not():
    assert title_key("Aké, les années d'enfance") == title_key("Aké")
    assert title_key("Isara, a voyage around Essay") == title_key("Isara")
    assert title_key("Burden of Memory, the Muse of Forgiveness") == "burden of memory"
    assert title_key("Things Fall Apart, No Longer at Ease") != title_key("Things Fall Apart")
    assert title_key("Art, Dialogue and Outrage") != title_key("Art")


def test_isbn_normalisation():
    assert normalize_isbn("0-435-90526-0") == "9780435905262"
    assert normalize_isbn("9780435905262") == "9780435905262"
    assert normalize_isbn("0435905261") is None  # bad check digit
    assert normalize_isbn("8936024911577") is None  # bad ISBN-13 check digit


def test_edition_and_collection_suffixes_are_ignored():
    assert title_key("Things Fall Apart with Connections") == title_key("Things Fall Apart")
    assert title_key("Things Fall Apart with related readings") == title_key("Things Fall Apart")
    assert title_key("Beware, soul-brother, and other poems") == title_key("Beware Soul Brother")
    assert title_key("Girls at War and Other Stories") == title_key("Girls at War")
    assert title_key("Termitenhügel in der Savanne. Roman.") == title_key(
        "Termitenhügel in der Savanne"
    )


def test_derivative_anthology_and_junk_titles():
    assert is_derivative_title("Things Fall Apart: Notes")
    assert is_derivative_title("A Study Guide to Things Fall Apart")
    assert not is_derivative_title("Things Fall Apart: A Novel")
    assert is_anthology_title("Prentice Hall Literature")
    assert is_anthology_title("African Short Stories")
    assert is_edited_anthology_title("Poems of Black Africa")
    assert is_edited_anthology_title("African Theatre")
    assert not is_edited_anthology_title("Collected Poems")
    assert is_junk_title("Things Fall Apart by Steiner, Rudolf, Achebe, Chinua Paperback")
    assert is_junk_title('EXCERPTS FROM "DEATH AND THE KING\'S HORSEMAN"')
    assert not is_junk_title("Things Fall Apart")


def test_language_normalisation():
    assert normalize_language("eng") == "en"
    assert normalize_language("en") == "en"
    assert normalize_language("fre") == "fr"
    assert normalize_language("ger") == "de"
    assert normalize_language("kik") == "ki"
    assert normalize_language(None) is None


def test_strip_trailing_author():
    assert strip_trailing_author("Things Fall Apart, Chinua Achebe", ["Chinua Achebe"]) == (
        "Things Fall Apart"
    )
    assert strip_trailing_author("Things Fall Apart by Chinua Achebe", ["Chinua Achebe"]) == (
        "Things Fall Apart"
    )
    assert strip_trailing_author("Things Fall Apart", ["Chinua Achebe"]) == "Things Fall Apart"


def test_doi_normalisation():
    assert normalize_doi("https://doi.org/10.2307/483838") == "10.2307/483838"
    assert normalize_doi("doi:10.1353/MAR.2016.0003") == "10.1353/mar.2016.0003"
    assert normalize_doi(None) is None
