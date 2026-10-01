"""File-owned admission rules for every active human player on both teams."""
import hashlib
import json
import re
from pathlib import Path


# Friendly aliases for the standard FAF palette, not browser CSS color names.
# Reference: https://github.com/FAForever/fa/blob/develop/lua/GameColors.lua
PLAYER_COLORS = {
    'red': '#e80a0a', 'dark-red': '#901427', 'orange': '#ff873e',
    'brown': '#b76518', 'gold': '#a79602', 'yellow': '#fafa00',
    'light-green': '#9fd802', 'green': '#40bf40', 'dark-green': '#2e8b57',
    'olive': '#2f4f4f', 'light-blue': '#436eee', 'blue': '#2929e1',
    'dark-purple': '#5f01a7', 'purple': '#9161ff', 'cyan': '#66ffcc',
    'aqua': '#66ffcc', 'white': '#ffffff', 'grey': '#616d7e',
    'gray': '#616d7e', 'pink': '#ff88ff', 'fuchsia': '#ff32ff',
}


def normalize_color(value):
    if not isinstance(value, str):
        raise ValueError('Player color must be a supported name or #RRGGBB.')
    value = value.strip().lower()
    if value in PLAYER_COLORS:
        return PLAYER_COLORS[value]
    if re.fullmatch(r'#[0-9a-f]{6}', value):
        return value
    raise ValueError('Unknown player color; use a supported name or #RRGGBB.')


def load_policy(path):
    try:
        document = json.loads(Path(path).read_text())
        if not isinstance(document, dict) or not {'players', 'max_outsiders'} <= set(document) or set(document) - {'players', 'max_outsiders', 'min_friends'}:
            raise ValueError('Expected players, max_outsiders, and optional min_friends keys.')
        limit = document['max_outsiders']
        if type(limit) is not int or limit not in (0, 1):
            raise ValueError('max_outsiders must be 0 or 1.')
        minimum = document.get('min_friends', 1)
        if type(minimum) is not int or not 1 <= minimum <= 200:
            raise ValueError('min_friends must be an integer between 1 and 200.')
        players = document['players']
        if not isinstance(players, list) or len(players) > 200:
            raise ValueError('players must be a list with at most 200 entries.')
        for player in players:
            if not isinstance(player, dict) or not {'id', 'name'} <= set(player) or set(player) - {'id', 'name', 'color'}:
                raise ValueError('Each player needs id and name, with an optional color.')
            if not isinstance(player['id'], str) or not player['id'].isascii() or not player['id'].isdigit() or len(player['id']) > 20:
                raise ValueError('Player IDs must be numeric strings of at most 20 digits.')
            if not isinstance(player['name'], str) or not player['name'].strip() or len(player['name']) > 100:
                raise ValueError('Player names must be nonempty strings of at most 100 characters.')
            if 'color' in player:
                player['color'] = normalize_color(player['color'])
        ids = sorted(p['id'] for p in players)
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate player IDs are not allowed.')
        # Content-derived revision survives restarts and notices atomic file replacements.
        canonical = json.dumps([ids, limit, minimum])
        revision = int(hashlib.sha256(canonical.encode()).hexdigest()[:15], 16)
        return dict(configured=True, player_ids=ids, players=players, max_outsiders=limit, min_friends=minimum, revision=revision, error=None)
    except (OSError, ValueError, TypeError) as exc:
        # Never fall back to old database settings or admit all games on a typo.
        return dict(configured=True, player_ids=[], players=[], max_outsiders=0, min_friends=1, revision=-2,
                    error=f'Friend configuration unavailable or invalid: {exc}')


def exclusion_reason(players, policy):
    if policy.get('error'):
        return 'Friend configuration unavailable or invalid.'
    friends = set(policy['player_ids'])
    outsiders = {p['id']: p['name'] for p in players if p['id'] not in friends}
    if not any(p['id'] in friends for p in players):
        return 'No players from the friend list.'
    count = len({p['id'] for p in players if p['id'] in friends})
    minimum = policy.get('min_friends', 1)
    if count < minimum:
        return f'{count} friends (minimum {minimum}).'
    if len(outsiders) > policy['max_outsiders']:
        return f"{len(outsiders)} outsiders (maximum {policy['max_outsiders']}): " + ', '.join(sorted(outsiders.values()))
    return None
