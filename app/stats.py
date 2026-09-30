from itertools import combinations
from math import sqrt
from .parser import METRICS


def wilson(wins, n):
    if not n:
        return [0, 1]
    z = 1.96
    center = (wins / n + z*z / (2*n)) / (1 + z*z/n)
    margin = z * sqrt((wins/n * (1-wins/n) + z*z/(4*n))/n) / (1+z*z/n)
    return [max(0, center-margin), min(1, center+margin)]


def statistics_game(game, player_ids):
    """Publish statistics only for friends; preserve full-match outcome and headcount."""
    friends = set(player_ids)
    visible = [p for p in game['players'] if p['id'] in friends]
    return {**game, 'players': visible, 'participant_count': len(game['players']),
            'guest_count': len(game['players']) - len(visible)}


def summarize(games, minimum=2, player_ids=None):
    if player_ids is not None:
        games = [statistics_game(game, player_ids) for game in games]

    players, pairs = {}, {}
    for game in sorted(games, key=lambda g: g.get('played_at') or 0):
        for p in game['players']:
            entry = players.setdefault(p['id'], dict(id=p['id'], name=p['name'], games=0, wins=0, losses=0, draws=0, unknown=0,
                                                    metrics={k: [] for k in METRICS}))
            entry['name'] = p['name']
            entry['games'] += 1
            entry[{'win':'wins', 'loss':'losses', 'draw':'draws', 'unknown':'unknown'}[p['result']]] += 1
            for metric in METRICS:
                if p[metric] is not None:
                    entry['metrics'][metric].append(p[metric])
        for a, b in combinations(game['players'], 2):
            if a['team'] != b['team']:
                continue
            key = tuple(sorted((a['id'], b['id'])))
            pair = pairs.setdefault(key, dict(ids=key, games=0, wins=0, losses=0, unknown=0, draws=0))
            pair['games'] += 1
            pair[{'win':'wins', 'loss':'losses', 'draw':'draws', 'unknown':'unknown'}[a['result']]] += 1
    for p in players.values():
        p['decided'] = p['wins'] + p['losses']
        p['win_rate'] = p['wins']/p['decided'] if p['decided'] else None
        p['metrics'] = {k: dict(total=sum(v) if v else None, average=sum(v)/len(v) if v else None,
                                best=max(v) if v else None, samples=len(v)) for k, v in p['metrics'].items()}
    for pair in pairs.values():
        pair['names'] = [players[i]['name'] for i in pair['ids']]
        n = pair['wins'] + pair['losses']
        pair.update(decided=n, win_rate=pair['wins']/n if n else None,
                    estimate=(pair['wins']+1)/(n+2), interval=wilson(pair['wins'], n), eligible=n >= minimum)
    return dict(players=sorted(players.values(), key=lambda p: (-p['wins'], p['name'])),
                pairs=sorted(pairs.values(), key=lambda p: (-p['interval'][0], -p['decided'], p['names'])),
                games=sorted(games, key=lambda g:g.get('played_at') or 0, reverse=True),
                totals=dict(games=len(games), players=len(players), decided=sum(g['outcome']=='resolved' for g in games),
                            stats_games=sum(any(p['stats_tick'] is not None for p in g['players']) for g in games)))
