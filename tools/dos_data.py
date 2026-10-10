"""Read and validate supplied DOS assets without executing a DOS program.

This module uses only Python's standard library and has no toolchain, emulator,
host path or build-directory dependency. Chunk layouts are identified before
decoding; different editions must not share implicit picture or sound numbers.
"""
import hashlib
from pathlib import Path
import struct

from game_profile import PROFILES, REQUIRED, profile


def carmack(data):
    if len(data) < 2:
        raise ValueError('truncated Carmack stream')
    size = struct.unpack_from('<H', data)[0]
    if size % 2:
        raise ValueError('odd Carmack output size')
    target, pos, out = size // 2, 2, []
    while len(out) < target:
        if pos + 2 > len(data):
            raise ValueError('truncated Carmack word')
        word = struct.unpack_from('<H', data, pos)[0]
        pos += 2
        tag, count = word >> 8, word & 255
        if tag not in (0xa7, 0xa8):
            out.append(word)
            continue
        if count == 0:
            if pos == len(data):
                raise ValueError('truncated Carmack escape')
            out.append((tag << 8) | data[pos])
            pos += 1
            continue
        needed = 1 if tag == 0xa7 else 2
        if pos + needed > len(data):
            raise ValueError('truncated Carmack reference')
        start = len(out) - data[pos] if needed == 1 else struct.unpack_from('<H', data, pos)[0]
        pos += needed
        if len(out) + count > target or not 0 <= start < len(out):
            raise ValueError('Carmack reference outside output')
        for index in range(count):
            out.append(out[start + index])
    return out


def rlew(words, tag):
    if not words or words[0] % 2:
        raise ValueError('invalid RLEW output size')
    target, out, pos = words[0] // 2, [], 1
    while len(out) < target:
        if pos >= len(words):
            raise ValueError('truncated RLEW stream')
        word = words[pos]
        pos += 1
        if word != tag:
            out.append(word)
            continue
        if pos + 2 > len(words):
            raise ValueError('truncated RLEW run')
        count, value = words[pos:pos + 2]
        pos += 2
        if len(out) + count > target:
            raise ValueError('RLEW run outside output')
        out.extend([value] * count)
    return out


def sprite(page):
    if len(page) < 4:
        raise ValueError('truncated sprite header')
    left, right = struct.unpack_from('<2H', page)
    if not 0 <= left <= right < 64 or 4 + 2 * (right - left + 1) > len(page):
        raise ValueError('sprite bounds')
    offsets = struct.unpack_from('<%dH' % (right - left + 1), page, 4)
    columns = []
    for offset in offsets:
        pos, runs = offset, []
        while True:
            if pos + 2 > len(page):
                raise ValueError('unterminated sprite column')
            end = struct.unpack_from('<H', page, pos)[0]
            pos += 2
            if not end:
                break
            if pos + 4 > len(page):
                raise ValueError('truncated sprite run')
            base, start = struct.unpack_from('<2H', page, pos)
            pos += 4
            # The official mission packs contain runs in descending order.
            # Preserve DOS command order; bounds do not imply sorted runs.
            if start % 2 or end % 2 or not 0 <= start // 2 < end // 2 <= 64:
                raise ValueError('sprite column run')
            start, end = start // 2, end // 2
            base = base if base < 32768 else base - 65536
            if not 0 <= base + start < base + end <= len(page):
                raise ValueError('sprite pixels outside page')
            runs.append((start, end, page[base + start:base + end]))
        columns.append(runs)
    return dict(left=left, right=right, columns=columns)


def huffman(stream, table, size=None):
    # Tile8 has no size prefix. At most seven padding bits follow its symbols.
    if size is not None and not 0 <= size <= 1024 * 1024:
        raise ValueError('Huffman output size outside asset limits')
    if size == 0:
        return b''
    import native_host
    if len(table) == 512 and native_host.library():
        return native_host.huffman(stream, table, size)
    node, out = 254, bytearray()
    for byte in stream:
        for shift in range(8):
            value = table[2 * node + ((byte >> shift) & 1)]
            if value < 256:
                out.append(value)
                node = 254
                if len(out) == size:
                    return bytes(out)
                if len(out) > 1024 * 1024:
                    raise ValueError('Huffman output exceeds asset limits')
            else:
                node = value - 256
                if node >= 255:
                    raise ValueError('Huffman node outside dictionary')
    if size is not None:
        raise ValueError('truncated Huffman stream')
    return bytes(out)


class DosData:
    @classmethod
    def from_files(cls, game, files):
        """Use a resolver's explicit role paths without renaming source files."""
        if set(files) != set(REQUIRED):
            raise ValueError('resolved source files must name all eight container roles')
        data = cls.__new__(cls)
        data.profile = profile(game)
        data.directory = Path(files['MAPHEAD']).parent
        data.files = {}
        for stem in REQUIRED:
            path = Path(files[stem])
            if not path.is_file():
                raise ValueError('missing ' + stem + ' source file: ' + str(path))
            data.files[data.filename(stem).upper()] = path
        return data

    def __init__(self, directory, game='shareware', shared_directory=None):
        self.directory = Path(directory)
        self.profile = profile(game)
        self.files = {}
        required = {self.filename(stem).upper() for stem in REQUIRED}
        directories = [self.directory]
        if shared_directory is not None and Path(shared_directory).resolve() != self.directory.resolve():
            directories.append(Path(shared_directory))
        for folder in directories:
            local_names = set()
            for path in folder.iterdir():
                name = path.name.upper()
                if not path.is_file() or name not in required:
                    continue
                if name in local_names:
                    raise ValueError('ambiguous case-insensitive filename: ' + name)
                local_names.add(name)
                if name in self.files and self.files[name].read_bytes() != path.read_bytes():
                    raise ValueError('different copies of ' + name + ' exist in the input folders')
                self.files.setdefault(name, path)
        missing = [self.filename(stem) for stem in REQUIRED if self.filename(stem).upper() not in self.files]
        if missing:
            raise ValueError(self.profile.title + ' data is incomplete: ' + ', '.join(missing))

    def filename(self, stem):
        return self.profile.files[stem]

    def read(self, stem):
        return self.files[self.filename(stem).upper()].read_bytes()

    def maps(self):
        head, raw = self.read('MAPHEAD'), self.read('GAMEMAPS')
        if len(head) < 2 + 4 * self.profile.floors:
            raise ValueError(self.filename('MAPHEAD') + ': missing map offsets')
        tag = struct.unpack_from('<H', head)[0]
        result = []
        for index in range(self.profile.floors):
            label = self.profile.floor_label(index)
            offset = struct.unpack_from('<I', head, 2 + 4 * index)[0]
            if offset + 38 > len(raw):
                raise ValueError(label + ': missing map header')
            starts = struct.unpack_from('<3I', raw, offset)
            sizes = struct.unpack_from('<3H', raw, offset + 12)
            if struct.unpack_from('<2H', raw, offset + 18) != (64, 64):
                raise ValueError(label + ': expected a 64 by 64 map')
            planes = []
            for start, size in zip(starts, sizes):
                if size < 2 or start + size > len(raw):
                    raise ValueError(label + ': map plane outside file')
                plane = rlew(carmack(raw[start:start + size]), tag)
                if len(plane) != 4096:
                    raise ValueError(label + ': map plane length')
                planes.append(plane)
            name = raw[offset + 22:offset + 38].split(b'\0')[0].decode('cp437')
            result.append(dict(name=name, planes=planes))
        return result

    def vswap(self):
        raw = self.read('VSWAP')
        if len(raw) < 6:
            raise ValueError('truncated VSWAP header')
        count, sprites, sounds = struct.unpack_from('<3H', raw)
        if not 0 < sprites < sounds < count or 6 + count * 6 > len(raw):
            raise ValueError('invalid VSWAP page directory')
        offsets = struct.unpack_from('<%dI' % count, raw, 6)
        lengths = struct.unpack_from('<%dH' % count, raw, 6 + count * 4)
        pages = []
        for index, (offset, length) in enumerate(zip(offsets, lengths)):
            if offset and (offset < 6 + count * 6 or offset + length > len(raw)):
                raise ValueError(f'VSWAP page {index} outside payload')
            page = raw[offset:offset + length] if offset else b''
            if page and index < sprites and len(page) != 4096:
                raise ValueError(f'wall page {index} is not 64 by 64')
            pages.append(page)
        return pages, sprites, sounds

    def graphics(self):
        raw, head, dictionary = self.read('VGAGRAPH'), self.read('VGAHEAD'), self.read('VGADICT')
        if len(dictionary) != 1024 or len(head) < 6 or len(head) % 3:
            raise ValueError('invalid graphics dictionary or directory')
        table = struct.unpack('<512H', dictionary)
        if any(value > 510 for value in table):
            raise ValueError('graphics dictionary node outside table')
        offsets = [int.from_bytes(head[n:n + 3], 'little') for n in range(0, len(head), 3)]
        present = [offset for offset in offsets if offset != 0xffffff]
        if not present or present != sorted(present) or present[-1] != len(raw):
            raise ValueError('graphics offsets do not match payload')
        if offsets[0] != 0 or len(raw) < 4:
            raise ValueError('missing picture dimensions')
        dimensions_size = struct.unpack_from('<I', raw)[0]
        if dimensions_size % 4:
            raise ValueError('invalid picture dimension table')
        pictures = dimensions_size // 4
        layout = (len(offsets) - 1, pictures)
        matches = [item for item in self.profile.layouts if (item['chunks'], item['pictures']) == layout]
        if len(matches) != 1:
            raise ValueError(f'unsupported {self.profile.key} graphics layout: {layout[0]} chunks, {pictures} pictures')
        self.graphics_layout = matches[0]
        chunks = []
        for index, start in enumerate(offsets[:-1]):
            if start == 0xffffff:
                chunks.append(None)
                continue
            end = next(offset for offset in offsets[index + 1:] if offset != 0xffffff)
            chunk = raw[start:end]
            if index == 3 + pictures:
                expanded = huffman(chunk, table)
                tiles, padding = divmod(len(expanded), 64)
                if tiles != self.graphics_layout['tile8_count'] or padding > 7:
                    raise ValueError('unsupported Tile8 layout')
                expanded = expanded[:tiles * 64]
            else:
                if len(chunk) < 4:
                    raise ValueError(f'graphics chunk {index}: missing size')
                expanded = huffman(chunk[4:], table, struct.unpack_from('<I', chunk)[0])
            chunks.append(expanded)
        for index, (width, height) in enumerate(struct.iter_unpack('<2H', chunks[0]), 3):
            if not width or not height or width % 4 or chunks[index] is None or len(chunks[index]) != width * height:
                raise ValueError(f'picture {index}: dimensions do not match pixels')
        return chunks

    def demos(self):
        """Original input packets from the selected graphics layout.

        DOS stores a floor byte, a 16-bit length and one unused header byte.
        A chunk may have trailing allocation bytes beyond the declared length.
        """
        chunks = self.graphics()
        layout = self.graphics_layout
        first = layout['roles']['demo_first']
        count = layout.get('demo_count', 4)
        if first + count > len(chunks):
            raise ValueError('demo range exceeds the selected graphics layout')
        demos = []
        for index in range(first, first + count):
            chunk = chunks[index]
            if chunk is None or len(chunk) < 4:
                raise ValueError(f'demo chunk {index}: missing header')
            length = struct.unpack_from('<H', chunk, 1)[0]
            if not 4 <= length <= len(chunk) or (length - 4) % 3:
                raise ValueError(f'demo chunk {index}: invalid packet length {length}')
            if chunk[0] >= self.profile.floors:
                raise ValueError(f'demo chunk {index}: floor {chunk[0]} is outside the campaign')
            demos.append(dict(chunk=index, mapon=chunk[0], length=length, data=chunk[4:length]))
        return demos

    def audio(self):
        raw, head = self.read('AUDIOT'), self.read('AUDIOHED')
        count = self.profile.sounds * 3 + self.profile.music
        if len(head) != (count + 1) * 4:
            raise ValueError('unsupported ' + self.profile.key + ' audio directory layout')
        offsets = struct.unpack('<%dI' % (count + 1), head)
        if offsets[0] != 0 or offsets[-1] != len(raw) or list(offsets) != sorted(offsets):
            raise ValueError('audio offsets do not match payload')
        return [raw[start:end] for start, end in zip(offsets, offsets[1:])]

    def inspect(self):
        levels, first_map = [], {}
        for index, level in enumerate(self.maps()):
            digest = hashlib.sha256(struct.pack('<8192H', *(level['planes'][0] + level['planes'][1]))).hexdigest()
            row = dict(index=index, label=self.profile.floor_label(index), name=level['name'],
                       plane_sha256=digest, info_codes=sorted(set(level['planes'][1])))
            if digest in first_map:
                row['same_geometry_and_objects_as'] = first_map[digest]
            first_map.setdefault(digest, index)
            levels.append(row)
        pages, sprites, sounds = self.vswap()
        for index in range(sprites, sounds):
            if pages[index]:
                sprite(pages[index])
        chunks = self.graphics()
        audio = self.audio()
        for index, chunk in enumerate(audio[self.profile.sounds * 3:]):
            if len(chunk) < 2:
                raise ValueError(f'song {index}: missing length')
            size = struct.unpack_from('<H', chunk)[0]
            if size % 4 or size + 2 > len(chunk):
                raise ValueError(f'song {index}: invalid IMF length')
        return dict(result='INPUT_STRUCTURE_VALID', profile=self.profile.key,
                    episodes=self.profile.episodes, floors=len(levels),
                    walls=sum(bool(p) for p in pages[:sprites]),
                    sprites=sum(bool(p) for p in pages[sprites:sounds]),
                    graphics_chunks=len(chunks), pictures=len(chunks[0]) // 4,
                    graphics_layout=self.graphics_layout['name'],
                    audio_chunks=len(audio), music=self.profile.music,
                    files={self.filename(stem):dict(bytes=len(self.read(stem)),
                           sha256=hashlib.sha256(self.read(stem)).hexdigest()) for stem in REQUIRED},
                    levels=levels, full_game_runtime_verified=False)


def detect(directory, shared_directory=None):
    names = {path.name.upper() for path in Path(directory).iterdir() if path.is_file()}
    primary = set(names)
    if shared_directory:
        names.update(path.name.upper() for path in Path(shared_directory).iterdir() if path.is_file())
    matches = [key for key, item in PROFILES.items()
               if item.files['MAPHEAD'].upper() in primary and item.files['VSWAP'].upper() in primary
               and all(name.upper() in names for name in item.files.values())]
    if len(matches) != 1:
        raise ValueError('select a profile explicitly: ' + (', '.join(matches) if matches else 'no complete supported data set'))
    return matches[0]
