"""Extract recorded facts; never infer simulation statistics from issued orders."""
import hashlib
import io
import zstandard
import json
import math
import re
from pathlib import Path
from .roster import exclusion_reason

from fafreplay import Parser, body_offset, body_ticks, commands, extract_scfa as library_extract_scfa

RESULT = re.compile(r"^GpgNetSend with command 'GameResult' and data '(\d+),(victory|defeat|draw)\b")
STATS_PREFIX = "GpgNetSend with command 'JsonStats' and data '"
# Bump when changing extracted facts so unchanged replay files are reprocessed.
PARSER_VERSION = 4
METRICS = {
    'score': ('general', 'score'),
    'reclaim': ('resources', 'massin', 'reclaimed'),
    'mass': ('resources', 'massin', 'total'),
    'energy': ('resources', 'energyin', 'total'),
    'experimentals': ('units', 'experimental', 'built'),
    'mass_spent': ('resources', 'massout', 'total'),
    'mass_wasted': ('resources', 'massout', 'excess'),
    'kills_mass': ('general', 'kills', 'mass'),
}


def extract_scfa(stream):
    """Decode vault frames without requiring an embedded decompressed size."""
    raw = stream.read()
    header, payload = raw.split(b'\n', 1)
    version = json.loads(header).get('version', 1)
    if version == 1:
        return library_extract_scfa(io.BytesIO(raw))
    if version != 2:
        raise ValueError(f'Unsupported FAF replay version: {version}')
    if not payload:
        raise ValueError('Empty Zstandard replay payload.')
    parts = []
    while payload:
        decoder = zstandard.ZstdDecompressor().decompressobj()
        parts.append(decoder.decompress(payload))
        if not decoder.eof:
            raise ValueError('Incomplete Zstandard replay frame.')
        payload = decoder.unused_data
    return b''.join(parts)


def decode(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value)


def number_at(obj, keys):
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    if isinstance(obj, (int, float)) and not isinstance(obj, bool) and math.isfinite(obj) and obj >= 0:
        return obj
    return None


def roster_from_header(header):
    players = []
    for index, army in sorted(header['armies'].items()):
        if not army.get('Human') or army.get('Civilian') or index == 255:
            continue
        team = int(army.get('Team', 1))
        # A missing FAF ID is anonymous, never a display-name identity.
        ident = decode(army['OwnerID']) if army.get('OwnerID') else f'anonymous-army-{index}'
        players.append(dict(id=ident,
                            name=decode(army['PlayerName']), army=index + 1,
                            team=str(team) if team > 1 else f'ffa-{index}',
                            faction=int(army.get('Faction', 0))))
    return players


def extract_facts(header, events, metadata, duration):
    players = roster_from_header(header)
    snapshots, results, warnings = {}, {}, []
    for event in events:
        if event.get('func') != 'ModeratorEvent':
            continue
        message = decode(event.get('args', {}).get('Message', ''))
        match = RESULT.match(message)
        if match:
            results.setdefault(int(match[1]), set()).add(match[2])
        if message.startswith(STATS_PREFIX):
            try:
                payload, _ = json.JSONDecoder().raw_decode(message[len(STATS_PREFIX):])
                for stat in payload['stats']:
                    name = stat['name']
                    tick = number_at(stat, ('general', 'lastupdatetick'))
                    if tick is not None and tick >= snapshots.get(name, {}).get('general', {}).get('lastupdatetick', -1):
                        snapshots[name] = stat
            except (ValueError, KeyError, TypeError):
                warnings.append('An invalid JsonStats snapshot was skipped.')
    winning_teams = {p['team'] for p in players if 'victory' in results.get(p['army'], set())}
    teams = {p['team'] for p in players}
    locked = decode(header.get('scenario', {}).get('Options', {}).get('TeamLock', 'locked')) == 'locked'
    resolved = len(winning_teams) == 1 and len(teams) > 1 and locked
    if len(winning_teams) > 1:
        warnings.append('Conflicting winning teams: outcome excluded from win statistics.')
    if not locked:
        warnings.append('Unlocked teams: starting-team win statistics are unavailable.')
    draw = bool(players) and all(results.get(p['army']) == {'draw'} for p in players)
    for p in players:
        p['result'] = ('win' if p['team'] in winning_teams else 'loss') if resolved else ('draw' if draw else 'unknown')
        p['reported_result'] = ', '.join(sorted(results.get(p['army'], []))) or None
        stat = snapshots.get(p['name'], {})
        p.update({key: number_at(stat, path) for key, path in METRICS.items()})
        p['stats_tick'] = number_at(stat, ('general', 'lastupdatetick'))
    return dict(id=str(metadata.get('uid') or ''), title=metadata.get('title') or 'Local replay',
                map=metadata.get('mapname') or header.get('map_file', 'Unknown map'),
                played_at=metadata.get('launched_at'), duration=duration,
                outcome='resolved' if resolved else ('draw' if draw else 'unknown'),
                winner=next(iter(winning_teams)) if resolved else None,
                warnings=sorted(set(warnings)), players=players)


class ExcludedReplay(Exception):
    def __init__(self, reason, players, game_id):
        super().__init__(reason)
        self.players, self.game_id = players, game_id


def parse_replay(path: Path, policy=None):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if path.suffix.lower() == '.fafreplay':
        metadata = json.loads(raw.split(b'\n', 1)[0])
        with path.open('rb') as stream:
            data = extract_scfa(stream)
    else:
        metadata, data = {}, raw
    offset = body_offset(data)
    header = Parser().parse_header(data[:offset])
    players = roster_from_header(header)
    if policy is not None:
        reason = exclusion_reason(players, policy)
        if reason:
            raise ExcludedReplay(reason, players, str(metadata.get('uid') or digest))
    replay = Parser(commands=[commands.LuaSimCallback], save_commands=True).parse(data)
    duration = body_ticks(data[body_offset(data):]) / 10
    result = extract_facts(replay['header'], replay['body']['commands'], metadata, duration)
    result['id'] = result['id'] or digest
    result['filename'] = path.name
    result['sha256'] = digest
    return result
