"""Bounded, anonymous public reads. Never trust forwarded headers for quotas."""
import json
import os
import threading
import time
from collections import OrderedDict

from fastapi import HTTPException
from starlette.responses import JSONResponse, Response

from .elo import calculate_elo
from .roster import exclusion_reason
from .stats import has_known_result, statistics_game, summarize


def positive_env(name, default):
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f'{name} must be a positive integer')
    return value


class TokenBucket:
    def __init__(self, rate, burst, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.tokens, self.updated = float(burst), clock()
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


class PublicReadLimit:
    """One global bucket per process: works behind Newt without spoofable IP keys."""
    def __init__(self, app, rate=10, burst=30):
        self.app = app
        self.bucket = TokenBucket(rate, burst)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'].startswith('/api/'):
            if not self.bucket.take():
                response = JSONResponse({'detail': 'Zu viele Anfragen. Bitte kurz warten.'}, status_code=429,
                                        headers={'Retry-After': '1', 'Cache-Control': 'no-store'})
                await response(scope, receive, send)
                return
            if len(scope.get('query_string', b'')) > 2048 or len(scope['path']) > 512:
                await JSONResponse({'detail': 'Anfrage zu lang.'}, status_code=414)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class PublicStatistics:
    def __init__(self, store, ttl=30, max_entries=64, max_bytes=16*1024*1024,
                 build_rate=2, build_burst=8, clock=time.monotonic):
        self.store, self.ttl, self.clock = store, ttl, clock
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.entries, self.bytes = OrderedDict(), 0
        self.lock = threading.Lock()
        self.build_budget = TokenBucket(build_rate, build_burst, clock)
        self.generation = None
        self.games, self.by_id = [], {}

    def _response(self, body):
        # Don't let browsers/proxies retain a response after the friend list changes.
        return Response(body, media_type='application/json', headers={'Cache-Control': 'no-store'})

    def _put(self, key, body):
        if len(body) > self.max_bytes:
            return  # Large archives can still be served, but cannot grow the cache unboundedly.
        while self.entries and (len(self.entries) >= self.max_entries or self.bytes + len(body) > self.max_bytes):
            _, (_, evicted) = self.entries.popitem(last=False)
            self.bytes -= len(evicted)
        self.entries[key] = (self.clock() + self.ttl, body)
        self.bytes += len(body)

    def _read(self, kind, player=None, since=None, minimum=2, game_id=None):
        # A cache miss cannot create an unbounded queue of expensive work.
        if not self.lock.acquire(blocking=False):
            raise HTTPException(503, 'Statistik wird gerade aktualisiert. Bitte kurz warten.',
                                headers={'Retry-After': '1', 'Cache-Control': 'no-store'})
        try:
            policy = self.store.policy()
            friends = set(policy['player_ids'])
            generation = (self.store.game_revision(), policy['revision'])
            # Invalid player requests share a cache entry; random strings cannot fill the cache.
            if player is not None and player not in friends:
                player, since, minimum = '__not_a_friend__', None, 2
            key = (kind, player, since, minimum, game_id)
            if generation == self.generation:
                cached = self.entries.get(key)
                if cached and cached[0] > self.clock():
                    self.entries.move_to_end(key)
                    return self._response(cached[1])
                if cached:
                    self.bytes -= len(self.entries.pop(key)[1])
                # Random nonexistent IDs don't spend aggregation work or cache space.
                if kind == 'game' and game_id not in self.by_id:
                    raise HTTPException(404, 'Partie nicht gefunden')
            if not self.build_budget.take():
                raise HTTPException(429, 'Zu viele neue Statistikabfragen. Bitte kurz warten.',
                                    headers={'Retry-After': '1', 'Cache-Control': 'no-store'})
            if generation != self.generation:
                eligible = [g for g in self.store.games()
                            if has_known_result(g) and exclusion_reason(g['players'], policy) is None]
                self.elo_games = eligible
                games = [statistics_game(g, friends) for g in eligible]
                self.games = games
                self.by_id = {g['id']: g for g in games}
                self.generation = generation
                self.entries.clear()
                self.bytes = 0
            if kind == 'replays':
                games = sorted(self.games, key=lambda g: (g.get('played_at') or 0, g['id']), reverse=True)
                document = {'count': len(games), 'replays': games}
            elif kind == 'game':
                document = self.by_id.get(game_id)
                if document is None:
                    raise HTTPException(404, 'Partie nicht gefunden')
            else:
                games = self.games
                if player:
                    games = [g for g in games if any(p['id'] == player for p in g['players'])]
                if since is not None:
                    games = [g for g in games if (g.get('played_at') or 0) >= since]
                document = summarize(games, minimum)
                # Current ratings always replay the full eligible archive, independent of filters.
                document['elo'] = {**calculate_elo(self.elo_games, friends), 'since': None}
            body = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            self._put(key, body)
            return self._response(body)
        finally:
            self.lock.release()

    def dashboard(self, player=None, since=None, minimum=2):
        return self._read('dashboard', player=player, since=since, minimum=minimum)

    def game(self, game_id):
        return self._read('game', game_id=game_id)

    def replays(self):
        return self._read('replays')
