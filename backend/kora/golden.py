"""Golden-profile checks for entity resolution and bibliography quality.

The fixture is deliberately semantic rather than snapshot-based: it asserts a
handful of must-have works, roles, provenance and broad count ranges. That way
normal source drift does not fail the build, but a regression in deduplication,
role inference or "about" detection does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kora.models import Profile, Relation, Work, WorkCategory, WorkRole
from kora.normalize import fold, is_other_language, name_key, title_key


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("authors"), list):
        raise ValueError(f"{path}: expected an object with an 'authors' list")
    return data


def _match_key(title: str) -> str:
    # title_key ignores non-Latin scripts; keep a folded fallback for those.
    return title_key(title) or fold(title)


def _books(profile: Profile, role: WorkRole) -> list[Work]:
    return [
        w for w in profile.works
        if w.relation == Relation.BY and w.category == WorkCategory.BOOK and w.role == role
    ]


def _about(profile: Profile) -> list[Work]:
    return [w for w in profile.works if w.relation == Relation.ABOUT]


def profile_stats(profile: Profile) -> dict[str, int]:
    authored = _books(profile, WorkRole.AUTHOR)
    edited = _books(profile, WorkRole.EDITOR)
    contributed = _books(profile, WorkRole.CONTRIBUTOR)
    return {
        "raw_works": profile.raw_work_count,
        "works": len(profile.works),
        "authored_all": len(authored),
        "authored_main": sum(not is_other_language(w.languages) for w in authored),
        "authored_other": sum(is_other_language(w.languages) for w in authored),
        "edited_all": len(edited),
        "edited_main": sum(not is_other_language(w.languages) for w in edited),
        "contributor": len(contributed),
        "about": len(_about(profile)),
        "other_language": sum(
            is_other_language(w.languages) for w in authored + edited
        ),
        "flagged": len(profile.flagged),
        "alternatives": len(profile.alternatives),
    }


def check_profile(spec: dict[str, Any], profile: Profile) -> tuple[list[str], dict[str, int]]:
    """Return (failures, stats) for one golden author specification."""
    failures: list[str] = []
    authored = _books(profile, WorkRole.AUTHOR)
    edited = _books(profile, WorkRole.EDITOR)
    contributed = _books(profile, WorkRole.CONTRIBUTOR)
    about = _about(profile)

    authored_keys = {_match_key(w.title) for w in authored}
    edited_keys = {_match_key(w.title) for w in edited}
    contributed_keys = {_match_key(w.title) for w in contributed}
    about_keys = {_match_key(w.title) for w in about}

    expected_name = spec.get("display_name")
    if expected_name and name_key(profile.person.display_name) != name_key(expected_name):
        failures.append(
            f"display name: expected {expected_name!r}, got {profile.person.display_name!r}"
        )
    for field in ("birth_year", "death_year"):
        if field in spec and getattr(profile.person, field) != spec[field]:
            failures.append(
                f"{field}: expected {spec[field]!r}, got {getattr(profile.person, field)!r}"
            )

    required_sources = set(spec.get("required_sources") or [])
    missing_sources = sorted(required_sources - set(profile.person.sources))
    if missing_sources:
        failures.append(f"missing identity sources: {', '.join(missing_sources)}")

    for label, keys, wanted in (
        ("authored book", authored_keys, spec.get("must_have_authored") or []),
        ("edited book", edited_keys, spec.get("must_have_edited") or []),
        ("contributor book", contributed_keys, spec.get("must_have_contributor") or []),
        ("about work", about_keys, spec.get("must_be_about") or []),
    ):
        for title in wanted:
            if _match_key(title) not in keys:
                failures.append(f"missing {label}: {title!r}")

    for title in spec.get("must_not_be_authored") or []:
        if _match_key(title) in authored_keys:
            failures.append(f"wrongly authored: {title!r}")

    stats = profile_stats(profile)
    for key, expected in (spec.get("counts") or {}).items():
        if key.endswith("_min"):
            stat = key[:-4]
            if stat not in stats:
                failures.append(f"unknown count field: {key!r}")
            elif stats[stat] < expected:
                failures.append(f"{stat}: {stats[stat]} < minimum {expected}")
        elif key.endswith("_max"):
            stat = key[:-4]
            if stat not in stats:
                failures.append(f"unknown count field: {key!r}")
            elif stats[stat] > expected:
                failures.append(f"{stat}: {stats[stat]} > maximum {expected}")
        else:
            failures.append(f"count key must end in _min or _max: {key!r}")

    alt_keys = {name_key(a.display_name) for a in profile.alternatives}
    for name in spec.get("must_include_alternatives") or []:
        if name_key(name) not in alt_keys:
            failures.append(f"missing alternative identity: {name!r}")
    for name in spec.get("forbidden_alternatives") or []:
        if name_key(name) in alt_keys:
            failures.append(f"forbidden alternative identity: {name!r}")

    for label, status in profile.source_status.items():
        if status.startswith("failed:"):
            failures.append(f"source {label}: {status}")

    return failures, stats
