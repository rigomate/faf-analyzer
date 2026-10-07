from copy import deepcopy
import math
from unittest.mock import patch

import pytest
from app.elo import (calculate_elo, effective_team_rating, expected_result,
                     performance_scores, recent_form)


def game(ident='1', winner='a', timestamp=100, teams=(('1', '2'), ('3', '4'))):
    return dict(id=ident, played_at=timestamp, outcome='draw' if winner is None else 'resolved', winner=winner,
                players=[dict(id=i, team=t) for t, members in zip(('a', 'b', 'c'), teams) for i in members])


def ratings(data):
    return {p['id']: p['rating'] for p in data['players']}


def test_history_matches_prefix_ratings_and_carries_absent_friends():
    first = game('1', timestamp=100, teams=(('1',), ('2', 'guest')))
    second = game('2', timestamp=200, teams=(('2',), ('3',)))
    result = calculate_elo([second, game('draw', winner=None), first], ['1', '2', '3'])
    history = result['history']
    assert [(p['id'], p['played_at']) for p in history] == [('1', 100), ('2', 200)]
    assert history[0]['ratings'] == ratings(calculate_elo([first], ['1', '2', '3']))
    assert history[-1]['ratings'] == ratings(result)
    assert history[0]['ratings']['1'] == history[1]['ratings']['1'] == 1024
    assert history[0]['ratings']['3'] == 1000
    assert 'guest' not in history[0]['ratings']


def test_archive_predictions_use_only_pre_match_rating_and_form():
    first = game('1', timestamp=100, teams=(('1',), ('2', 'guest')))
    second = game('2', timestamp=200, teams=(('1',), ('2', 'guest')))
    future = game('3', timestamp=300, winner='b', teams=(('1',), ('2', 'guest')))
    before = calculate_elo([second, first], ['1', '2'])
    after = calculate_elo([future, second, first, game('draw', winner=None)], ['1', '2'])
    assert after['predictions']['1'] == before['predictions']['1']
    assert after['predictions']['2'] == before['predictions']['2']
    assert before['predictions']['1']['probabilities'] == {'a': .5, 'b': .5}
    prediction = before['predictions']['2']
    assert prediction['probabilities']['a'] == pytest.approx(expected_result(1034, 983))
    assert prediction['players'] == [dict(id='1', rating=1024, games=1, form=1),
                                     dict(id='2', rating=976, games=1, form=0)]
    assert 'draw' not in after['predictions']
    # Current-game performance changes the update, but never its prediction.
    second['players'][0]['kills_mass'] = 1e9
    assert calculate_elo([first, second], ['1', '2'])['predictions']['2'] == prediction


def test_replay_changes_include_performance_and_match_historical_ratings():
    first = game('1', timestamp=100, teams=(('1',), ('2', 'guest')))
    second = game('2', timestamp=200, winner='b', teams=(('1',), ('2', 'guest')))
    for p, value in zip(second['players'], (100, 0, 0)):
        p['kills_mass'] = value
    result = calculate_elo([second, first, game('draw', winner=None)], ['1', '2'])
    assert result['changes']['1'] == {
        '1': dict(before=1000, after=1024, delta=24),
        '2': dict(before=1000, after=976, delta=-24)}
    assert 'draw' not in result['changes']
    assert 'guest' not in result['changes']['2']
    for ident, change in result['changes']['2'].items():
        assert change['before'] == result['history'][0]['ratings'][ident]
        assert change['after'] == result['history'][1]['ratings'][ident]
        assert change['delta'] == pytest.approx(change['after'] - change['before'], abs=.001)
    plain = deepcopy(second)
    for p in plain['players']:
        p.pop('kills_mass')
    assert result['changes']['2']['1']['delta'] > calculate_elo([first, plain], ['1', '2'])['changes']['2']['1']['delta']


def test_equal_teams_probability_winner_loser_and_simultaneous_updates():
    assert expected_result(1000, 1000) == .5
    assert expected_result(1000, 1500) == pytest.approx(1 / 11)
    assert expected_result(1000, 1000000) == 0
    first = game()
    result = calculate_elo([first], ['1', '2', '3', '4'])
    assert ratings(result) == {'1': 1024, '2': 1024, '3': 976, '4': 976}
    assert all(p['games'] == 1 for p in result['players'])
    shuffled = deepcopy(first)
    shuffled['players'].reverse()
    assert calculate_elo([shuffled], ['1', '2', '3', '4']) == result


def test_chronology_not_import_order_and_underdog_reward():
    first = game()
    second = game('2', winner='b', timestamp=200)
    forward = calculate_elo([first, second], ['1', '2', '3', '4'])
    assert forward == calculate_elo([second, first], ['1', '2', '3', '4'])
    assert ratings(forward)['3'] > 1000
    second['played_at'] = 100  # Timestamp ties are resolved by game ID.
    assert calculate_elo([first, second], ['1']) == calculate_elo([second, first], ['1'])


def test_recent_form_and_team_average():
    assert recent_form([]) == .5
    assert recent_form([1, 0, 1]) == pytest.approx(2 / 3)
    assert recent_form([0, 1, 1, 1, 1, 1]) == 1
    members = [dict(id='1'), dict(id='2'), dict(id='guest')]
    assert effective_team_rating(members, {'1': 1200, '2': 800}, {'1': [1], '2': [0]}) == 1000
    assert effective_team_rating([dict(id='1')], {'1': 1000}, {'1': [1]}) == 1010


def test_form_is_previous_five_results_without_current_result_leakage():
    games = [game(str(i), winner='a' if i < 6 else 'b', timestamp=i) for i in range(1, 8)]
    with patch('app.elo.expected_result', wraps=expected_result) as predict:
        result = calculate_elo(games, ['1', '2', '3', '4'])
    assert predict.call_args_list[0].args == (1000, 1000)
    assert predict.call_args_list[1].args == (1034, 966)  # 1024+10 vs 976-10.
    player = next(p for p in result['players'] if p['id'] == '1')
    assert player['form'] == .6  # Last five are win, win, win, loss, loss.
    assert player['games'] == 7


def test_current_performance_and_score_never_enter_prediction():
    first = game()
    boosted = deepcopy(first)
    boosted['players'][0].update(kills_mass=1e9, mass_spent=1e9, reclaim=1e9, mass_wasted=0, score=1e99)
    # Give the others observed zero values so the boosted player has a real Z score.
    for p in boosted['players'][1:]:
        p.update(kills_mass=0, mass_spent=0, reclaim=0, mass_wasted=0)
    with patch('app.elo.expected_result', wraps=expected_result) as predict:
        plain = calculate_elo([first], ['1', '2', '3', '4'])
        enhanced = calculate_elo([boosted], ['1', '2', '3', '4'])
    assert [c.args for c in predict.call_args_list] == [(1000, 1000), (1000, 1000)]
    assert ratings(enhanced)['1'] > ratings(plain)['1']
    boosted['players'][0]['score'] = -1e99
    assert calculate_elo([boosted], ['1', '2', '3', '4']) == enhanced


def test_performance_logs_population_z_and_individual_updates():
    # Transformed columns [0,1,2] have mean 1 and population std sqrt(2/3).
    players = [dict(kills_mass=math.expm1(x), mass_spent=math.expm1(x),
                    reclaim=math.expm1(x), mass_wasted=(math.expm1(x)+1)*math.expm1(x)/1000)
               for x in (0, 1, 2)]
    assert performance_scores(players) == pytest.approx([-.88*math.sqrt(1.5), 0, .88*math.sqrt(1.5)])
    match = game(teams=(('1', '2'), ('3',)))
    for p, metrics in zip(match['players'], players):
        p.update(metrics)
    result = ratings(calculate_elo([match], ['1', '2', '3']))
    assert result['1'] == pytest.approx(1024-6*.88*math.sqrt(1.5), abs=.001)
    assert result['2'] == 1024
    assert result['3'] == pytest.approx(976+6*.88*math.sqrt(1.5), abs=.001)


def test_zero_stddev_and_negative_values():
    assert performance_scores([dict(kills_mass=10, mass_spent=20, reclaim=3, mass_wasted=5)]*4) == [0]*4
    assert performance_scores([dict(kills_mass=-1, mass_spent=-2, reclaim=-3, mass_wasted=-4),
                               dict(kills_mass=0, mass_spent=0, reclaim=0, mass_wasted=0)]) == [0, 0]


def test_missing_stats_neutral_imputation_and_population_std():
    assert performance_scores([{}, {}]) == [0, 0]
    assert performance_scores([dict(kills_mass=None, mass_spent=float('nan'), reclaim='bad', mass_wasted=True), {}]) == [0, 0]
    # Missing player receives the log-space mean and contributes to the match population.
    assert performance_scores([dict(kills_mass=0), {}, dict(kills_mass=math.expm1(2))]) == pytest.approx([-.46*math.sqrt(1.5), 0, .46*math.sqrt(1.5)])
    assert performance_scores([dict(mass_wasted=100), dict(mass_wasted=0)]) == [0, 0]  # Unknown denominator.
    assert performance_scores([dict(kills_mass=10), {}]) == [0, 0]


def test_uneven_teams_guest_neutral_and_no_guest_rating_or_form():
    match = game(teams=(('1',), ('2', 'guest')))
    result = calculate_elo([match], ['1', '2', 'new'])
    assert ratings(result) == {'1': 1024, '2': 976, 'new': 1000}
    with patch('app.elo.expected_result', wraps=expected_result) as predict:
        calculate_elo([match, game('2', timestamp=200, teams=(('1',), ('2', 'guest')))], ['1', '2'])
    assert predict.call_args_list[1].args == (1034, 983)  # Guest stays at 1000/form .5.
    assert 'guest' not in ratings(result)
    assert next(p for p in result['players'] if p['id'] == 'new')['form'] == .5


def test_guests_performance_is_included_in_match_normalization():
    match = game(teams=(('1',), ('2', 'guest')))
    for p, value in zip(match['players'], (0, 0, 100)):
        p['kills_mass'] = value
    result = calculate_elo([match], ['1', '2'])
    assert ratings(result)['1'] == pytest.approx(1024-6*.46/math.sqrt(2), abs=.001)
    assert ratings(result)['2'] == pytest.approx(976-6*.46/math.sqrt(2), abs=.001)


def test_faf_id_identity_cassandra_to_pjetr_continuous_rating_form_counts():
    first = game(teams=(('349167',), ('2',)))
    second = game('2', timestamp=200, teams=((349167,), ('2',)))
    first['players'][0]['name'] = 'cassandra'
    second['players'][0]['name'] = 'pjetr'
    second['players'][1]['name'] = 'cassandra'  # A reused name is still a different ID.
    with patch('app.elo.expected_result', wraps=expected_result) as predict:
        result = calculate_elo([first, second], [349167, '349167', '2'])
    assert predict.call_args_list[1].args == (1034, 966)
    assert len(result['players']) == 2
    player = next(p for p in result['players'] if p['id'] == '349167')
    assert player['games'] == 2 and player['form'] == 1
    assert player['rating'] == pytest.approx(1024+48*(1-expected_result(1034, 966)), abs=.001)
    second['players'][0]['name'] = 'cassandra'
    assert calculate_elo([first, second], ['349167', '2']) == result


@pytest.mark.parametrize('timestamp', [None, 0, -1, 'unknown', float('nan'), float('inf'), True])
def test_invalid_dates_are_counted_before_sorting(timestamp):
    result = calculate_elo([game(timestamp=timestamp), game('2')], ['1'])
    assert result['undated_games'] == 1 and result['games'] == 1


@pytest.mark.parametrize('match', [game(winner=None), game(teams=(('1',),)),
                                  game(teams=(('1',), ('2',), ('3',))),
                                  game(winner='missing'), game(teams=(('1',), ('1',)))])
def test_unsupported_layouts_and_draws_explicitly_skipped(match):
    result = calculate_elo([match], ['1', '2', '3'])
    assert set(ratings(result).values()) == {1000}
    assert all(p['form'] == .5 and p['games'] == 0 for p in result['players'])
    assert result['unsupported_games'] == 1 and result['games'] == 0


def test_unknown_result_explicitly_counted():
    match = game()
    match['outcome'] = 'unknown'
    result = calculate_elo([match], ['1'])
    assert ratings(result) == {'1': 1000}
    assert result['unknown_games'] == 1


def test_all_history_including_first_fifty_games_is_replayed():
    result = calculate_elo([game(str(i), timestamp=i) for i in range(1, 61)], ['1'])
    assert result['games'] == 60 and result['players'][0]['games'] == 60
    assert result['players'][0]['rating'] > 1000


@pytest.mark.parametrize('field', ['id', 'team'])
def test_missing_identity_or_team_is_explicitly_unsupported(field):
    match = game()
    del match['players'][0][field]
    result = calculate_elo([match], ['1'])
    assert result['unsupported_games'] == 1 and result['games'] == 0
    assert ratings(result) == {'1': 1000}
