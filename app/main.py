import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .scanner import Scanner
from .public import PublicReadLimit, PublicStatistics, positive_env
from .store import Store

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).parent / 'static'


def create_app(db_path=None, replay_dir=None, interval=None, config_path=None):
    store = Store(db_path or os.getenv('DATABASE_PATH', 'data/faf.sqlite3'), config_path)
    scanner = Scanner(store, replay_dir or os.getenv('REPLAY_DIR', 'replays'))
    statistics = PublicStatistics(store,
        ttl=positive_env('STATS_CACHE_SECONDS', 30),
        build_rate=positive_env('STATS_BUILD_RATE', 2),
        build_burst=positive_env('STATS_BUILD_BURST', 8))
    scan_interval = max(5, interval or int(os.getenv('SCAN_INTERVAL_SECONDS', '60')))

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()
        async def worker():
            while not stop.is_set():
                await asyncio.to_thread(scanner.scan)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=scan_interval)
                except TimeoutError:
                    pass
        task = asyncio.create_task(worker())
        yield
        stop.set()
        await task

    app = FastAPI(title='FAF Aftermath', lifespan=lifespan)
    app.add_middleware(PublicReadLimit,
                       rate=positive_env('API_RATE_PER_SECOND', 10),
                       burst=positive_env('API_RATE_BURST', 30))
    app.state.store, app.state.scanner, app.state.statistics = store, scanner, statistics
    app.mount('/static', StaticFiles(directory=STATIC), name='static')

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/healthz')
    def health():
        with store.connect() as db:
            db.execute('SELECT 1')
        return {'status': 'ok'}

    @app.get('/api/dashboard')
    def dashboard(player: str | None = Query(None, max_length=100),
                  since: float | None = Query(None, ge=0, allow_inf_nan=False),
                  minimum: int = Query(2, ge=1, le=1000)):
        return statistics.dashboard(player, since, minimum)

    @app.get('/api/games/{game_id}')
    def game(game_id: str):
        return statistics.game(game_id)

    @app.get('/api/roster')
    def roster():
        policy = store.policy()
        return {'policy': {'configured': True, 'player_ids': policy['player_ids'],
                           'max_outsiders': policy['max_outsiders'], 'min_friends': policy['min_friends'], 'error': bool(policy['error'])},
                'players': policy['players']}

    @app.get('/api/status')
    def status():
        return {**scanner.status(), 'interval': scan_interval}

    return app


app = create_app()
