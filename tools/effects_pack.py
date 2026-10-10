"""Prepared native effect samples, independent of the synthesizer installation."""
import hashlib
import math
from pathlib import Path

from game_profile import fields, integer, number, profile, read_toml
from music_pack import pack_file

DOC_RATE = 894886/34


class EffectsPack:
    def __init__(self, path, game='shareware'):
        game = profile(game)
        path = Path(path)
        manifest = path/'pack.toml' if path.is_dir() else path
        doc = read_toml(manifest)
        fields(doc, ('format', 'catalog', 'effects'), 'effects pack')
        if doc['format'] != 1 or doc['catalog'] != game.document['engine']:
            raise ValueError('effects pack format/catalog differs from the selected game')
        self.rows = []
        seen = set()
        for item in doc['effects']:
            fields(item, ('id', 'name', 'file', 'sha256', 'rate', 'table_bytes', 'volume', 'priority'), 'effect')
            sid = item['id']
            integer(sid, 0, game.sounds-1, 'effect.id')
            if sid in seen:
                raise ValueError('duplicate effect ID')
            seen.add(sid)
            size = item['table_bytes']
            if size not in (256,512,1024,2048,4096):
                raise ValueError('effect table_bytes must be 256, 512, 1024, 2048 or 4096')
            payload = pack_file(manifest.parent, item['file']).read_bytes()
            if not payload or len(payload)>size or payload[-1]!=0 or 0 in payload[:-1]:
                raise ValueError('effect PCM must fit its table and contain only its final zero terminator')
            if hashlib.sha256(payload).hexdigest() != item['sha256']:
                raise ValueError('effect PCM hash differs from manifest')
            # Small tables can contain repeated cycles and legitimately use
            # a rate above the DAC clock. The encoded FC is the real limit.
            number(item['rate'], 1, DOC_RATE*65535/(65536/(size//256)), 'effect.rate')
            integer(item['volume'], 1, 255, 'effect.volume')
            integer(item['priority'], 0, 65535, 'effect.priority')
            code = (size//256).bit_length()-1
            fc = round(item['rate']*(65536/(size//256))/DOC_RATE)
            integer(fc, 1, 65535, 'effect frequency word')
            self.rows.append(dict(id=sid, name=item['name'], samples=list(payload[:-1]),
                                  pages=size//256, size_code=code, fc=fc,
                                  rate=DOC_RATE*fc/(65536/(size//256)), level=item['volume'],
                                  priority=item['priority']))
        if seen != set(range(game.sounds)):
            raise ValueError('effects pack must cover every effect ID in the selected catalog')
        self.rows.sort(key=lambda row: row['id'])
