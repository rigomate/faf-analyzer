import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.parser import extract_facts, METRICS
from app.stats import summarize


def mixed_game():
    armies = {i: dict(Human=True, PlayerName=name.encode(), OwnerID=str(i+1).encode(),
                      Team=2 if i<3 else 3)
              for i, name in enumerate(['Friend A','Friend B','Guest','Friend C'])}
    events = [{'func':'ModeratorEvent', 'args':{'Message':b"GpgNetSend with command 'GameResult' and data '3,victory 10,'"}}]
    game = extract_facts({'armies':armies}, events, {'uid':123}, 100)
    for player in game['players']:
        player.update({key: 999999 if player['id']=='3' else 10 for key in METRICS})
        player['stats_tick']=1000
    return game


def write_config(path, ids):
    path.write_text(json.dumps({'max_outsiders':1,'players':[{'id':i,'name':'Friend '+i} for i in ids]}))


def test_guests_never_enter_aggregates_pairs_or_report_statistics():
    game=mixed_game()
    data=summarize([game],player_ids={'1','2','4'})
    assert {p['id'] for p in data['players']}=={'1','2','4'}
    assert data['totals']['players']==3
    assert len(data['pairs'])==1 and set(data['pairs'][0]['ids'])=={'1','2'}
    assert all(p['metrics']['mass']['total']==10 for p in data['players'])
    # A guest's explicit victory still credits their friends' team.
    assert data['pairs'][0]['wins']==1
    report=data['games'][0]
    assert report['participant_count']==4 and report['guest_count']==1
    assert {p['id'] for p in report['players']}=={'1','2','4'}
    assert len(game['players'])==4  # Do not mutate the persisted roster or lose eligibility evidence.
    for player in game['players']:
        if player['id']!='3':player['stats_tick']=None
    assert summarize([game],player_ids={'1','2','4'})['totals']['stats_games']==0
    assert summarize([game],player_ids=set())['players']==[]


def test_http_filters_previously_imported_guests_and_updates_from_file(tmp_path):
    folder=tmp_path/'replays';folder.mkdir()
    config=tmp_path/'friends.json';write_config(config,['1','2','4'])
    app=create_app(tmp_path/'db.sqlite3',folder,config_path=config)
    game=mixed_game()
    with app.state.store.connect() as db:
        db.execute('INSERT INTO games VALUES (?,?,?)',('123',json.dumps(game),1))
        db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?,?)',
                   ('old.fafreplay','sig','imported',None,1,'123',0,json.dumps(game['players'])))
    with TestClient(app) as client:
        for path in ['/api/dashboard','/api/dashboard?player=1','/api/dashboard?minimum=1']:
            data=client.get(path).json()
            assert {p['id'] for p in data['players']}=={'1','2','4'}
            assert all('3' not in pair['ids'] for pair in data['pairs'])
            assert {p['id'] for p in data['games'][0]['players']}=={'1','2','4'}
        assert client.get('/api/dashboard?player=3').json()['totals']['games']==0
        assert {p['id'] for p in client.get('/api/games/123').json()['players']}=={'1','2','4'}
        assert 'roster' not in client.get('/api/status').json()['files'][0]
        # Move the guest into the friend list and a friend out, without reparsing.
        write_config(config,['1','3','4'])
        data=client.get('/api/dashboard').json()
        assert {p['id'] for p in data['players']}=={'1','3','4'}
        assert data['totals']['games']==1
        # Two outsiders means the match is rejected before player filtering.
        write_config(config,['1','4'])
        assert client.get('/api/dashboard').json()['totals']['games']==0
        assert client.get('/api/games/123').status_code==404
