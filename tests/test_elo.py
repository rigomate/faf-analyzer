from copy import deepcopy
import pytest
from app.elo import calculate_elo


def game(ident='1', winner='a', timestamp=100, teams=(('1','2'),('3','4'))):
    return dict(id=ident, played_at=timestamp, outcome='draw' if winner is None else 'resolved', winner=winner,
                players=[dict(id=i,team=t) for t,members in zip(('a','b','c'),teams) for i in members])


def ratings(data):
    return {p['id']:p['rating'] for p in data['players']}


def test_equal_teams_simultaneous_updates_and_draw():
    result=calculate_elo([game()],['1','2','3','4'])
    assert ratings(result)=={'1':1016,'2':1016,'3':984,'4':984}
    assert all(p['games']==1 for p in result['players'])
    assert set(ratings(calculate_elo([game(winner=None)],['1','2','3','4'])).values())=={1000}


def test_chronology_not_import_order_and_underdog_reward():
    first=game();second=game('2',winner='b',timestamp=200)
    forward=calculate_elo([first,second],['1','2','3','4'])
    assert forward==calculate_elo([second,first],['1','2','3','4'])
    assert ratings(forward)['3']>1000  # Upset recovers more than initial loss.
    shuffled=deepcopy(first);shuffled['players'].reverse()
    assert calculate_elo([first],['1','2','3','4'])==calculate_elo([shuffled],['1','2','3','4'])


def test_uneven_teams_guest_neutral_and_no_guest_rating():
    result=calculate_elo([game(teams=(('1',),('2','guest')))],['1','2','new'])
    assert ratings(result)['1']==pytest.approx(1000+32*2/3,abs=.001)
    assert ratings(result)['2']==pytest.approx(1000-32*2/3,abs=.001)
    assert ratings(result)['new']==1000
    assert 'guest' not in ratings(result)


def test_unknown_undated_and_invalid_teams_do_not_change_rating():
    unknown=game();unknown['outcome']='unknown'
    result=calculate_elo([unknown,game(timestamp=None),game(teams=(('1',),))],['1'])
    assert ratings(result)=={'1':1000}
    assert result['games']==0 and result['undated_games']==1 and result['unsupported_games']==1


def test_multiteam_win_and_draw():
    teams=(('1',),('2',),('3',))
    assert ratings(calculate_elo([game(teams=teams)],['1','2','3']))=={'1':1016,'2':992,'3':992}
    assert set(ratings(calculate_elo([game(teams=teams,winner=None)],['1','2','3'])).values())=={1000}
