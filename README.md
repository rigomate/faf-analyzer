# FAF Aftermath

A self-hosted replay dashboard for a regular group of friends. Python/FastAPI, the real `faf-replay-parser` library, SQLite, and a lightweight browser UI. No API keys, external services, Node build, or game installation required.

## Run with Docker

```sh
cp .env.example .env
# Optional: edit REPLAY_PATH, PORT, and SCAN_INTERVAL_SECONDS.
docker compose up -d --build
```

Open **http://localhost:8080**. The supplied `replays/` folder is mounted read-only. New `.fafreplay` and `.scfareplay` files in this folder or subdirectories are picked up every 60 seconds. The dashboard refreshes every 15 seconds. Copy a file completely before expecting it to appear; imports wait at least 10 seconds after its last modification.

SQLite persists in the `faf-data` Docker volume at `/data/faf.sqlite3`. `docker compose down` preserves it; `docker compose down -v` deletes it. Containers run as UID 10001 by default (configurable using `APP_UID`); the replay folder must be readable and traversable by that user. Set `APP_UID` in `.env` to the replay owner’s numeric UID (`id -u`) before building if files are owner-readable only. The local `.env` is already configured with UID 1000 and port 8093 for this workspace. The named database volume is initialized with the correct ownership on first use. If you later change APP_UID, migrate the existing database volume ownership to that UID before starting the rebuilt container.

### Pangolin

The app serves plain HTTP on container port **8080**, with no TLS or login of its own. Compose connects it to your existing external Docker network **`pangolin`**. The network must already exist, and your Pangolin/Newt connector must also be attached to it.

Set the Pangolin target to **`http://faf-analyzer:8080`**. Use a dedicated hostname at `/` (a URL subpath is not supported). Host access remains available through the published loopback port (`8080` by default, `8093` in this workspace's `.env`).

Apply network changes with `docker compose up -d`. For a standalone installation without an existing Pangolin network, create it first with `docker network create pangolin`.

```sh
docker compose logs -f
docker compose ps
```

`GET /healthz` checks HTTP/database availability. The Replay-Import tab and `/api/status` expose only counts and a generic error flag. Detailed diagnostics are available only on the server.

## What you can see

- Teammate win-rate matrix, pair records, minimum sample-size filter, smoothed estimates, and 95% Wilson intervals. Pair rankings favor stronger evidence instead of ranking one lucky match first.
- Player wins, losses, draws, unknown outcomes; reclaimed mass, experimentals built, total mass and energy income, and wasted mass. Switch between averages, totals, and personal bests; sort the columns.
- Match reports with original teams, factions, individual reported outcomes, team outcomes, and per-player statistics with snapshot timestamps.
- Player and date filters, searchable match archive, JSON export, and automatic import status.

## Friend list and outsiders

Edit **`config/friends.json`** on the host. This is the only source of friend-list settings. The public dashboard and all HTTP endpoints are read-only; there is no web editor or settings-write API.

```json
{
  "max_outsiders": 0,
  "players": [
    {"id": "303498", "name": "rigomate"},
    {"id": "25228", "name": "DerKinderRiegel"}
  ]
}
```

The supplied file contains the 12 friends you confirmed. `id` is the stable numeric FAF ID, written as a JSON string; `name` is a descriptive label. Nickname changes do not affect membership. Add or remove player entries to change your group.

- **`max_outsiders: 0`**: every active human player on both teams must be on your list.
- **`max_outsiders: 1`**: allow one human outsider across both teams combined.
- At least one listed friend must participate. An empty list excludes all matches. Spectators, civilians, and AI do not count toward the human outsider limit.

Compose mounts the entire `config/` directory read-only into the container. File changes, including atomic saves by editors, are picked up without a restart: existing statistics are filtered on the next HTTP request, and replay files are reconsidered on the next scheduled scan (normally within 60 seconds). The browser refreshes every 15 seconds. When running without Compose, set `FRIENDS_CONFIG_PATH` to your configuration file (local default: `config/friends.json`).

Missing or invalid configuration excludes all matches and pauses imports until corrected; it never disables the filter or falls back to old SQLite settings. The website shows a generic configuration-error notice; use container logs or the diagnostic command below for the details. Existing database records remain intact, and relaxing a rule can restore their visibility.

The importer decompresses each new replay and checks its internal header **before parsing body events or extracting statistics**. Exclusion reasons and outsider names are kept in server diagnostics, not published on the website. The outsider allowance only determines which matches qualify. Player totals, leaderboards, the teammate matrix, player selectors, match-report statistics, and JSON statistics include only configured friends. Guest statistics are excluded even for previously imported games. Match headcounts still include guests, and team outcomes are resolved from the complete replay roster before filtering.

`GET /api/roster` exposes the current rule and configured players for display. `POST`, `PUT`, `PATCH`, and `DELETE` are not supported. The legacy database settings table, if present from an earlier version, is ignored.

## Anonymous public access

The website needs no login. Pangolin handles public HTTPS and routing; the application exposes only read-only HTTP endpoints. Keep the backend on the intended private Docker network or loopback interface.

Public diagnostics are deliberately limited:

- `/api/status` returns import/exclusion/error counts, scan timing, and a generic error flag. It never returns file lists, paths, exclusion reasons, outsider names, signatures, or exception messages.
- `/api/roster` publishes only the configured friends and rule, with a boolean configuration-error flag.
- Dashboard JSON, match reports, and exports omit source filenames, hashes, and internal warnings. Friends-only statistics remain unchanged.

For operator diagnostics on the server:

```sh
docker compose logs --tail=200 faf-analyzer
docker compose exec faf-analyzer python -m app.diagnostics
```

The second command includes already recorded errors/exclusions, even if they aren't in recent logs. Do not publish that output as a public endpoint.

### Caching and request limits

The app keeps one parsed archive snapshot and caches serialized responses. SQLite triggers increment a revision when a game is inserted, replaced, updated, or deleted. Requests check that revision and the file-based friend policy before serving a cached response. Changes invalidate cached data immediately, including tightening the friend rule or an invalid configuration. Responses use `Cache-Control: no-store` so browsers and proxies don't retain outdated friend data.

The response cache holds at most **64 entries / 16 MiB**, with a default lifetime of **30 seconds**. Oversized responses are served without caching. The archive snapshot itself grows with your stored games. Normal date filters use a fixed UTC-midnight cutoff, so refreshing the page reuses the same cache entry.

Limits are global across all visitors, **per application process**, and intentionally do not use `X-Forwarded-For` or client-IP attribution. They work behind Pangolin/Newt without trusting visitor-supplied forwarding headers. A visitor can consume shared capacity; these limits bound application work, not volumetric DDoS traffic.

| Environment variable | Default | Meaning |
|---|---:|---|
| `API_RATE_PER_SECOND` | 10 | Sustained requests/second across `/api/*` |
| `API_RATE_BURST` | 30 | Burst allowance for API requests |
| `STATS_CACHE_SECONDS` | 30 | Serialized-response cache lifetime |
| `STATS_BUILD_RATE` | 2 | Sustained uncached statistic calculations/second |
| `STATS_BUILD_BURST` | 8 | Burst allowance for new statistic calculations |

Exhausted quotas return **429** with `Retry-After: 1`. Only one statistics read/build runs at a time; a concurrent request gets **503** with the same retry hint rather than joining an unbounded work queue. Cached requests don't spend the calculation quota. Static assets and `/healthz` are outside the API quota. The German UI keeps the current view and explains temporary overload; automatic refresh retries later.

All values must be positive integers. Adjust them in `.env` and apply with `docker compose up -d`. Keep one Uvicorn worker as configured; separate workers would each have their own cache and quota. These changes do not add authentication or TLS inside the app, and do not impose replay decompression/process limits.

## Data interpretation

The importer reads the binary replay using [`faf-replay-parser`](https://github.com/Askaholic/faf-replay-parser-python). It supports the library's compressed FAF formats as well as raw SCFA replays. Player identities and teams come from the **internal army records**, not the outer JSON teams list: the latter omits several players in the supplied files. Army indexes in the parser are zero-based; recorded `GameResult` indexes are one-based.

Current sample replays embed `ModeratorEvent` callbacks with `GpgNetSend ... GameResult` and `JsonStats` payloads. These contain actual reported statistics. The importer never counts build orders as completed units, or reclaim commands as reclaimed mass. It never executes replay Lua.

- A team wins when one of its members has an explicit victory event. Eliminated teammates share that team victory. A single confirmed winning team resolves the other teams as losses. Conflicting winners, unlocked teams, and absent victory events remain unknown; all-player explicit draws remain draws. This uses **starting teams** and is intended for standard locked-team games.
- Economy means `resources.massin.total`, including reclaim, rather than instantaneous income rate or an estimate of skill. Reclaim is `resources.massin.reclaimed`; experimentals are `units.experimental.built`. Energy income and overflow use the corresponding resource counters.
- Each player's most recent snapshot by `general.lastupdatetick` is retained. Duplicate snapshots from multiple peers are not summed. A snapshot may precede the end of the game; the UI shows its timestamp. Reported values can reflect game/mod sharing rules.
- Some replays contain no snapshots or result events, especially early exits and older game versions. Missing values remain null and are excluded from metric averages. **This app cannot reconstruct missing simulation statistics from orders.** Each metric shows its coverage, and all unknown results are excluded from win-rate denominators.
- Pair estimates are `(wins + 1) / (wins + losses + 2)`, with Wilson intervals around the observed win rate. These are descriptive, not calibrated forecasts; they do not control for the map, opponents, or other teammates.

Initial sample validation: **13 replays, 11 players, 10 resolved matches, 9 matches with recorded statistics**. This is real extracted data, not demo content.

## Import and persistence behavior

Files are tracked by relative path, size, and nanosecond modification timestamp. Unchanged successful files are skipped. Failed imports do not stop other files and retry after five minutes; changed files retry at the next scan. A file that changes during parsing is deferred. Game IDs deduplicate copies saved by different friends; the recording with a confirmed outcome, then more player snapshots, then longer duration takes precedence. Raw SCFA files without FAF IDs deduplicate by SHA-256. Replay files are never modified or deleted. Removing a source file does not remove its archived match.

The database has `games` (version-independent JSON documents keyed by match ID), `files` (private import tracking), and `revisions` (cache invalidation) tables. Older databases are migrated automatically. One Uvicorn worker runs the background scanner; don't enable multiple workers or replicas against the same SQLite volume. Reads and imports use separate SQLite connections with WAL mode. Parsing happens outside the HTTP event loop.

For a consistent backup while running:

```sh
docker compose exec faf-analyzer python -c "import sqlite3; src=sqlite3.connect('/data/faf.sqlite3'); dst=sqlite3.connect('/data/backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
docker compose cp faf-analyzer:/data/backup.sqlite3 ./faf-backup.sqlite3
```

To restore, stop the service, replace the database in the volume with the backup, remove any old `-wal`/`-shm` companions, ensure the configured APP_UID owns the restored database, and start the service.

## Local development

Python 3.12 recommended (the Docker image uses it).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
.venv/bin/pytest -q
```

Local defaults: `REPLAY_DIR=replays`, `DATABASE_PATH=data/faf.sqlite3`, `SCAN_INTERVAL_SECONDS=60`, and `FRIENDS_CONFIG_PATH=config/friends.json`. Override with environment variables. The sample integration tests automatically skip when the replay folder is absent.

Statistics JSON endpoints: `/api/dashboard` (optional `player`, Unix timestamp `since`, and `minimum`), `/api/games/{id}`, `/api/status`. OpenAPI docs are at `/docs`.
