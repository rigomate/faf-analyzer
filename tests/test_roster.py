import json
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.parser import ExcludedReplay, parse_replay, roster_from_header
from app.roster import exclusion_reason, load_policy
from app.scanner import Scanner
from app.store import Store

REPLAY = Path(__file__).resolve().parents[1]/'replays/27726302-rigomate.fafreplay'


def policy(ids, guests=0):
    return dict(configured=True, player_ids=ids, max_outsiders=guests, revision=1)


def write_config(path, ids, guests=0, minimum=1):
    document = {'players':[{'id':i, 'name':'Player '+i} for i in ids], 'max_outsiders':guests, 'min_friends':minimum}
    replacement = path.with_suffix('.new')
    replacement.write_text(json.dumps(document))
    replacement.replace(path)


def test_all_teams_and_exact_outsider_limit():
    players=[dict(id='1',name='Friend',team='2'),dict(id='2',name='Guest',team='3')]
    assert exclusion_reason(players,policy(['1'])) == '1 outsiders (maximum 0): Guest'
    assert exclusion_reason(players,policy(['1'],1)) is None
    assert exclusion_reason(players+[dict(id='3',name='Guest2')],policy(['1'],1))
    assert exclusion_reason([dict(id='2',name='Guest')],policy(['1'],1)) == 'No players from the friend list.'
    assert exclusion_reason(players,policy([]))
    assert exclusion_reason([dict(id='1',name='NewNickname')],policy(['1'])) is None


def test_observers_and_ai_do_not_count():
    header={'armies':{0:dict(Human=True,OwnerID=b'1',PlayerName=b'Friend',Team=2),
                      1:dict(Human=False,PlayerName=b'AI'),
                      255:dict(Human=True,Civilian=True,PlayerName=b'civilian')},
            'players':{'Observer':123}}
    players=roster_from_header(header)
    assert [p['id'] for p in players]==['1']
    assert exclusion_reason(players,policy(['1'])) is None


@pytest.mark.skipif(not REPLAY.exists(),reason='Sample replay missing')
def test_rejected_replay_does_not_parse_body():
    from fafreplay import Parser as RealParser
    class HeaderOnlyParser:
        def __init__(self,*args,**kwargs):self.parser=RealParser(*args,**kwargs)
        def parse_header(self,data):return self.parser.parse_header(data)
        def parse(self,data):raise AssertionError('Must not parse the body of an excluded replay')
    with patch('app.parser.Parser',HeaderOnlyParser):
        with pytest.raises(ExcludedReplay) as exc:
            parse_replay(REPLAY,policy(['303498'],1))
    assert len(exc.value.players)==5
    assert '4 outsiders' in str(exc.value)


@pytest.mark.skipif(not REPLAY.exists(),reason='Sample replay missing')
def test_settings_recheck_unchanged_files_and_retroactive_filter(tmp_path):
    folder=tmp_path/'replays';folder.mkdir();shutil.copyfile(REPLAY,folder/REPLAY.name)
    config=tmp_path/'friends.json'
    store=Store(tmp_path/'db.sqlite3',config)
    game=parse_replay(REPLAY)
    ids=[p['id'] for p in game['players']]
    write_config(config,ids[:-1],0)
    scanner=Scanner(store,folder,0);scanner.scan()
    assert store.games()==[]
    assert store.files()[0]['status']=='excluded'
    assert len(store.roster_settings()['players'])==4
    first=store.files();scanner.scan();assert first==store.files()
    write_config(config,ids[:-1],1);scanner.scan()
    assert len(store.eligible_games())==1
    assert store.files()[0]['status']=='imported'
    write_config(config,ids[:-2],1)
    assert store.eligible_games()==[]  # Immediate, even before the scanner runs.
    assert len(store.games())==1  # Existing records are retained without leaking into stats.
    scanner.scan();assert store.files()[0]['status']=='excluded'
    restarted=Store(tmp_path/'db.sqlite3',config)
    assert restarted.policy()['player_ids']==sorted(ids[:-2])
    write_config(config,ids,0);scanner.scan()
    assert len(store.eligible_games())==1


def test_migrates_existing_database_without_losing_games(tmp_path):
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE files (path TEXT PRIMARY KEY, signature TEXT NOT NULL, status TEXT NOT NULL, error TEXT, checked_at REAL NOT NULL, game_id TEXT); CREATE TABLE games (id TEXT PRIMARY KEY, document TEXT NOT NULL, imported_at REAL NOT NULL);')
        db.execute('INSERT INTO files VALUES (?,?,?,?,?,?)',('old.fafreplay','1:2','imported',None,1,'123'))
        db.execute('INSERT INTO games VALUES (?,?,?)',('123',json.dumps({'id':'123','players':[]}),1))
    store=Store(path)
    assert store.files()[0]['policy_revision']==-1
    assert store.games()[0]['id']=='123'
    assert Store(path).files()==store.files()


@pytest.mark.skipif(not REPLAY.exists(),reason='Sample replay missing')
def test_file_policy_filters_details_and_exports_and_api_is_read_only(tmp_path):
    folder=tmp_path/'replays';folder.mkdir()
    config=tmp_path/'friends.json'
    app=create_app(tmp_path/'db.sqlite3',folder,config_path=config)
    game=parse_replay(REPLAY)
    with app.state.store.connect() as db:
        db.execute('INSERT INTO games VALUES (?,?,?)',(game['id'],json.dumps(game),1))
    ids=[p['id'] for p in game['players']]
    write_config(config,ids[:-1],0)
    with TestClient(app) as client:
        for method in ['post','put','patch','delete']:
            assert getattr(client,method)('/api/roster').status_code==405
        assert all(set(spec).issubset({'get','head','options'}) for spec in client.get('/openapi.json').json()['paths'].values())
        assert client.get('/api/dashboard').json()['totals']['games']==0
        assert client.get('/api/games/'+game['id']).status_code==404
        write_config(config,ids[:-1],1)
        assert client.get('/api/dashboard').json()['totals']['games']==1
        assert client.get('/api/games/'+game['id']).status_code==200
        write_config(config,ids[:-1],1,minimum=len(ids))
        assert client.get('/api/dashboard').json()['totals']['games']==0
        assert client.get('/api/games/'+game['id']).status_code==404
        assert client.get('/api/roster').json()['policy']['min_friends']==len(ids)
        write_config(config,ids[:-1],1,minimum=len(ids)-1)
        assert client.get('/api/dashboard').json()['totals']['games']==1
        write_config(config,[],1)
        assert client.get('/api/dashboard').json()['totals']['games']==0
        assert client.get('/api/roster').json()['players']==[]
        assert 'roster-form' not in client.get('/').text


@pytest.mark.parametrize('content', [None, '{', '{}', '{"players":[],"max_outsiders":2}',
                                    '{"players":[],"max_outsiders":true}',
                                    '{"players":[{"id":123,"name":"A"}],"max_outsiders":0}',
                                    '{"players":[{"id":"1","name":"A"},{"id":"1","name":"B"}],"max_outsiders":0}'])
def test_missing_or_invalid_config_fails_closed_and_recovers(tmp_path,content):
    config=tmp_path/'friends.json'
    if content is not None:config.write_text(content)
    store=Store(tmp_path/'db.sqlite3',config)
    assert store.policy()['error']
    assert exclusion_reason([dict(id='1',name='A')],store.policy())
    # Legacy editable settings in SQLite must never override the file.
    with store.connect() as db:
        db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT)')
        db.execute('INSERT INTO settings VALUES (?,?)',('roster',json.dumps(policy(['1']))))
    assert store.policy()['error']
    folder=tmp_path/'replays';folder.mkdir()
    scanner=Scanner(store,folder,0)
    scanner.scan()
    assert scanner.last_error and store.files()==[]
    write_config(config,['1'])
    scanner.scan()
    assert scanner.last_error is None
    assert exclusion_reason([dict(id='1',name='A')],store.policy()) is None
    revision=store.policy()['revision']
    write_config(config,['1'])
    assert store.policy()['revision']==revision


def test_minimum_counts_distinct_friends_across_teams():
    rule = {**policy(['1', '2'], 1), 'min_friends': 2}
    friend = dict(id='1', name='Friend', team='2')
    guest = dict(id='3', name='Guest', team='3')
    assert exclusion_reason([friend], rule)
    assert exclusion_reason([friend, guest], rule)
    assert exclusion_reason([friend, friend, guest], rule)
    assert exclusion_reason([friend, dict(id='2', name='Friend2', team='3'), guest], rule) is None
    assert exclusion_reason([friend, guest], {**rule, 'min_friends': 1}) is None


@pytest.mark.parametrize('minimum', [0, -1, 201, True, 1.5, '2', None])
def test_invalid_minimum_fails_closed(tmp_path, minimum):
    config = tmp_path/'friends.json'
    write_config(config, ['1'], minimum=minimum)
    assert load_policy(config)['error']


def test_legacy_minimum_default_and_revision_change(tmp_path):
    config = tmp_path/'friends.json'
    config.write_text(json.dumps({'players':[{'id':'1', 'name':'Friend'}], 'max_outsiders':1}))
    before = load_policy(config)
    assert before['min_friends'] == 1 and not before['error']
    write_config(config, ['1'], 1, minimum=2)
    after = load_policy(config)
    assert after['revision'] != before['revision']
    assert exclusion_reason([dict(id='1', name='Friend')], after)


@pytest.mark.parametrize('color,expected', [('light-green','#9fd802'), ('yellow','#fafa00'), ('grey','#616d7e'), ('#A1B2C3','#a1b2c3')])
def test_configured_player_colors(tmp_path, color, expected):
    config=tmp_path/'friends.json'
    write_config(config,['1'])
    old=load_policy(config)
    data=json.loads(config.read_text())
    data['players'][0]['color']=color
    config.write_text(json.dumps(data))
    policy=load_policy(config)
    assert policy['error'] is None
    assert policy['players'][0]['color']==expected
    assert policy['revision']==old['revision']  # Display edits need no replay reimport.


@pytest.mark.parametrize('color', ['unknown', '#12345g', 'red;display:none', '\" onmouseover=alert(1)', None, 123])
def test_invalid_player_color_fails_closed(tmp_path, color):
    config=tmp_path/'friends.json'
    config.write_text(json.dumps({'players':[{'id':'1','name':'Friend','color':color}], 'max_outsiders':1}))
    assert load_policy(config)['error']


def test_missing_owner_id_does_not_use_player_name_as_identity():
    header = {'armies': {0: dict(Human=True, PlayerName=b'cassandra', Team=2)}}
    player = roster_from_header(header)[0]
    assert player['id'] == 'anonymous-army-0'
    assert player['name'] == 'cassandra'
    header['armies'][0]['PlayerName'] = b'pjetr'
    assert roster_from_header(header)[0]['id'] == player['id']
