"""Normalisation helpers for names, titles and identifiers.

African names often carry diacritics (Yoruba Ṣóyínká, Igbo Ọ̀kọ̀nkwọ), honorifics
(Prof., Chief, Alhaji) and inconsistent name order ("ACHEBE, Chinua"). Matching
works on folded forms while display keeps the originals.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

HONORIFICS = {
    "prof", "professor", "dr", "doctor", "mr", "mrs", "ms", "miss", "sir", "dame",
    "chief", "alhaji", "alhaja", "hajia", "mallam", "malam", "oba", "baba", "mama",
    "rev", "reverend", "pastor", "engr", "arc", "barr", "hon", "senator", "jr", "sr",
}

# Titles too generic to merge on title alone (need year/venue agreement too).
GENERIC_TITLES = {
    "introduction", "preface", "foreword", "afterword", "editorial", "review",
    "book review", "interview", "an interview", "untitled", "index", "contents",
    "notes", "acknowledgements", "acknowledgments", "conclusion", "epilogue",
    "prologue", "letter", "comment", "response", "reply", "poems", "selected poems",
    "short stories", "essays", "collected poems", "stories", "literature", "fiction",
    "poetry", "anthology", "the anthology", "reader", "the reader",
}

_LEADING_ARTICLES = re.compile(r"^(the|a|an|le|la|les|l'|el|der|die|das)\s+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
# The trailing group is optional so open-ended library dates ("1934-") work too.
_YEAR_RANGE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\s*[-–—]\s*(?:(1[5-9]\d\d|20\d\d))?")
_TITLE_SPLIT = re.compile(r"\s*[:;]\s+|\s+[-–—]\s+|\s*--\s*|\s*\(")
# A comma followed by a subtitle opener ("Aké, les années d'enfance") is a
# subtitle, not a list of separate works ("Things Fall Apart, No Longer at
# Ease") or a title comma ("Beware, soul-brother"). This keeps omnibus volumes
# from being conflated with the single novel they contain.
_COMMA_SUBTITLE = re.compile(
    r",\s+(?=(?:a|an|the|le|la|les|l'|un|une|des|du|el|los|las|il|lo|gli|"
    r"os|as|um|uma|der|die|das|ein|eine|of|in|on|for|with|from|to|at|by|"
    r"dans|sur|pour|avec|de|en|au|aux|im|mit|von|zu|con|por|para|del|"
    r"della|nel|com|em|do|da)\b)",
    re.IGNORECASE,
)
# Markers that make a record a derivative work (study guide, review companion)
# rather than another edition of the primary work.
_DERIVATIVE_RE = re.compile(
    r"\b(notes?|study guide|cliffs ?notes|spark ?notes|companion|reader'?s guide|summary|analysis|workbook)\b",
    re.IGNORECASE,
)
_DERIVATIVE_LEAD_RE = re.compile(
    r"^\s*(notes on|study guide|a study guide|cliffsnotes|sparknotes|companion to|"
    r"reader'?s guide to|summary of|analysis of)\b",
    re.IGNORECASE,
)
_ANTHOLOGY_RE = re.compile(
    r"\b(literature|anthology|reader|prentice hall|glencoe|elements of|world masterpieces|"
    r"portable|collection|selected (?:stories|poems|papers)|short stories|poems|stories|"
    r"fiction|voices|proceedings|issue)\b",
    re.IGNORECASE,
)
# Stronger markers for a volume *edited* by the person even when they are the
# only listed author (e.g. Soyinka's "Poems of Black Africa").
_EDITED_ANTHOLOGY_RE = re.compile(
    r"(^poems of\b|^a book of\b|^the book of\b|\banthology\b|\breader\b|"
    r"prentice hall|glencoe|elements of literature|world masterpieces|"
    r"selected papers|proceedings|short stories|voices of|"
    r"literature--|literature:|african theatre)",
    re.IGNORECASE,
)
_EDITION_SUFFIX_RE = re.compile(
    r"\s+(?:with connections|with related readings.*|the expanded edition.*|"
    r"expanded edition.*)\s*$|\.\s*(?:a novel|novel|roman)\.?\s*$",
    re.IGNORECASE,
)
_COLLECTION_SUFFIX_RE = re.compile(
    r",?\s+(?:and|&)\s+other\s+(?:poems|stories|essays)\b.*$",
    re.IGNORECASE,
)
_JUNK_TITLE_RE = re.compile(
    r"\b(paperback|hardcover|library binding|mass market|audio cd|audiobook)\b",
    re.IGNORECASE,
)
_EXCERPT_TITLE_RE = re.compile(r"^\s*excerpts? from\b", re.IGNORECASE)
_COLLECTIVE_AUTHOR_RE = re.compile(
    r"\b(collective|committee|association|society|organization|organisation|"
    r"institute|editors|various|anonymous|team)\b",
    re.IGNORECASE,
)

# Open Library uses MARC three-letter codes, OpenAlex uses ISO 639-1. Normalise
# both to ISO 639-1 so the CLI can separate translations consistently.
LANGUAGE_ALIASES = {
    "en": "en", "eng": "en", "fr": "fr", "fre": "fr", "de": "de", "ger": "de",
    "nl": "nl", "dut": "nl", "es": "es", "spa": "es", "it": "it", "ita": "it",
    "pt": "pt", "por": "pt", "ja": "ja", "jpn": "ja", "zh": "zh", "chi": "zh",
    "ru": "ru", "rus": "ru", "tr": "tr", "tur": "tr", "ca": "ca", "cat": "ca",
    "eu": "eu", "baq": "eu", "ki": "ki", "kik": "ki", "ig": "ig", "ibo": "ig",
    "yo": "yo", "yor": "yo", "sw": "sw", "swa": "sw", "pl": "pl", "pol": "pl",
    "he": "he", "heb": "he", "ar": "ar", "ara": "ar", "hi": "hi", "hin": "hi",
    "bn": "bn", "ben": "bn", "am": "am", "amh": "am", "so": "so", "som": "so",
    "zu": "zu", "zul": "zu", "xh": "xh", "xho": "xh", "af": "af", "afr": "af",
    "sv": "sv", "swe": "sv", "no": "no", "nor": "no", "da": "da", "dan": "da",
    "fi": "fi", "fin": "fi", "el": "el", "gre": "el", "la": "la", "lat": "la",
    "und": "und",
}


def fold(text: str) -> str:
    """Lower-case, strip diacritics (Ṣóyínká -> soyinka), collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def name_tokens(name: str) -> list[str]:
    """Folded name tokens without honorifics, punctuation or year ranges."""
    name = _YEAR_RANGE.sub(" ", name)
    tokens = _NON_ALNUM.sub(" ", fold(name)).split()
    return [t for t in tokens if t not in HONORIFICS and not t.isdigit()]


def name_key(name: str) -> str:
    """Order-insensitive key: 'Achebe, Chinua' == 'Chinua Achebe'."""
    return " ".join(sorted(name_tokens(name)))


def name_similarity(a: str, b: str) -> float:
    """0-100 similarity tolerant to order, initials and honorifics."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    score = fuzz.token_sort_ratio(" ".join(ta), " ".join(tb))
    # Initials: "C. Achebe" vs "Chinua Achebe" -> same surname, compatible initial.
    if score < 90 and _initials_compatible(ta, tb):
        score = max(score, 88.0)
    return float(score)


def _initials_compatible(ta: list[str], tb: list[str]) -> bool:
    short, long_ = (ta, tb) if len("".join(ta)) <= len("".join(tb)) else (tb, ta)
    long_set = set(long_)
    full = [t for t in short if len(t) > 1]
    initials = [t for t in short if len(t) == 1]
    if not full or not initials or not all(t in long_set for t in full):
        return False
    remaining = [t for t in long_ if t not in full]
    return all(any(r.startswith(i) for r in remaining) for i in initials)


def best_name_similarity(names_a: list[str], names_b: list[str]) -> float:
    return max((name_similarity(a, b) for a in names_a for b in names_b), default=0.0)


def years_in_names(names: list[str]) -> tuple[int | None, int | None]:
    """Extract (birth, death) from library-style names like 'Achebe, Chinua 1930-2013'."""
    for n in names:
        m = _YEAR_RANGE.search(n)
        if m:
            return int(m.group(1)), int(m.group(2)) if m.group(2) else None
    return None, None


def title_parts(title: str) -> tuple[str, str]:
    """Return (base title, subtitle) with diacritics folded.

    Subtitles are useful for distinguishing an edition ("A Novel") from a
    derivative work ("Notes", "A Study Guide").
    """
    raw = title
    comma = _COMMA_SUBTITLE.search(raw)
    if comma:
        raw = raw[: comma.start()]
    cleaned = _EDITION_SUFFIX_RE.sub("", fold(raw))
    cleaned = _COLLECTION_SUFFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"\s*&\s*", " and ", cleaned)
    parts = _TITLE_SPLIT.split(cleaned, maxsplit=1)
    base = parts[0].strip()
    subtitle = parts[1].strip(" )") if len(parts) > 1 else ""
    return base, subtitle


def title_key(title: str) -> str:
    """Normalised title for dedup: folded, no subtitle, no leading article/punctuation."""
    base, _ = title_parts(title)
    base = _LEADING_ARTICLES.sub("", base)
    return _NON_ALNUM.sub(" ", base).strip()


def is_derivative_title(title: str) -> bool:
    """True for study guides/companions, which must not merge with the primary work."""
    _, subtitle = title_parts(title)
    if subtitle and _DERIVATIVE_RE.search(subtitle):
        return True
    return bool(_DERIVATIVE_LEAD_RE.search(title))


def is_anthology_title(title: str) -> bool:
    """Heuristic for anthologies/readers/textbooks with many contributors."""
    return bool(_ANTHOLOGY_RE.search(title))


def is_edited_anthology_title(title: str) -> bool:
    """Stronger signal that the named person is the volume's editor, not author."""
    return bool(_EDITED_ANTHOLOGY_RE.search(title))


def is_junk_title(title: str) -> bool:
    """Catch vendor/format debris and excerpt-only records."""
    if _EXCERPT_TITLE_RE.search(title):
        return True
    return bool(_JUNK_TITLE_RE.search(title)) and " by " in title.lower()


def is_collective_author(name: str) -> bool:
    """True for corporate/collective bylines such as 'Collective Antigone'.

    When a person is listed after such a byline, they usually wrote a preface or
    introduction rather than the whole book.
    """
    return bool(_COLLECTIVE_AUTHOR_RE.search(fold(name)))


def strip_trailing_author(title: str, authors: list[str]) -> str:
    """Drop a source's redundant trailing author credit.

    OpenAlex sometimes emits titles such as "Things Fall Apart, Chinua Achebe";
    the author is already a separate field, so the title should match the book.
    """
    out = title.strip().rstrip(" .")
    for author in authors:
        name = author.strip()
        if len(name.split()) < 2:
            continue
        for pattern in (f", {name}", f" by {name}", f" - {name}", f" – {name}", f" ({name})"):
            if out.lower().endswith(pattern.lower()):
                trimmed = out[: -len(pattern)].rstrip(" .,;:-–—")
                if trimmed:
                    return trimmed
    return out


def is_generic_title(key: str) -> bool:
    # Three-letter titles such as "Aké" are distinctive; only two-letter
    # fragments and the explicit list need year/venue corroboration.
    return key in GENERIC_TITLES or len(key) < 3


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    code = fold(value)
    return LANGUAGE_ALIASES.get(code, code)


def is_other_language(languages: list[str]) -> bool:
    """True when a work has known languages but none of them is English."""
    langs = {lang for lang in languages if lang and lang != "und"}
    return bool(langs) and "en" not in langs


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)
    d = d.removeprefix("doi:")
    return d or None


def normalize_isbn(isbn: str) -> str | None:
    """Return ISBN-13 digits, converting ISBN-10. None if invalid."""
    s = re.sub(r"[^0-9Xx]", "", isbn).upper()
    if len(s) == 10:
        if not _isbn10_valid(s):
            return None
        core = "978" + s[:9]
        return core + _isbn13_check(core)
    if len(s) == 13 and s.isdigit():
        if not s.startswith(("978", "979")):
            return None
        return s if _isbn13_check(s[:12]) == s[12] else None
    return None


def _isbn10_valid(s: str) -> bool:
    total = 0
    for i, ch in enumerate(s):
        if ch == "X":
            if i != 9:
                return False
            v = 10
        elif ch.isdigit():
            v = int(ch)
        else:
            return False
        total += v * (10 - i)
    return total % 11 == 0


def _isbn13_check(core12: str) -> str:
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core12))
    return str((10 - total % 10) % 10)
