# Kora

**An Africa-first academic aggregator: everything by and about a scholar, with provenance and legal access links.**

Kora is being built from the researcher's side outward. Given a person's name, it resolves their identity across open scholarly and bibliographic sources, merges duplicate records into works, separates books from articles, anthologies and works *about* them, and points to open-access, publisher, library or preview copies. It never hosts copyrighted full text.

This repository contains the **hardened Phase 0.5 resolution engine** plus the **start of Phase 1**: a FastAPI service with a normalized Postgres schema, a temporary SQLite test path and Docker Compose for local Postgres.

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
- Docker Compose Postgres and an OpenAPI UI at `/docs`.

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
python -m uvicorn kora.api.app:app --reload --port 8000
```

Open <http://127.0.0.1:8000/docs> for the interactive API. The development default creates the schema at startup (`KORA_AUTO_CREATE_SCHEMA=true`); see `.env.example`. Tests use a temporary SQLite database and do not need Docker or Postgres.

Endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process and database health. |
| `POST` | `/v1/profiles/resolve` | Resolve a query live and persist the profile by default. Set `"persist": false` to skip the write. |
| `GET` | `/v1/profiles/{query}` | Resolve a query live without writing; supports `pick` and `include_about`. |
| `GET` | `/v1/scholars` | List stored scholars with by/about counts. |
| `GET` | `/v1/scholars/{id}` | Read a stored canonical profile. |

PowerShell example:

```powershell
$body = @{ query = "Chinua Achebe"; include_about = $true } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/v1/profiles/resolve `
  -ContentType "application/json" -Body $body
```

The API persists scholars, identities, global works, source records, access links and the scholar-work relation/role. It also stores the latest profile snapshot (bio, source status, alternatives and flagged records) so stored profiles can be read back without re-querying every source.

## Tests and golden profiles

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\golden.py
```

`pytest` covers normalization, identity clustering, work merging, role heuristics, about-detection, flags, alternatives, golden-check mechanics, the API contract, and a full SQLite persistence round-trip. The suite currently passes **49 tests** offline.

`scripts/golden.py` runs semantic regression checks against four authors using `tests/golden/authors.json`. It asserts must-have works, correct roles, provenance, alternatives and broad count ranges, then reports any failed source calls. It uses the cache by default; add `--no-cache` to force live sources, `--only "Wole Soyinka"` to run one author, or `--dump-dir .out/golden` to save full profiles.

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
    api/
      app.py            FastAPI app, dependencies and endpoints
      schemas.py        typed profile/work/person API contracts
    storage/
      database.py       async engine, settings, schema bootstrap
      tables.py         SQLAlchemy canonical schema
      repository.py     profile upsert and stored-profile reconstruction
  scripts/
    golden.py           golden-profile runner
    debug_people.py     inspect identity candidates without fetching works
    summarize.py        summarize a profile JSON file
  tests/
    golden/authors.json semantic golden fixture
    test_api.py         API tests with a fake resolver + SQLite
    test_storage.py     persistence round-trip and idempotent upsert
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
- `scholar_profiles`: latest snapshot fields that do not belong on canonical entities (bio, source status, alternatives, flagged records).

A profile upsert is transactional and idempotent: identities and works are updated, stale scholar-work links are removed, and the stored snapshot is replaced.

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
- **The API is an early Phase 1 slice.** There is no authentication, rate limiting, background refresh or migration tooling yet. `create_all` is a development convenience; use Alembic before production. Profile resolution is still live per request (with an HTTP cache), not served from a warm store.
- **Database writes replace mutable sub-records.** A profile refresh replaces work records/links for that work and the scholar-work links. This keeps upserts simple and idempotent, but a future ingestion pipeline should version provenance and merge records across jobs.
- **Performance needs Phase 1 work.** Warm-cache profiles are fast enough for development, but the earlier Achebe `--no-about` timing (about 4 s) was above the p95 <3 s target and has not been re-profiled after the latest changes.
- **Achebe's flagged records are mostly DOI-form metadata noise**, not bibliography entries; flags stay inspectable rather than being deleted.

## Phase 1 progress and next work

Done in this slice:

1. FastAPI service with typed profile/work/person contracts and OpenAPI docs.
2. Postgres schema for scholars, identities, works, records, links and scholar-work relations.
3. Transactional, idempotent profile persistence and stored-profile retrieval.
4. Docker Compose Postgres, environment template and SQLite-backed tests.

Next:

1. Alembic migrations and production database lifecycle.
2. Background ingestion/refresh jobs with source status, provenance history and retries.
3. Persistent disambiguation queue for grey identities and flagged records.
4. API authentication, rate limiting and caching responses from stored canonical entities.
5. Web app for scholar profiles, work pages and legal access links.
6. Africa-specific sources, repository connectors and partnership ingestion.

Open product questions remain: final name/brand, business model, first Phase 2 countries, partnerships and team shape. They do not block the Phase 1 engineering work.
