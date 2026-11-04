"""Command-line prototype: `python -m kora "chinua achebe"`."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kora.aggregator import Aggregator, default_cache_dir
from kora.http import HttpClient
from kora.models import Confidence, Person, Profile, Relation, Work, WorkCategory, WorkRole
from kora.normalize import is_other_language

SECTIONS = [
    ("Books", Relation.BY, {WorkCategory.BOOK}, {WorkRole.AUTHOR}, "main"),
    ("Edited volumes", Relation.BY, {WorkCategory.BOOK}, {WorkRole.EDITOR}, "main"),
    ("Translations & other-language editions", Relation.BY, {WorkCategory.BOOK},
     {WorkRole.AUTHOR, WorkRole.EDITOR}, "other"),
    ("Included in anthologies", Relation.BY, {WorkCategory.BOOK}, {WorkRole.CONTRIBUTOR}, None),
    ("Articles, essays & chapters", Relation.BY, {WorkCategory.ARTICLE},
     {WorkRole.AUTHOR, WorkRole.EDITOR}, None),
    ("Theses", Relation.BY, {WorkCategory.THESIS}, {WorkRole.AUTHOR, WorkRole.EDITOR}, None),
    ("Datasets & other", Relation.BY, {WorkCategory.DATASET, WorkCategory.OTHER},
     {WorkRole.AUTHOR, WorkRole.EDITOR}, None),
    ("About them: criticism, reviews, theses", Relation.ABOUT, set(WorkCategory), set(WorkRole), None),
]
CONF_STYLE = {
    Confidence.HARD_ID: "green",
    Confidence.HIGH: "cyan",
    Confidence.GREY: "yellow",
    Confidence.CONFLICT: "red",
}


def _life(p: Person) -> str:
    if p.birth_year or p.death_year:
        return f" ({p.birth_year or '?'}-{p.death_year or ''})"
    return ""


def _is_other_language(w: Work) -> bool:
    return is_other_language(w.languages)


def render(profile: Profile, console: Console, limit: int) -> None:
    p = profile.person
    header = f"[bold]{p.display_name}[/bold]{_life(p)}"
    if p.description:
        header += f"\n[italic]{p.description}[/italic]"
    if profile.bio:
        bio = profile.bio if len(profile.bio) < 600 else profile.bio[:600] + "…"
        header += f"\n\n{bio}\n[dim]{profile.bio_url}[/dim]"
    console.print(Panel(header, title="Kora profile", expand=True))

    ids = Table(title="Merged identities (entity resolution)", show_lines=False)
    for col in ("Source", "ID", "Name", "Works", "Confidence", "Evidence"):
        ids.add_column(col)
    for ident in p.identities:
        rp = ident.person
        ids.add_row(
            rp.source, rp.source_id, rp.name, str(rp.works_count or ""),
            f"[{CONF_STYLE[ident.confidence]}]{ident.confidence}[/]",
            "; ".join(ident.evidence),
        )
    console.print(ids)

    by = [
        w for w in profile.works
        if w.relation == Relation.BY and w.role != WorkRole.CONTRIBUTOR
    ]
    contributed = [
        w for w in profile.works
        if w.relation == Relation.BY and w.role == WorkRole.CONTRIBUTOR
    ]
    about = [w for w in profile.works if w.relation == Relation.ABOUT]
    other_books = [
        w for w in by if w.category == WorkCategory.BOOK and _is_other_language(w)
    ]
    grey = [i for i in p.identities if i.confidence == Confidence.GREY]
    console.print(
        f"\n[bold]{profile.raw_work_count}[/bold] raw records → "
        f"[bold]{len(profile.works)}[/bold] unique works "
        f"([green]{len(by)} by/edited[/green], "
        f"[yellow]{len(contributed)} in anthologies[/yellow], "
        f"[magenta]{len(about)} about[/magenta])"
    )
    if other_books:
        console.print(
            f"[dim]{len(other_books)} other-language editions are listed separately.[/dim]"
        )
    if grey:
        console.print(
            f"[yellow]{len(grey)} grey-zone identit{'y' if len(grey) == 1 else 'ies'} shown above "
            "but not used for works (pending review)[/yellow]"
        )
    if profile.flagged:
        sample = "; ".join(f"{r.title[:40]} ({r.year})" for r in profile.flagged[:3])
        console.print(f"[yellow]{len(profile.flagged)} suspected misattributions flagged:[/yellow] {sample}")
    console.print()

    for title, relation, cats, roles, lang_group in SECTIONS:
        items = [
            w for w in profile.works
            if w.relation == relation and w.category in cats and w.role in roles
        ]
        if lang_group == "main":
            items = [w for w in items if not _is_other_language(w)]
        elif lang_group == "other":
            items = [w for w in items if _is_other_language(w)]
        if not items:
            continue
        t = Table(title=f"{title} ({len(items)})", title_justify="left", expand=True)
        t.add_column("Year", width=5)
        t.add_column("Title", ratio=4)
        t.add_column("Venue / authors", ratio=2)
        t.add_column("Eds/Cites", width=9)
        t.add_column("Sources", ratio=1)
        t.add_column("Best access", ratio=3)
        for w in items[:limit]:
            t.add_row(
                str(w.year or ""),
                w.title,
                _venue(w, relation),
                f"{w.edition_count}e/{w.cited_by}c",
                ",".join(s.replace("openlibrary", "OL").replace("openalex", "OA") for s in w.sources),
                f"{w.links[0].label}: {w.links[0].url}" if w.links else "",
            )
        if len(items) > limit:
            t.caption = f"… {len(items) - limit} more (use --limit or --json)"
        console.print(t)

    if profile.alternatives:
        console.print("\n[bold]Did you mean[/bold] (use --pick N):")
        for i, alt in enumerate(profile.alternatives, start=1):
            srcs = ",".join(alt.sources)
            console.print(f"  {i}. {alt.display_name}{_life(alt)}: {alt.description or ''} [dim]({srcs})[/dim]")

    st = Table(title="Source status", title_justify="left")
    st.add_column("Call")
    st.add_column("Result")
    for k, v in profile.source_status.items():
        st.add_row(k, v if v.startswith("ok") else f"[red]{v}[/red]")
    console.print(st)


def _venue(w: Work, relation: Relation) -> str:
    if (relation == Relation.ABOUT or w.role == WorkRole.CONTRIBUTOR) and w.authors:
        base = ", ".join(w.authors[:3]) + (f" in {w.venue}" if w.venue else "")
    else:
        base = w.venue or ""
    if _is_other_language(w):
        langs = ",".join(sorted({lang for lang in w.languages if lang and lang != "und"}))
        base = f"{base} [{langs}]" if base else f"[{langs}]"
    return base


def render_audit(profile: Profile, console: Console) -> None:
    """Developer view: where works come from and how they were classified."""
    t = Table(title="Audit: unique works", title_justify="left")
    for col in ("Relation", "Category", "Role", "Works"):
        t.add_column(col)
    counts = Counter(
        (w.relation.value, w.category.value, w.role.value) for w in profile.works
    )
    for (relation, category, role), n in counts.most_common():
        t.add_row(relation, category, role, str(n))
    console.print(t)

    src = Counter(r.source for w in profile.works for r in w.records)
    console.print("[bold]Records by source:[/bold] " + ", ".join(
        f"{name}={n}" for name, n in src.most_common()
    ))
    if profile.flagged:
        console.print(
            "[bold]Flagged:[/bold] "
            + "; ".join(f"{r.title[:50]} ({r.year})" for r in profile.flagged[:10])
        )


def to_json(profile: Profile) -> str:
    return json.dumps(dataclasses.asdict(profile), indent=2, ensure_ascii=False, default=str)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kora", description="Aggregate everything by and about a person.")
    ap.add_argument("query", help='person name, e.g. "Chinua Achebe"')
    ap.add_argument("--pick", type=int, default=0, help="choose the Nth 'did you mean' person (0 = best)")
    ap.add_argument("--limit", type=int, default=15, help="rows per section")
    ap.add_argument("--json", type=Path, help="write full merged profile as JSON")
    ap.add_argument("--no-about", action="store_true", help="skip works *about* the person")
    ap.add_argument("--no-cache", action="store_true", help="bypass the on-disk HTTP cache")
    ap.add_argument("--audit", action="store_true", help="show role/source counts and flagged records")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    console = Console()

    async def run() -> Profile | None:
        cache = None if args.no_cache else default_cache_dir()
        async with HttpClient(cache_dir=cache) as http:
            agg = Aggregator(http)
            with console.status(f"Searching sources for '{args.query}'…"):
                return await agg.build_profile(args.query, pick=args.pick, include_about=not args.no_about)

    profile = asyncio.run(run())
    if profile is None:
        console.print(f"[red]No person found for '{args.query}'.[/red]")
        return 1
    render(profile, console, args.limit)
    if args.audit:
        render_audit(profile, console)
    if args.json:
        args.json.write_text(to_json(profile), encoding="utf-8")
        console.print(f"\nFull JSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
