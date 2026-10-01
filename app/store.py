import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .roster import exclusion_reason, load_policy
from .stats import has_known_result


class Store:
    def __init__(self, path, config_path=None):
        self.path = str(path)
        self.config_path = config_path or os.getenv('FRIENDS_CONFIG_PATH', 'config/friends.json')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS revisions (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT OR IGNORE INTO revisions VALUES ('games', 0);
                CREATE TABLE IF NOT EXISTS games (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL, imported_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, signature TEXT NOT NULL, status TEXT NOT NULL,
                    error TEXT, checked_at REAL NOT NULL, game_id TEXT);
                CREATE TRIGGER IF NOT EXISTS games_insert_revision AFTER INSERT ON games
                    BEGIN UPDATE revisions SET value=value+1 WHERE name='games'; END;
                CREATE TRIGGER IF NOT EXISTS games_update_revision AFTER UPDATE ON games
                    BEGIN UPDATE revisions SET value=value+1 WHERE name='games'; END;
                CREATE TRIGGER IF NOT EXISTS games_delete_revision AFTER DELETE ON games
                    BEGIN UPDATE revisions SET value=value+1 WHERE name='games'; END;
            ''')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(files)')}
            if 'policy_revision' not in columns:
                db.execute('ALTER TABLE files ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT -1')
            if 'roster' not in columns:
                db.execute("ALTER TABLE files ADD COLUMN roster TEXT NOT NULL DEFAULT '[]'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def games(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT document FROM games')]

    def files(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM files ORDER BY path')]

    def policy(self):
        return load_policy(self.config_path)

    def eligible_games(self, policy=None):
        policy = self.policy() if policy is None else policy
        return [g for g in self.games() if has_known_result(g) and exclusion_reason(g['players'], policy) is None]

    def roster_settings(self):
        policy = self.policy()
        return dict(policy=policy, players=policy['players'])

    def game_revision(self):
        with self.connect() as db:
            return db.execute("SELECT value FROM revisions WHERE name='games'").fetchone()[0]

    def file_counts(self):
        counts = dict(imported=0, excluded=0, error=0)
        with self.connect() as db:
            for row in db.execute('SELECT status, COUNT(*) AS count FROM files GROUP BY status'):
                if row['status'] in counts:
                    counts[row['status']] = row['count']
        return counts
