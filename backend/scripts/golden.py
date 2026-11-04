"""Run the golden-profile regression checks.

Usage:
    python scripts/golden.py
    python scripts/golden.py --no-cache
    python scripts/golden.py --dump-dir .out/golden

The checks assert semantic qualities (must-have works, roles, provenance and
broad count ranges), not exact snapshots. They are meant for a warm cache or a
network connection; source failures are reported as failures.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path

from kora.aggregator import Aggregator, default_cache_dir
from kora.golden import check_profile, load_fixture
from kora.http import HttpClient

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "golden" / "authors.json"


def _print_stats(label: str, stats: dict[str, int]) -> None:
    print(
        f"{label}: raw={stats['raw_works']} works={stats['works']} "
        f"authored={stats['authored_all']} (main={stats['authored_main']}, "
        f"other={stats['authored_other']}) edited={stats['edited_all']} "
        f"contributor={stats['contributor']} about={stats['about']} "
        f"flagged={stats['flagged']} alternatives={stats['alternatives']}"
    )


async def run(args: argparse.Namespace) -> int:
    fixture = load_fixture(args.fixture)
    specs = fixture["authors"]
    if args.only:
        wanted = {name.casefold() for name in args.only}
        specs = [
            spec for spec in specs
            if spec["query"].casefold() in wanted
            or (spec.get("display_name") or "").casefold() in wanted
        ]
        if not specs:
            print(f"No fixture author matched: {', '.join(args.only)}", file=sys.stderr)
            return 2

    if args.dump_dir:
        args.dump_dir.mkdir(parents=True, exist_ok=True)

    failed = 0
    async with HttpClient(cache_dir=None if args.no_cache else default_cache_dir()) as http:
        for spec in specs:
            query = spec["query"]
            profile = await Aggregator(http).build_profile(query)
            if profile is None:
                print(f"[FAIL] {query}: no person found")
                failed += 1
                continue
            failures, stats = check_profile(spec, profile)
            marker = "PASS" if not failures else "FAIL"
            print(f"[{marker}] {query}")
            _print_stats("       ", stats)
            for failure in failures:
                print(f"       - {failure}")
            if failures:
                failed += 1
            if args.dump_dir:
                slug = query.casefold().replace(" ", "_").replace("'", "")
                out = args.dump_dir / f"{slug}.json"
                out.write_text(
                    json.dumps(
                        dataclasses.asdict(profile), indent=2, ensure_ascii=False, default=str
                    ),
                    encoding="utf-8",
                )

    total = len(specs)
    print(f"\n{total - failed}/{total} profiles passed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fixture", type=Path, default=FIXTURE, help=f"golden fixture (default: {FIXTURE})"
    )
    ap.add_argument("--no-cache", action="store_true", help="bypass the on-disk HTTP cache")
    ap.add_argument("--only", nargs="+", help="run only these query/display names")
    ap.add_argument("--dump-dir", type=Path, help="write each full profile as JSON here")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
