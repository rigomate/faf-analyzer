import json
import logging
import threading
import time
from pathlib import Path
from .parser import parse_replay, ExcludedReplay

logger = logging.getLogger(__name__)


class Scanner:
    def __init__(self, store, directory, settle_seconds=10):
        self.store, self.directory = store, Path(directory)
        self.settle_seconds = settle_seconds
        self.lock = threading.Lock()
        self.last_scan = None
        self.last_error = None
        self.running = False

    def scan(self):
        if not self.lock.acquire(blocking=False):
            return
        self.running = True
        try:
            if not self.directory.is_dir():
                raise FileNotFoundError('Replay directory is missing: ' + str(self.directory))
            known = {r['path']: r for r in self.store.files()}
            policy = self.store.policy()
            if policy.get('error'):
                raise ValueError(policy['error'])
            for path in sorted(self.directory.rglob('*')):
                if path.suffix.lower() not in {'.fafreplay', '.scfareplay'} or not path.is_file():
                    continue
                relative = str(path.relative_to(self.directory))
                signature = ''
                try:
                    st = path.stat()
                    signature = f'{st.st_size}:{st.st_mtime_ns}'
                    previous = known.get(relative)
                    if time.time() - st.st_mtime < self.settle_seconds:
                        continue
                    if previous and previous['signature'] == signature and previous['policy_revision'] == policy['revision']:
                        if previous['status'] in {'imported', 'excluded'} or time.time() - previous['checked_at'] < 300:
                            continue
                    try:
                        game = parse_replay(path, policy)
                    except ExcludedReplay as exc:
                        after = path.stat()
                        if (st.st_size, st.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            continue
                        with self.store.connect() as db:
                            db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?)',
                                       (relative, signature, 'excluded', str(exc), time.time(), exc.game_id,
                                        policy['revision'], json.dumps(exc.players)))
                        continue
                    after = path.stat()
                    if (st.st_size, st.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        continue
                    with self.store.connect() as db:
                        existing = db.execute('SELECT document FROM games WHERE id=?', (game['id'],)).fetchone()
                        # Multiple friends can save the same match. Keep the richer recording.
                        quality = lambda g: (g['outcome'] == 'resolved', sum(p['stats_tick'] is not None for p in g['players']), g['duration'])
                        if not existing or quality(game) >= quality(json.loads(existing[0])):
                            db.execute('INSERT OR REPLACE INTO games VALUES (?,?,?)', (game['id'], json.dumps(game), time.time()))
                        db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?)',
                                   (relative, signature, 'imported', None, time.time(), game['id'], policy['revision'], json.dumps(game['players'])))
                except Exception as exc:
                    logger.exception('Could not import %s', relative)
                    with self.store.connect() as db:
                        db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?)',
                                   (relative, signature, 'error', str(exc)[:500], time.time(), None, policy['revision'], '[]'))
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception('Replay scan failed')
        finally:
            self.last_scan = time.time()
            self.running = False
            self.lock.release()

    def status(self):
        return dict(running=self.running, last_scan=self.last_scan, error=self.last_error,
                    files=self.store.files())
