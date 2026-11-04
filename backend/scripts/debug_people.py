"""Debug helper: print resolved person clusters for a query (no works fetch)."""

import asyncio
import sys

from kora.aggregator import Aggregator, default_cache_dir
from kora.http import HttpClient


async def main(q: str) -> None:
    async with HttpClient(cache_dir=default_cache_dir()) as http:
        agg = Aggregator(http)
        people = await agg.find_people(q)
        print(agg.status)
        for i, p in enumerate(people):
            print(f"[{i}] {p.display_name} ({p.birth_year}-{p.death_year}) {p.description or ''}")
            for ident in p.identities:
                rp = ident.person
                print(
                    f"     {rp.source:11} {rp.source_id:14} {rp.name[:35]:35} works={rp.works_count} "
                    f"{ident.confidence:9} {'; '.join(ident.evidence)[:90]}"
                )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main(" ".join(sys.argv[1:])))
