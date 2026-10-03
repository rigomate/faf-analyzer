"""Local team Elo, replayed chronologically from currently eligible matches."""
from collections import defaultdict
import math

BASE = 1000.0
K = 32.0
SCALE = 400.0


def strength(rating):
    return 10 ** ((rating - BASE) / SCALE)


def calculate_elo(games, friend_ids):
    friends = set(friend_ids)
    ratings = {i: BASE for i in friends}
    counts = {i: 0 for i in friends}
    used = undated = unsupported = 0
    ordered = sorted(games, key=lambda g: (g.get('played_at') or 0, str(g['id'])))
    for game in ordered:
        if game.get('outcome') not in {'resolved', 'draw'}:
            continue
        timestamp = game.get('played_at')
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp <= 0:
            undated += 1
            continue
        teams = defaultdict(list)
        for player in game['players']:
            teams[player['team']].append(player)
        if len(teams) < 2 or (game['outcome'] == 'resolved' and game.get('winner') not in teams):
            unsupported += 1
            continue
        # Guests are anonymous neutral participants, never assigned a persistent rating.
        powers = {team: sum(strength(ratings.get(p['id'], BASE)) for p in members)
                  for team, members in teams.items()}
        deltas = {}
        for team in teams:
            change = 0.0
            for other in teams:
                if team == other:
                    continue
                actual = .5
                if game['outcome'] == 'resolved':
                    if team == game['winner']:
                        actual = 1.0
                    elif other == game['winner']:
                        actual = 0.0
                expected = powers[team] / (powers[team] + powers[other])
                change += actual - expected
            deltas[team] = K * change / (len(teams) - 1)
        # Every change uses pre-match ratings, independent of participant order.
        for team, members in teams.items():
            for player in members:
                if player['id'] in friends:
                    ratings[player['id']] += deltas[team]
                    counts[player['id']] += 1
        used += 1
    return dict(base=BASE, k=K, scale=SCALE, games=used,
                undated_games=undated, unsupported_games=unsupported,
                players=[dict(id=i, rating=round(ratings[i], 3), games=counts[i], provisional=counts[i] < 10)
                         for i in sorted(friends)])
