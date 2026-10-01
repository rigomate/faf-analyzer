import json
import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.parser import extract_facts, parse_replay
from app.scanner import Scanner
from app.stats import summarize
from app.store import Store

REPLAYS = Path(__file__).resolve().parents[1] / 'replays'


def callback(message):
    return {'func': 'ModeratorEvent', 'args': {'Message': message.encode()}}


def result(army, outcome):
    return callback(f"GpgNetSend with command 'GameResult' and data '{army},{outcome} 10,'")


def header():
    return {'armies': {0: {'Human': True, 'PlayerName': b'A', 'OwnerID': b'1', 'Team': 2},
                       1: {'Human': True, 'PlayerName': b'B', 'OwnerID': b'2', 'Team': 2},
                       2: {'Human': True, 'PlayerName': b'C', 'OwnerID': b'3', 'Team': 3},
                       255: {'Human': False, 'PlayerName': b'civilian'}}}


def test_team_victory_includes_eliminated_teammate():
    g = extract_facts(header(), [result(1, 'defeat'), result(2, 'victory'), result(3, 'defeat')], {}, 100)
    assert [p['result'] for p in g['players']] == ['win', 'win', 'loss']
    assert g['players'][0]['reported_result'] == 'defeat'
    assert g['players'][0]['mass'] is None


def test_no_winner_is_not_a_loss_and_conflicts_not_guessed():
    for events in [[], [result(1, 'defeat')], [result(1, 'victory'), result(3, 'victory')]]:
        g = extract_facts(header(), events, {}, 100)
        assert g['outcome'] == 'unknown'
        assert all(p['result'] == 'unknown' for p in g['players'])
    h = header()
    h['scenario'] = {'Options': {'TeamLock': b'unlocked'}}
    assert extract_facts(h, [result(1, 'victory')], {}, 100)['outcome'] == 'unknown'


def test_snapshots_are_latest_per_player_not_summed():
    def snap(tick, mass):
        return callback("GpgNetSend with command 'JsonStats' and data '" + json.dumps({'stats':[
            {'name':'A', 'general':{'lastupdatetick':tick, 'score':mass*2}, 'resources':{'massin':{'total':mass,'reclaimed':0}},
             'units':{'experimental':{'built':2}}}]}) + "'")
    g = extract_facts(header(), [snap(100, 500), snap(300, 900), snap(100, 500), result(1, "victory")], {}, 100)
    a, b, _ = g['players']
    assert a['mass'] == 900 and a['experimentals'] == 2 and a['reclaim'] == 0
    assert a['score'] == 1800
    assert b['mass'] is None and b['score'] is None
    d = summarize([g])
    assert next(p for p in d['players'] if p['id']=='1')['metrics']['mass']['samples'] == 1
    assert d['pairs'][0]['decided'] == 1


def test_ffa_players_not_teammates():
    h = header()
    for a in h['armies'].values():
        a['Team'] = 1
    g = extract_facts(h, [result(1,'victory')], {}, 100)
    assert len({p['team'] for p in g['players']}) == 3
    assert summarize([g])['pairs'] == []


@pytest.mark.skipif(not (REPLAYS / '27726302-rigomate.fafreplay').exists(), reason='Sample replays not installed')
def test_real_replay_stats_and_team_result():
    g = parse_replay(REPLAYS / '27726302-rigomate.fafreplay')
    assert g['duration'] == 3040.4
    rigomate = next(p for p in g['players'] if p['name']=='rigomate')
    assert rigomate['result'] == 'win' and rigomate['reported_result'] == 'defeat'
    assert all(p['stats_tick'] is not None for p in g['players'])


@pytest.mark.skipif(not REPLAYS.exists(), reason='Sample replays not installed')
def test_import_is_idempotent_and_preserves_missing_data(tmp_path):
    config = tmp_path/'friends.json'
    policy = json.loads((REPLAYS.parent/'config/friends.json').read_text())
    policy['min_friends'] = 1  # This historical parser fixture includes a solo replay.
    config.write_text(json.dumps(policy))
    store = Store(tmp_path/'db.sqlite3', config)
    samples = tmp_path/'original-samples'
    samples.mkdir()
    for replay_id in ['27725732','27726302','27765261','27765952','27802228','27802810','27838450','27838982','27875183','27875668','27875677','27875681','27875731']:
        shutil.copyfile(REPLAYS/f'{replay_id}-rigomate.fafreplay', samples/f'{replay_id}.fafreplay')
    scanner = Scanner(store, samples, 0)
    scanner.scan()
    first = store.files()
    scanner.scan()
    assert store.files() == first
    assert all(f['status']=='imported' for f in first)
    d = summarize(store.games())
    assert d['totals'] == {'games':10, 'players':11, 'decided':10, 'stats_games':9}
    missing = next(g for g in store.games() if g['id']=='27765261')
    assert all(p['mass'] is None for p in missing['players'])
    assert len(missing['players']) == 8  # Outer metadata incorrectly says seven.


@pytest.mark.skipif(not REPLAYS.exists(), reason='Sample replays not installed')
def test_duplicate_corrupt_recovery_and_settling(tmp_path):
    folder = tmp_path/'replays';folder.mkdir()
    source = REPLAYS/'27726302-rigomate.fafreplay'
    a, b = folder/'a.fafreplay', folder/'b.fafreplay'
    shutil.copyfile(source,a);shutil.copyfile(source,b)
    bad = folder/'bad.fafreplay';bad.write_bytes(b'not a replay')
    store=Store(tmp_path/'db.sqlite3');scanner=Scanner(store,folder,10)
    scanner.scan()
    assert store.games()==[]  # Active/recent copies are deferred.
    for p in folder.iterdir():os.utime(p,(time.time()-20,time.time()-20))
    scanner.scan()
    assert len(store.games())==1
    assert len([f for f in store.files() if f['status']=='error'])==1
    shutil.copyfile(REPLAYS/'27725732-rigomate.fafreplay',bad)
    os.utime(bad,(time.time()-20,time.time()-20));scanner.scan()
    assert len(store.games())==2
    assert all(f['status']=='imported' for f in store.files())


def test_http_empty_filter_validation_and_missing_game(tmp_path):
    folder=tmp_path/'replays';folder.mkdir()
    app=create_app(tmp_path/'db.sqlite3',folder,5)
    with TestClient(app) as client:
        assert client.get('/').status_code==200
        assert client.get('/static/app.js').status_code==200
        assert client.get('/healthz').json()=={'status':'ok'}
        assert client.get('/api/dashboard?player=missing').json()['totals']['games']==0
        assert client.get('/api/dashboard?minimum=0').status_code==422
        assert client.get('/api/games/missing').status_code==404
        assert client.get('/api/status').json()['interval']==5


@pytest.mark.skipif(not REPLAYS.exists(), reason='Sample replays not installed')
def test_background_scanner_picks_up_new_file_after_startup(tmp_path):
    folder=tmp_path/'replays';folder.mkdir()
    app=create_app(tmp_path/'db.sqlite3',folder,5)
    with TestClient(app) as client:
        deadline=time.monotonic()+3
        while app.state.scanner.last_scan is None and time.monotonic()<deadline:
            time.sleep(.05)
        assert client.get('/api/dashboard').json()['totals']['games']==0
        replay=folder/'new.fafreplay'
        shutil.copyfile(REPLAYS/'27726302-rigomate.fafreplay',replay)
        os.utime(replay,(time.time()-20,time.time()-20))
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if client.get('/api/dashboard').json()['totals']['games']==1:
                break
            time.sleep(.1)
        assert client.get('/api/dashboard').json()['totals']['games']==1
        assert client.get('/api/dashboard?player=303498').json()['totals']['games']==1
        assert client.get('/api/dashboard?player=absent').json()['totals']['games']==0


@pytest.mark.skipif(not REPLAYS.exists(), reason='Sample replays not installed')
def test_existing_import_is_backfilled_after_parser_upgrade(tmp_path):
    folder = tmp_path/'replays'
    folder.mkdir()
    replay = folder/'sample.fafreplay'
    shutil.copyfile(REPLAYS/'27726302-rigomate.fafreplay', replay)
    store = Store(tmp_path/'db.sqlite3')
    scanner = Scanner(store, folder, 0)
    scanner.scan()
    game = store.games()[0]
    expected = {p['id']: p.pop('score') for p in game['players']}
    assert any(v is not None for v in expected.values())
    with store.connect() as db:
        db.execute('UPDATE games SET document=?', (json.dumps(game),))
        db.execute('UPDATE files SET signature=?', (f'{replay.stat().st_size}:{replay.stat().st_mtime_ns}',))
    # Archived matches remain readable until their source is processed again.
    old = summarize(store.games())
    assert all(p['metrics']['score']['samples'] == 0 for p in old['players'])
    scanner.scan()
    assert len(store.games()) == 1
    assert {p['id']: p['score'] for p in store.games()[0]['players']} == expected
