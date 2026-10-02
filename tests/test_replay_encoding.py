import base64
import io
import json
import zlib
from pathlib import Path

import pytest
import zstandard

from app.parser import extract_scfa, parse_replay


def wrapped(payload, version=2):
    return io.BytesIO(json.dumps({'version':version}).encode()+b'\n'+payload)


@pytest.mark.parametrize('content_size', [True, False])
def test_zstd_frames_with_and_without_content_size(content_size):
    source=b'replay commands'*50000
    encoded=zstandard.ZstdCompressor(write_content_size=content_size).compress(source)
    assert extract_scfa(wrapped(encoded))==source
    with pytest.raises(ValueError,match='Incomplete'):
        extract_scfa(wrapped(encoded[:-1]))


def test_multiple_frames_and_legacy_encoding():
    compressor=zstandard.ZstdCompressor(write_content_size=False)
    assert extract_scfa(wrapped(compressor.compress(b'first')+compressor.compress(b'second')))==b'firstsecond'
    source=b'old replay'
    payload=base64.b64encode(len(source).to_bytes(4,'big')+zlib.compress(source))
    assert extract_scfa(wrapped(payload,1))==source


@pytest.mark.parametrize('payload', [b'', b'not zstd'])
def test_invalid_payload_rejected(payload):
    with pytest.raises((ValueError,zstandard.ZstdError)):
        extract_scfa(wrapped(payload))


def test_downloaded_replay_with_unknown_content_size():
    path=Path('replays/20808727.fafreplay')
    if not path.exists():pytest.skip('Optional downloaded replay not installed')
    game=parse_replay(path)
    assert game['id']=='20808727'
    assert game['duration']==6052
    assert [p['id'] for p in game['players']]==['27218']
    assert game['outcome']=='unknown'
    assert game['players'][0]['mass'] is None
