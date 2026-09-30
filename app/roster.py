"""File-owned admission rules for every active human player on both teams."""
import hashlib
import json
from pathlib import Path


def load_policy(path):
    try:
        document = json.loads(Path(path).read_text())
        if not isinstance(document, dict) or set(document) != {'players', 'max_outsiders'}:
            raise ValueError('Expected players and max_outsiders keys.')
        limit = document['max_outsiders']
        if type(limit) is not int or limit not in (0, 1):
            raise ValueError('max_outsiders must be 0 or 1.')
        players = document['players']
        if not isinstance(players, list) or len(players) > 200:
            raise ValueError('players must be a list with at most 200 entries.')
        for player in players:
            if not isinstance(player, dict) or set(player) != {'id', 'name'}:
                raise ValueError('Each player needs id and name.')
            if not isinstance(player['id'], str) or not player['id'].isascii() or not player['id'].isdigit() or len(player['id']) > 20:
                raise ValueError('Player IDs must be numeric strings of at most 20 digits.')
            if not isinstance(player['name'], str) or not player['name'].strip() or len(player['name']) > 100:
                raise ValueError('Player names must be nonempty strings of at most 100 characters.')
        ids = sorted(p['id'] for p in players)
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate player IDs are not allowed.')
        # Content-derived revision survives restarts and notices atomic file replacements.
        canonical = json.dumps([ids, limit])
        revision = int(hashlib.sha256(canonical.encode()).hexdigest()[:15], 16)
        return dict(configured=True, player_ids=ids, players=players, max_outsiders=limit, revision=revision, error=None)
    except (OSError, ValueError, TypeError) as exc:
        # Never fall back to old database settings or admit all games on a typo.
        return dict(configured=True, player_ids=[], players=[], max_outsiders=0, revision=-2,
                    error=f'Friend configuration unavailable or invalid: {exc}')


def exclusion_reason(players, policy):
    if policy.get('error'):
        return 'Friend configuration unavailable or invalid.'
    friends = set(policy['player_ids'])
    outsiders = {p['id']: p['name'] for p in players if p['id'] not in friends}
    if not any(p['id'] in friends for p in players):
        return 'No players from the friend list.'
    if len(outsiders) > policy['max_outsiders']:
        return f"{len(outsiders)} outsiders (maximum {policy['max_outsiders']}): " + ', '.join(sorted(outsiders.values()))
    return None
