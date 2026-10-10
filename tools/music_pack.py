"""Read prepared music without a synthesizer, ROMs, SoundFonts or native tools."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct

from game_profile import fields, integer, profile, read_toml

ROOT = Path(__file__).resolve().parents[1]


def selected_pack():
    return Path(os.environ.get('WOLF_MUSIC_PACK') or ROOT / 'build/audio/music')


def decode_lz(data, source, end, length, relocated=0, preserve_until=None):
    """Bound the stream and check the loader's in-place unread-input boundary."""
    out = bytearray()
    preserve_until = end if preserve_until is None else preserve_until
    while len(out) < length:
        if source >= end:
            raise ValueError('truncated music LZ token')
        token = data[source]
        source += 1
        count = token + 1 if token < 128 else (token & 127) + 3
        if len(out) + count > length:
            raise ValueError('music LZ run exceeds the declared output')
        if token < 128:
            if source + count > end:
                raise ValueError('truncated music LZ literal')
            # MVN reads then writes each literal. Equal addresses are safe.
            if source < len(out) - relocated:
                raise ValueError('music expansion overwrites unread input')
            out.extend(data[source:source + count])
            source += count
        else:
            if source + 2 > end:
                raise ValueError('truncated music LZ distance')
            distance = struct.unpack_from('<H', data, source)[0]
            source += 2
            if not 0 < distance <= len(out):
                raise ValueError('music LZ distance is outside this block')
            for _ in range(count):
                out.append(out[-distance])
        if source < preserve_until and len(out) > source + relocated:
            raise ValueError('music expansion overwrites unread input')
    return bytes(out), source


def inspect_song(data):
    """Check supported cold/hot formats and existing bank/DOC RAM limits.

    This is a container and memory check, not an audio-quality verdict or an
    execution audit of the prepared 65816 handlers in a WDM2 hot bank.
    """
    if not 32 <= len(data) <= 65536 or data[:4] not in (b'WDP2', b'WDP3'):
        raise ValueError('music must be a WDP2/WDP3 bank of 32..65536 bytes')
    base, wave_length = struct.unpack_from('<2H', data, 4)
    if base % 256 or wave_length % 256 or not 0 < wave_length <= 180 * 256:
        raise ValueError('music waves must use 1..180 whole DOC pages')
    if base < 0x4000 or base + wave_length > 0xf400:
        raise ValueError('music waves overlap effects or the DOC timer area')
    if data[:4] == b'WDP2':
        start, packed, packed_length, hot_length = struct.unpack_from('<4H', data, 8)
        if start != 32 or start + wave_length > packed or packed + packed_length != len(data):
            raise ValueError('invalid WDP2 wave/hot boundaries')
        waves = data[start:start + wave_length]
    else:
        start, wave_packed, packed_length, hot_length, table, block, packed, kind = struct.unpack_from('<8H', data, 8)
        if kind != 2 or table != 0:
            raise ValueError('this player requires WDP3 byte-LZ kind 2, without a Huffman table')
        if block not in (1024, 2048) or not 32 <= start < packed:
            raise ValueError('invalid WDP3 wave window')
        if start + wave_packed != packed or packed + packed_length != len(data):
            raise ValueError('invalid WDP3 wave/hot boundaries')
        delta = bytearray()
        source = start
        while len(delta) < wave_length:
            part, source = decode_lz(data, source, packed, min(block, wave_length - len(delta)),
                                     preserve_until=len(data))
            delta.extend(part)
        if source != packed:
            raise ValueError('extra bytes after the WDP3 wave stream')
        waves = bytearray()
        previous = 0
        for value in delta:
            previous = (previous + value) & 255
            waves.append(previous)
    if not packed_length or not 0x600 < hot_length < 65536:
        raise ValueError('invalid music hot-bank size')
    hot, end = decode_lz(data, packed, len(data), hot_length, relocated=65536 - len(data))
    if end != len(data) or hot[:4] != b'WDM2':
        raise ValueError('music hot bank must contain exactly one WDM2 unit')
    command, command_length, wave_offset, hot_wave_length = struct.unpack_from('<4H', hot, 4)
    if command != 0x600 or not command_length or command + command_length > hot_length:
        raise ValueError('music command stream is outside the hot bank')
    if wave_offset != hot_length or hot_wave_length != wave_length or hot[12] * 256 != base or hot[13] != 24:
        raise ValueError('music cold/hot headers disagree about the player or waves')
    return dict(format='WDM2', cold_format=data[:4].decode('ascii'), bytes=len(data),
                hot_bytes=hot_length, doc_bytes=wave_length, doc_base=base, pages=wave_length // 256,
                hot_sha256=hashlib.sha256(hot).hexdigest(),
                wave_sha256=hashlib.sha256(waves).hexdigest())


def pack_file(directory, filename):
    # A pack is portable as a directory tree, including on Windows. Require
    # forward slashes and keep all referenced files inside that directory.
    if not isinstance(filename, str) or not filename or '\\' in filename or ':' in filename:
        raise ValueError('music file: expected a relative path using forward slashes')
    path = PurePosixPath(filename)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('music file must remain inside its pack folder')
    target = directory.joinpath(*path.parts).resolve()
    try:
        target.relative_to(directory.resolve())
    except ValueError as error:
        raise ValueError('music file must remain inside its pack folder') from error
    return target


@dataclass
class PreparedSong:
    report: dict
    data: bytes
    check: dict


class MusicPack:
    def __init__(self, path, game='shareware'):
        self.profile = profile(game)
        path = Path(path)
        self.manifest = (path / 'pack.toml' if (path / 'pack.toml').is_file() else path / 'manifest.json') if path.is_dir() else path
        directory = self.manifest.parent
        raw = self.manifest.read_bytes()
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        legacy = self.manifest.suffix.lower() == '.json'
        if legacy:
            if self.profile.spear:
                raise ValueError('legacy Wolf music manifests do not identify a Spear music pack; use pack.toml')
            rows = json.loads(raw)
        else:
            doc = read_toml(self.manifest)
            fields(doc, ('format', 'catalog', 'player', 'songs'), 'music pack')
            integer(doc['format'], 1, 1, 'music pack.format')
            if doc['catalog'] != self.profile.document['engine'] or doc['player'] != 'wdm2':
                raise ValueError('music pack catalog/player does not match the selected game')
            rows = doc['songs']
        if not isinstance(rows, list) or not rows:
            raise ValueError('music pack: expected at least one song')
        self.songs = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('music pack: expected song tables')
            if legacy:
                sid = row.get('id')
                integer(sid, 0, self.profile.music - 1, 'music song.id')
                name = row.get('song') or str(row.get('name', '')).removesuffix('_MUS')
                filename = f'song-{sid:02}.bin'
                digest = row.get('cold_sha256')
                if name != self.profile.music_names[sid] or row.get('format') != 'WDM2':
                    raise ValueError('music song name/ID or player format does not match the profile')
                report = dict(row, song=name)
            else:
                fields(row, ('name', 'file', 'sha256'), 'music song')
                name, filename, digest = row['name'], row['file'], row['sha256']
                if not isinstance(name, str) or name not in self.profile.music_names:
                    raise ValueError('music song is not in the selected catalog: ' + str(name))
                sid = self.profile.music_names.index(name)
                report = dict(id=sid, song=name, name=name + '_MUS', format='WDM2', cold_sha256=digest)
            if sid in seen:
                raise ValueError('duplicate music song: ' + name)
            seen.add(sid)
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('music song.sha256: expected 64 lowercase hexadecimal digits')
            asset = pack_file(directory, filename)
            if asset.stat().st_size > 65536:
                raise ValueError(name + ': music bank exceeds 65536 bytes')
            data = asset.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(name + ': music file SHA-256 differs from the manifest')
            try:
                check = inspect_song(data)
            except ValueError as error:
                raise ValueError(name + ': ' + str(error)) from error
            report.update(bytes=len(data), doc_bytes=check['doc_bytes'])
            if sid in self.profile.required_music:
                self.songs.append(PreparedSong(report, data, check))
        missing = self.profile.required_music.keys() - seen
        if missing:
            raise ValueError('music pack is missing songs required by ' + self.profile.key + ': ' +
                             ', '.join(self.profile.required_music[sid] for sid in sorted(missing)))
        self.songs.sort(key=lambda song: song.report['id'])

    def inspect(self):
        return dict(profile=self.profile.key, catalog=self.profile.document['engine'], player='wdm2',
                    manifest_sha256=self.manifest_sha256,
                    required_songs=len(self.profile.required_music),
                    songs=[dict(id=song.report['id'], name=song.report['song'],
                                sha256=song.report['cold_sha256'], **song.check) for song in self.songs],
                    synthesizer_required=False, audio_quality_verified=False,
                    native_playback_verified=False)
