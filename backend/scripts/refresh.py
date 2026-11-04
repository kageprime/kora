"""Refresh stored scholar profiles from live sources.

Example:
    python scripts/refresh.py --limit 25 --stale-hours 168
    python scripts/refresh.py --only 1 --only 4
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from kora.aggregator import Aggregator
from kora.http import HttpClient
from kora.refresh import RefreshResult, refresh_scholars
from kora.storage.database import (
    Settings,
    build_engine,
    build_session_factory,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=25, help="maximum scholars to refresh"
    )
    parser.add_argument(
        "--stale-hours",
        type=int,
        default=None,
        help="only refresh scholars not attempted in this many hours",
    )
    parser.add_argument(
        "--only",
        type=int,
        action="append",
        default=None,
        help="refresh a specific scholar id (repeatable)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="bypass the on-disk HTTP cache",
    )
    return parser.parse_args()


def print_result(result: RefreshResult) -> None:
    if result.ok:
        print(f"ok\t{result.scholar_id}\t{result.display_name}\t{result.work_count} works")
    else:
        print(f"failed\t{result.scholar_id}\t{result.display_name}\t{result.error}")


async def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    cache_dir = None if args.no_cache else settings.cache_dir
    http = HttpClient(cache_dir=cache_dir)
    aggregator = Aggregator(http)
    try:
        results = await refresh_scholars(
            factory,
            aggregator,
            limit=args.limit,
            stale_hours=args.stale_hours,
            scholar_ids=args.only,
        )
    finally:
        await http.close()
        await engine.dispose()

    for result in results:
        print_result(result)
    failed = sum(1 for result in results if not result.ok)
    print(f"\n{len(results) - failed} refreshed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
