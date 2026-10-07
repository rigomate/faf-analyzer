"""Experimental predictive Elo, replayed from the full eligible archive by FAF ID."""
from collections import defaultdict, deque
import math
from statistics import fmean, pstdev

INITIAL_ELO = 1000.0
K = 48.0
ELO_SCALE = 500.0
FORM_GAMES = 5
FORM_STRENGTH = 20.0
PERFORMANCE_MULTIPLIER = 6.0
WEIGHT_SCORE = 0.00  # Raw FAF score is deliberately unused.
WEIGHT_KILLS_MASS = 0.46
WEIGHT_MASS_SPENT = 0.38
WEIGHT_RECLAIM = 0.10
WEIGHT_WASTE = -0.06
WASTE_RATIO_SCALE = 1000.0


def recent_form(results):
    return fmean(list(results)[-FORM_GAMES:]) if results else 0.5


def expected_result(effective_a, effective_b):
    """Pre-game probability; the stable logistic avoids exponent overflow."""
    exponent = (effective_b - effective_a) / ELO_SCALE
    small = 10 ** (-abs(exponent))
    return small / (1 + small) if exponent >= 0 else 1 / (1 + small)


def effective_team_rating(members, ratings, histories):
    # Guests have neither persistent ratings nor form, so contribute neutral values.
    elo = fmean(ratings.get(str(p['id']), INITIAL_ELO) for p in members)
    form = fmean(recent_form(histories.get(str(p['id']), ())) for p in members)
    return elo + FORM_STRENGTH * (form - 0.5)


def metric_value(player, metric):
    value = player.get(metric)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return None
    return max(0.0, value)


def performance_scores(players):
    """Log metrics, then population Z scores over both teams (including guests).

    Missing/invalid metrics use the observed transformed match mean, i.e. Z=0.
    If no values are observed, that metric contributes zero for everyone.
    Waste needs both mass_spent and mass_wasted; neither is guessed as zero.
    """
    columns = []
    for metric, weight in (('kills_mass', WEIGHT_KILLS_MASS),
                           ('mass_spent', WEIGHT_MASS_SPENT),
                           ('reclaim', WEIGHT_RECLAIM),
                           ('mass_wasted', WEIGHT_WASTE)):
        values = []
        for player in players:
            value = metric_value(player, metric)
            if metric == 'mass_wasted':
                spent = metric_value(player, 'mass_spent')
                value = (math.log1p(WASTE_RATIO_SCALE * (value / (spent + 1)))
                         if value is not None and spent is not None else None)
            elif value is not None:
                value = math.log1p(value)
            values.append(value)
        observed = [v for v in values if v is not None]
        mean = fmean(observed) if observed else 0.0
        filled = [mean if v is None else v for v in values]
        std = pstdev(filled) if filled else 0.0
        columns.append([weight * (v - mean) / std if std else 0.0 for v in filled])
    return [math.fsum(column[i] for column in columns) for i in range(len(players))]


def valid_timestamp(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def calculate_elo(games, friend_ids):
    friends = {str(i) for i in friend_ids}
    ratings = {i: INITIAL_ELO for i in friends}
    counts = {i: 0 for i in friends}
    histories = {i: deque(maxlen=FORM_GAMES) for i in friends}
    timeline = []
    predictions = {}
    changes = {}
    used = undated = unsupported = unknown = 0
    # Validate dates before sorting; malformed timestamps cannot break public reads.
    dated = []
    for game in games:
        if game.get('outcome') not in {'resolved', 'draw'}:
            unknown += 1
        elif not valid_timestamp(game.get('played_at')):
            undated += 1
        else:
            dated.append(game)
    for game in sorted(dated, key=lambda g: (g['played_at'], str(g['id']))):
        teams = defaultdict(list)
        players = game.get('players') or []
        ids = [str(p.get('id')) for p in players]
        for player in players:
            teams[player.get('team')].append(player)
        if (game['outcome'] != 'resolved' or len(teams) != 2 or None in teams
                or '' in teams or game.get('winner') not in teams
                or len(set(ids)) != len(ids) or any(i in {'', 'None'} for i in ids)):
            unsupported += 1
            continue
        team_a, team_b = teams
        # Prediction uses only pre-game ratings and previous results.
        expected_a = expected_result(effective_team_rating(teams[team_a], ratings, histories),
                                     effective_team_rating(teams[team_b], ratings, histories))
        expected = {team_a: expected_a, team_b: 1 - expected_a}
        predictions[str(game['id'])] = dict(
            probabilities=expected,
            players=[dict(id=i, rating=round(ratings[i], 3), games=counts[i],
                          form=recent_form(histories[i])) for i in sorted(set(ids) & friends)])
        performances = performance_scores(players)
        updates = []
        for player, performance in zip(players, performances):
            ident = str(player['id'])
            if ident in friends:
                actual = int(player['team'] == game['winner'])
                delta = K * (actual - expected[player['team']]) + PERFORMANCE_MULTIPLIER * performance
                updates.append((ident, ratings[ident] + delta, actual))
        # Commit every delta before appending any current-game result to form.
        changes[str(game['id'])] = {
            ident: dict(before=round(ratings[ident], 3), after=round(rating, 3),
                        delta=round(rating - ratings[ident], 3))
            for ident, rating, _ in updates}
        for ident, rating, _ in updates:
            ratings[ident] = rating
            counts[ident] += 1
        for ident, _, actual in updates:
            histories[ident].append(actual)
        timeline.append(dict(id=str(game['id']), played_at=game['played_at'],
                             ratings={i: round(ratings[i], 3) for i in sorted(friends)}))
        used += 1
    return dict(base=INITIAL_ELO, k=K, scale=ELO_SCALE, games=used, history=timeline,
                predictions=predictions,
                changes=changes,
                form_games=FORM_GAMES, form_strength=FORM_STRENGTH,
                performance_multiplier=PERFORMANCE_MULTIPLIER,
                undated_games=undated, unsupported_games=unsupported, unknown_games=unknown,
                players=[dict(id=i, rating=round(ratings[i], 3), games=counts[i],
                              form=recent_form(histories[i]), provisional=counts[i] < 10)
                         for i in sorted(friends)])
