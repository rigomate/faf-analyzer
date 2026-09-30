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

The app serves plain HTTP on container port **8080**, with no TLS or login of its own. By default Compose publishes it on host loopback `127.0.0.1:8080`. Point Pangolin at that address if its connector shares the host network; otherwise attach its connector to the Compose network and target `http://faf-analyzer:8080`, or set `BIND_ADDRESS` to a host interface reachable by the connector. Use a dedicated hostname at `/` (a URL subpath is not supported). Configure access control at your proxy if desired.

```sh
docker compose logs -f
docker compose ps
```

`GET /healthz` checks HTTP/database availability. The Import status tab and `/api/status` report scanner errors separately.

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

The supplied file contains all 11 friends you confirmed. `id` is the stable numeric FAF ID, written as a JSON string; `name` is a descriptive label. Nickname changes do not affect membership. Add or remove player entries to change your group.

- **`max_outsiders: 0`**: every active human player on both teams must be on your list.
- **`max_outsiders: 1`**: allow one human outsider across both teams combined.
- At least one listed friend must participate. An empty list excludes all matches. Spectators, civilians, and AI do not count toward the human outsider limit.

Compose mounts the entire `config/` directory read-only into the container. File changes, including atomic saves by editors, are picked up without a restart: existing statistics are filtered on the next HTTP request, and replay files are reconsidered on the next scheduled scan (normally within 60 seconds). The browser refreshes every 15 seconds. When running without Compose, set `FRIENDS_CONFIG_PATH` to your configuration file (local default: `config/friends.json`).

Missing or invalid configuration excludes all matches and pauses imports until corrected; it never disables the filter or falls back to old SQLite settings. Check Import status or container logs for configuration errors. Existing database records remain intact, and relaxing a rule can restore their visibility.

The importer decompresses each new replay and checks its internal header **before parsing body events or extracting statistics**. Excluded files show the outsider names in Import status. Allowed guests remain visible in eligible match reports and statistics.

`GET /api/roster` exposes the current rule and configured players for display. `POST`, `PUT`, `PATCH`, and `DELETE` are not supported. The legacy database settings table, if present from an earlier version, is ignored.

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

The database has `games` (version-independent JSON documents keyed by match ID), `files` (import tracking, roster, policy revision, and errors) tables. Older databases are migrated automatically. One Uvicorn worker runs the background scanner; don't enable multiple workers or replicas against the same SQLite volume. Reads and imports use separate SQLite connections with WAL mode. Parsing happens outside the HTTP event loop.

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
