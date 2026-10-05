import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.public import PublicStatistics, TokenBucket
from app.stats import summarize
from test_friend_statistics import mixed_game, write_config


@pytest.fixture
def setup(tmp_path):
    folder=tmp_path/'replays';folder.mkdir()
    config=tmp_path/'friends.json';write_config(config,['1','2','4'])
    app=create_app(tmp_path/'db.sqlite3',folder,config_path=config)
    game=mixed_game()
    game.update(filename='PRIVATE-REPLAY.fafreplay',sha256='PRIVATE-HASH',warnings=['PRIVATE-ERROR'])
    with app.state.store.connect() as db:
        db.execute('INSERT INTO games VALUES (?,?,?)',('123',json.dumps(game),1))
    return app,config,game


def document(response):
    return json.loads(response.body)


def test_cache_reuses_archive_and_serialized_response(setup):
    app,_,_=setup
    service=app.state.statistics
    with patch.object(app.state.store,'games',wraps=app.state.store.games) as games, patch('app.public.summarize',wraps=summarize) as calculate:
        first=service.dashboard()
        for _ in range(20):
            assert service.dashboard().body is first.body
        service.dashboard(minimum=3)
        assert games.call_count==1
        assert calculate.call_count==2
        assert first.headers['cache-control']=='no-store'


def test_cache_invalidates_on_updates_deletes_and_config_changes(setup):
    app,config,game=setup
    service=PublicStatistics(app.state.store,build_burst=100)
    assert document(service.dashboard())['totals']['games']==1
    write_config(config,['1','4'])  # Two outsiders: no longer eligible.
    assert document(service.dashboard())['totals']['games']==0
    config.write_text('broken')
    assert document(service.dashboard())['totals']['players']==0
    write_config(config,['1','2','4'])
    assert document(service.dashboard())['totals']['games']==1
    game['players'][0]['mass']=123
    with app.state.store.connect() as db:
        db.execute('UPDATE games SET document=? WHERE id=?',(json.dumps(game),'123'))
    assert document(service.dashboard())['players'][0]['metrics']['mass']['total']==123
    with app.state.store.connect() as db:
        db.execute('DELETE FROM games WHERE id=?',('123',))
    assert document(service.dashboard())['totals']['games']==0


def test_cache_expiry_entry_and_byte_bounds(setup):
    app,_,_=setup
    now=[0.0]
    service=PublicStatistics(app.state.store,ttl=10,max_entries=2,build_burst=100,clock=lambda:now[0])
    with patch('app.public.summarize',wraps=summarize) as calculate:
        size=len(service.dashboard().body)
        service.max_bytes=2*size
        for minimum in range(3,15):service.dashboard(minimum=minimum)
        assert len(service.entries)<=2 and service.bytes<=2*size
        count=calculate.call_count
        service.dashboard(minimum=14)
        assert calculate.call_count==count
        now[0]=11
        service.dashboard(minimum=14)
        assert calculate.call_count==count+1
    service=PublicStatistics(app.state.store,max_bytes=1)
    assert document(service.dashboard())['totals']['games']==1
    assert not service.entries and service.bytes==0


def test_new_query_budget_does_not_block_cached_reads(setup):
    app,_,_=setup
    now=[0.0]
    service=PublicStatistics(app.state.store,build_rate=1,build_burst=1,clock=lambda:now[0])
    first=service.dashboard()
    for minimum in range(3,20):
        with pytest.raises(HTTPException) as exc:service.dashboard(minimum=minimum)
        assert exc.value.status_code==429 and exc.value.headers['Retry-After']=='1'
    assert service.dashboard().body==first.body
    now[0]=1
    assert document(service.dashboard(minimum=3))['totals']['games']==1


def test_concurrent_rebuilds_are_rejected_without_duplicate_work(setup):
    app,_,_=setup
    entered,release=threading.Event(),threading.Event()
    def slow(*args,**kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return summarize(*args,**kwargs)
    with patch('app.public.summarize',side_effect=slow) as calculate, ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(app.state.statistics.dashboard)
        try:
            assert entered.wait(timeout=3)
            with pytest.raises(HTTPException) as exc:app.state.statistics.dashboard()
            assert exc.value.status_code==503
        finally:
            release.set()
        body=future.result(timeout=3).body
        assert app.state.statistics.dashboard().body==body
        assert calculate.call_count==1


def test_public_responses_hide_private_diagnostics(setup):
    app,config,game=setup
    with app.state.store.connect() as db:
        for index,state in enumerate(['imported','excluded','error']):
            db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?,?)',
                       (f'PRIVATE-FILE-{index}','PRIVATE-SIGNATURE',state,'PRIVATE-ERROR with OUTSIDER-NAME',1,
                        'PRIVATE-ID',0,'[]'))
    app.state.scanner.last_error='PRIVATE-ERROR in /PRIVATE/PATH'
    client=TestClient(app)
    status=client.get('/api/status')
    assert status.json()['counts']=={'imported':1,'excluded':1,'error':1}
    assert status.json()['error'] is True
    for path in ['/api/dashboard','/api/games/123','/api/status','/api/roster']:
        response=client.get(path)
        assert response.status_code==200
        for secret in ['PRIVATE','OUTSIDER-NAME','filename','sha256','signature','checked_at']:
            assert secret not in response.text
    config.unlink()
    roster=client.get('/api/roster').json()
    assert roster['policy']['error'] is True
    assert str(config) not in json.dumps(roster)


def test_global_limit_cannot_be_bypassed_with_forwarded_ip(tmp_path,monkeypatch):
    monkeypatch.setenv('API_RATE_PER_SECOND','1')
    monkeypatch.setenv('API_RATE_BURST','2')
    app=create_app(tmp_path/'db.sqlite3',tmp_path)
    client=TestClient(app)
    assert client.get('/api/roster').status_code==200
    assert client.get('/api/status').status_code==200
    for index in range(5):
        response=client.get('/api/roster',headers={'X-Forwarded-For':f'192.0.2.{index}','Forwarded':f'for=192.0.2.{index}'})
        assert response.status_code==429 and response.headers['Retry-After']=='1'
    assert client.get('/healthz').status_code==200
    assert client.get('/').status_code==200


def test_request_validation_rejects_nonfinite_dates_and_oversized_input(setup):
    client=TestClient(setup[0])
    for value in ['nan','inf','-inf','-1']:
        assert client.get('/api/dashboard',params={'since':value}).status_code==422
    assert client.get('/api/dashboard',params={'player':'x'*101}).status_code==422
    assert client.get('/api/dashboard',params={'extra':'x'*2100}).status_code==414


def test_token_bucket_refills_without_sleep():
    now=[0.0]
    bucket=TokenBucket(2,2,clock=lambda:now[0])
    assert bucket.take() and bucket.take() and not bucket.take()
    now[0]=.5
    assert bucket.take() and not bucket.take()
    now[0]=100
    assert bucket.take() and bucket.take() and not bucket.take()


def test_unknown_results_excluded_and_result_updates_invalidate_cache(setup):
    app, _, game = setup
    service = PublicStatistics(app.state.store, build_burst=100)
    assert document(service.dashboard())['totals']['games'] == 1
    for outcome in ['unknown', None, 'draw', 'resolved']:
        game['outcome'] = outcome
        for player in game['players']:
            player['result'] = 'draw' if outcome == 'draw' else ('win' if outcome == 'resolved' else 'unknown')
        with app.state.store.connect() as db:
            db.execute('UPDATE games SET document=? WHERE id=?', (json.dumps(game), '123'))
        data = document(service.dashboard())
        direct = summarize([game])
        if outcome in ('unknown', None):
            assert data['totals'] == dict(games=0, players=0, decided=0, stats_games=0)
            assert data['players'] == data['pairs'] == data['games'] == []
            assert direct['totals']['games'] == 0
            assert app.state.store.eligible_games() == []
            with pytest.raises(HTTPException) as exc:
                service.game('123')
            assert exc.value.status_code == 404
        else:
            assert data['totals']['games'] == direct['totals']['games'] == 1
            assert document(service.game('123'))['outcome'] == outcome
            assert all(p['metrics']['mass']['samples'] == 1 for p in data['players'])
            if outcome == 'draw':
                assert all(p['win_rate'] is None and p['draws'] == 1 for p in data['players'])


def test_current_elo_uses_all_history_independent_of_date_and_player_filters(setup):
    app,config,game=setup
    game['played_at']=100
    with app.state.store.connect() as db:
        db.execute('UPDATE games SET document=? WHERE id=?',(json.dumps(game),'123'))
    service=PublicStatistics(app.state.store,build_burst=100)
    data=document(service.dashboard())
    assert data['elo']['games']==1
    assert {p['id'] for p in data['elo']['players']}=={'1','2','4'}
    recent=document(service.dashboard(since=200))['elo']
    assert recent == data['elo']
    assert recent['games']==1 and recent['since'] is None
    assert document(service.dashboard(since=200))['totals']['games']==0
    boundary=document(service.dashboard(since=100))['elo']
    assert boundary['games']==1 and boundary['players']==data['elo']['players']
    assert document(service.dashboard())['elo']==data['elo']
    assert document(service.dashboard(since=200))['elo']==recent
    assert document(service.dashboard(player='4'))['elo']==data['elo']
    write_config(config,['1','4'])
    fresh=document(service.dashboard())['elo']
    assert fresh['games']==0 and all(p['rating']==1000 for p in fresh['players'])


def test_replay_endpoint_lists_only_currently_used_sanitized_games(setup):
    app,config,game=setup
    with TestClient(app) as client:
        response=client.get('/api/replay')
        assert response.status_code==200
        data=response.json()
        assert data['count']==1 and data['replays'][0]['id']=='123'
        assert {p['id'] for p in data['replays'][0]['players']}=={'1','2','4'}
        assert 'PRIVATE-' not in response.text
        assert response.headers['cache-control']=='no-store'
        assert client.get('/api/replay').json()==data
        game['outcome']='unknown'
        with app.state.store.connect() as db:
            db.execute('UPDATE games SET document=? WHERE id=?',(json.dumps(game),'123'))
        assert client.get('/api/replay').json()=={'count':0,'replays':[]}
        game['outcome']='resolved'
        with app.state.store.connect() as db:
            db.execute('UPDATE games SET document=? WHERE id=?',(json.dumps(game),'123'))
        assert client.get('/api/replay').json()['count']==1
        write_config(config,['1','4'])
        assert client.get('/api/replay').json()['count']==0
