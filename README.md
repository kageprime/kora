# Kora

**An Africa-first academic aggregator: everything by and about a scholar, with provenance and legal access links.**

Kora is being built from the researcher's side outward. Given a person's name, it resolves their identity across open scholarly and bibliographic sources, merges duplicate records into works, separates books from articles, anthologies and works *about* them, and points to open-access, publisher, library or preview copies. It never hosts copyrighted full text.

This repository contains the **hardened Phase 0.5 resolution engine** plus **Phase 1A**: a FastAPI service with an Alembic-managed Postgres schema, durable review queues, a conservative refresh job, CI against Postgres, and Docker Compose for the API and database.

## What works today

- Identity resolution across **Wikidata**, **OpenAlex** and **Open Library**, with hard identifiers, aliases, date/affiliation evidence and visible grey-zone matches.
- FRBR-lite work merging by DOI, ISBN and conservative title matching.
- Role separation: authored books, edited volumes, contributions to anthologies/textbooks, articles, theses, datasets/other, translations, and works about the person.
- Precision-first "about" detection (biographies, criticism, interviews, study guides) using titles, subjects and source metadata.
- Misattribution flags for pre-birth, posthumous, future-dated and junk records.
- Access links only: OA PDF, publisher DOI, Internet Archive borrow/full text where legally available, Open Library record, OpenAlex record.
- UTF-8-safe names and diacritics (`Ngũgĩ wa Thiong'o`, `Aké`, Yoruba names).
- On-disk HTTP cache, source-level failure isolation and JSON output.
- **FastAPI + Postgres persistence**: live resolution, canonical scholar/identity/work/record/link tables, stored-profile retrieval and scholar listing.
- **Alembic migrations** as the source of schema truth, with automatic `create_all` disabled by default.
- **Durable review queues** for grey identities and flagged records. Decisions survive refreshes, and stale pending items are marked `superseded` instead of deleted.
- **Conservative refresh job** that re-resolves stored scholars, records failures, and refuses to overwrite a profile if the top identity changed.
- Docker Compose for Postgres and the API, plus GitHub Actions coverage on SQLite and Postgres.

## Quick start: CLI

Requires Python 3.11+.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

python -m kora "Chinua Achebe" --limit 20
python -m kora "Ngugi wa Thiong'o" --audit
python -m kora "Wole Soyinka" --json .out/soyinka.json
```

On macOS/Linux, activate with `source .venv/bin/activate`.

Useful flags:

| Flag | Meaning |
| --- | --- |
| `--pick N` | Choose the Nth identity candidate from the "did you mean" list. |
| `--limit N` | Rows per section (default 15). |
| `--json PATH` | Write the full merged profile, including raw work records and source status. |
| `--no-about` | Skip works about the person. |
| `--no-cache` | Bypass the 24-hour HTTP cache. |
| `--audit` | Show role/category/source counts and flagged records. |

Optional environment variables:

```powershell
$env:KORA_MAILTO = "you@example.org"       # polite contact for OpenAlex/User-Agent
$env:OPENALEX_API_KEY = "..."              # improves OpenAlex rate limits
```

## Quick start: API + Postgres

```powershell
# from the repository root
docker compose up -d db

cd backend
$env:KORA_DATABASE_URL = "postgresql+psycopg://kora:kora@localhost:5432/kora"
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn kora.api.app:app --reload --port 8000
```

Or run the API and database together with `docker compose up --build`. The API container applies migrations before starting. Schema creation at API startup is disabled by default; set `KORA_AUTO_CREATE_SCHEMA=true` only for a throwaway database. See `.env.example`. Tests use temporary SQLite databases and do not need Docker or Postgres.

Endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process and database health. |
| `POST` | `/v1/profiles/resolve` | Resolve a query live and persist the profile by default. Set `"persist": false` to skip the write. |
| `GET` | `/v1/profiles/{query}` | Resolve a query live without writing; supports `pick` and `include_about`. |
| `GET` | `/v1/scholars` | List stored scholars with by/about counts and refresh state. |
| `GET` | `/v1/scholars/{id}` | Read a stored canonical profile. |
| `GET` | `/v1/review` | Review queue; filter by status, kind or scholar. |
| `GET` | `/v1/review/{id}` | Read one review item. |
| `PATCH` | `/v1/review/{id}` | Set an item to `pending`, `resolved` or `dismissed`, with an optional note. |

PowerShell example:

```powershell
$body = @{ query = "Chinua Achebe"; include_about = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/v1/profiles/resolve `
  -ContentType "application/json" -Body $body
```

The API persists scholars, identities, global works, source records, access links and the scholar-work relation/role. It also stores the latest profile snapshot (bio, source status, alternatives and flagged records) so stored profiles can be read back without re-querying every source. Every save syncs grey identities and flagged records into `review_items`; matching items are updated in place, so a human decision is not lost when the profile is refreshed.

## Tests and golden profiles

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\golden.py
```

`pytest` covers normalization, identity clustering, work merging, role heuristics, about-detection, flags, alternatives, golden-check mechanics, the API contract, review-queue behavior, the refresh job, and full SQLite persistence round-trips. The suite currently passes **54 tests** offline; the Postgres-only round-trip skips unless `KORA_TEST_DATABASE_URL` is set. CI also runs `alembic upgrade head` and `alembic check` against Postgres to catch model/migration drift.

`scripts/golden.py` runs semantic regression checks against four authors using `tests/golden/authors.json`. It asserts must-have works, correct roles, provenance, alternatives and broad count ranges, then reports any failed source calls. It uses the cache by default; add `--no-cache` to force live sources, `--only "Wole Soyinka"` to run one author, or `--dump-dir .out/golden` to save full profiles.

Refresh stored profiles with:

```powershell
python scripts\refresh.py --limit 25 --stale-hours 168
python scripts\refresh.py --only 1
```

The job is intentionally manual/schedulable rather than an embedded worker. It refreshes one scholar at a time, records failures in `scholar_profiles.refresh_error`, and refuses to overwrite a scholar when live resolution returns a different canonical identity.

### Current cached profiles

These are regression snapshots from live sources, not fixed truth. Source data changes.

| Author | Raw records | Unique works | Main books (author/editor) | Other-language | Contributions | About | Flagged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chinua Achebe | 360 | 238 | 35 (31/4) | 5 | 72 | 65 | 52 |
| Wole Soyinka | 451 | 363 | 79 (75/4) | 13 | 11 | 91 | 1 |
| Ngũgĩ wa Thiong'o | 307 | 255 | 47 (47/0) | 8 | 9 | 53 | 1 |
| Wangari Muta Maathai | 120 | 106 | 15 (15/0) | 2 | 2 | 18 | 2 |

Achebe's main book count is within the Phase 0 target of 25–40. Soyinka and Ngũgĩ remain above it because their bibliographies include many translations/editions that sources do not consistently tag with a language. Those records are kept rather than guessed into the translations section.

## Architecture

```text
backend/
  kora/
    models.py           RawPerson/RawWork -> canonical Person/Work/Profile
    normalize.py        name, title, language, ISBN and DOI normalization
    resolve.py          identity clustering, work merge, role/relation logic, flags
    aggregator.py       concurrent source fan-out, grey-identity corroboration
    connectors/
      wikidata.py       identity hub: humans, aliases, external IDs
      openalex.py       scholarly works, about-search, author positions
      openlibrary.py    books/editions, subjects, covers, borrowable scans
    cli.py              Rich terminal presentation and JSON export
    golden.py           golden-profile check logic
    refresh.py          batch refresh service with identity-change guard
    api/
      app.py            FastAPI app, dependencies and endpoints
      schemas.py        typed profile/work/person/review API contracts
    storage/
      database.py       async engine, settings, optional schema bootstrap
      tables.py         SQLAlchemy canonical schema and review queue
      repository.py     profile upsert, snapshots, review items and reads
  alembic/
    env.py              async migration environment
    versions/           schema migrations
  scripts/
    golden.py           golden-profile runner
    refresh.py          refresh stored profiles from the CLI
    debug_people.py     inspect identity candidates without fetching works
    summarize.py        summarize a profile JSON file
  tests/
    golden/authors.json semantic golden fixture
    test_api.py         API tests with a fake resolver + SQLite
    test_storage.py     persistence, idempotent upsert and review decisions
    test_refresh.py     refresh success, failure and identity-change guard
    test_postgres.py    optional Postgres round-trip for CI
```

Resolution follows two layers:

1. **People.** Wikidata humans are hubs. Direct identifier claims (Open Library/OpenAlex/ORCID IDs) attach with `HARD_ID`; date/affiliation/alias corroboration attaches with `HIGH`; name-only matches stay `GREY` and are not used for works unless corroborated by shared distinctive titles. Conflicts are never merged.
2. **Works.** Records merge on DOI/ISBN first, then conservative title rules. Title matching refuses to merge a work with its study guide, review or same-titled critical book, and treats generic titles more cautiously. The primary record determines display metadata; links and identifiers are unioned.

Every source call is isolated: one failing API degrades the profile and shows up under **Source status** instead of breaking the run.

### Storage model

- `scholars`: canonical person and natural key (Wikidata/ORCID/Open Library/OpenAlex).
- `identities`: every source identity, confidence level, evidence and raw metadata.
- `works`: global merged works keyed deterministically by category, title, year (for non-books) and first author.
- `work_records`: the source records that produced each work, preserving provenance.
- `work_links`: legal access links with kind and label.
- `scholar_works`: the relation (`by`/`about`) and role (`author`/`editor`/`contributor`) for each scholar-work pair.
- `scholar_profiles`: latest snapshot fields that do not belong on canonical entities (bio, source status, alternatives, flagged records), plus refresh timestamps and the last refresh error.
- `review_items`: durable grey-identity and flagged-record decisions, keyed by a stable fingerprint per scholar.

A profile upsert is transactional and idempotent: identities and works are updated, stale scholar-work links are removed, and the stored snapshot is replaced. Review items are upserted separately so human decisions survive later refreshes. A pending item that disappears from the latest resolution is marked `superseded`; it is never silently deleted.

## Legal and data policy

- Kora links to copies; it does not host or mirror copyrighted full text.
- OA links come from source metadata (OpenAlex `open_access`, Open Library/Internet Archive access flags).
- Publisher and library links are for discovery and lawful access.
- Provenance is preserved at the work level (`Work.records`) and exposed in the JSON output.

## Known limitations

- **Role inference is heuristic.** Open Library and OpenAlex list forewords, afterwords and contributions as bylines. Position, title and contributor-count signals catch many anthology cases, but some introductions can still look like co-authorship.
- **Language metadata is incomplete.** Some translations remain in the main book section; the split only moves records with at least one known non-English language and no English.
- **"About" is precision-first, not complete.** The OpenAlex title search deliberately avoids abstract-only mentions; the trade-off is fewer false positives and some missed criticism.
- **Entity resolution still needs review.** OpenAlex author IDs can be split or conflated; `GREY` identities are surfaced for future AI/human adjudication rather than silently trusted.
- **Coverage is source-bound.** No Crossref, Africa-specific databases, institutional repositories or ORCID connector yet; the connector interface is designed for them.
- **The API is a Phase 1A slice.** Authentication, rate limiting, scheduling and the public web UI are still missing. Profile resolution is live per request (with an HTTP cache); `POST /v1/profiles/resolve` writes a snapshot, while the GET profile route stays read-only. A warm read model and search index are next.
- **Refresh is manual or cron-driven.** `scripts/refresh.py` refreshes sequentially and records failures, but there is no scheduler, retry policy or distributed lock yet. Run one instance per batch to avoid duplicate work.
- **Review decisions are operator-facing only.** The queue is durable, but there is no authentication or audit log around who changed a decision yet.
- **Database writes replace mutable sub-records.** A profile refresh replaces work records/links for that work and the scholar-work links. This keeps upserts simple and idempotent, but a future ingestion pipeline should version provenance and merge records across jobs.
- **Performance needs Phase 1 work.** Warm-cache profiles are fast enough for development, but the earlier Achebe `--no-about` timing (about 4 s) was above the p95 <3 s target and has not been re-profiled after the latest changes.
- **Achebe's flagged records are mostly DOI-form metadata noise**, not bibliography entries; flags stay inspectable rather than being deleted.

## Phase 1 progress and next work

Done in Phase 1A:

1. FastAPI service with typed profile/work/person/review contracts and OpenAPI docs.
2. Alembic-managed Postgres schema for scholars, identities, works, records, links, scholar-work relations and review items.
3. Transactional, idempotent profile persistence and stored-profile retrieval.
4. Durable review queue for grey identities and flagged records, including supersede semantics.
5. Conservative refresh job with per-scholar failure recording and identity-change protection.
6. Docker Compose for Postgres and the API, plus SQLite and Postgres CI with migration-drift checks.

Next:

1. Authentication, rate limiting and an operator identity around review decisions.
2. A warm read model/search index so stored profiles are served without live source calls.
3. Background scheduling, retries, locking and provenance history for refresh/ingestion jobs.
4. Web app for scholar profiles, work pages and legal access links.
5. Africa-specific sources, repository connectors and partnership ingestion.
6. Select the pilot scope and access model, then instrument the metrics that matter for it.

Open product questions remain: final name/brand, business model, first Phase 2 countries, partnerships and team shape. They do not block the Phase 1 engineering work.
