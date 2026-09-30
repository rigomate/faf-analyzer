import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .scanner import Scanner
from .stats import summarize
from .store import Store

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).parent / 'static'


def create_app(db_path=None, replay_dir=None, interval=None, config_path=None):
    store = Store(db_path or os.getenv('DATABASE_PATH', 'data/faf.sqlite3'), config_path)
    scanner = Scanner(store, replay_dir or os.getenv('REPLAY_DIR', 'replays'))
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
    app.state.store, app.state.scanner = store, scanner
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
    def dashboard(player: str | None = None, since: float | None = None,
                  minimum: int = Query(2, ge=1, le=1000)):
        games = store.eligible_games()
        if player:
            games = [g for g in games if any(p['id'] == player for p in g['players'])]
        if since is not None:
            games = [g for g in games if (g.get('played_at') or 0) >= since]
        return summarize(games, minimum)

    @app.get('/api/games/{game_id}')
    def game(game_id: str):
        for g in store.eligible_games():
            if g['id'] == game_id:
                return g
        raise HTTPException(404, 'Game not found')

    @app.get('/api/roster')
    def roster():
        return store.roster_settings()

    @app.get('/api/status')
    def status():
        return {**scanner.status(), 'interval': scan_interval}

    return app


app = create_app()
