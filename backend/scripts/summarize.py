"""Debug helper: summarise a profile JSON written by `python -m kora ... --json f.json`."""

import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
d = json.load(open(sys.argv[1], encoding="utf-8"))
p = d["person"]
print(f"{p['display_name']} ({p['birth_year']}-{p['death_year']})")
for i in p["identities"]:
    rp = i["person"]
    print(f"  {rp['source']:11} {rp['source_id']:13} works={rp['works_count']} {i['confidence']:8} {'; '.join(i['evidence'])[:110]}")
works = d["works"]
print(f"raw={d['raw_work_count']} works={len(works)} flagged={len(d['flagged'])}")
print("  ", Counter(f"{w['relation']}/{w['category']}" for w in works))
print("  multi-source works:", sum(1 for w in works if len({r['source'] for r in w['records']}) > 1))
for k, v in d["source_status"].items():
    if not v.startswith("ok"):
        print("  !", k, v)
