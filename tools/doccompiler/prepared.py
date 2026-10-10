"""Compile register batches to the player's existing prepared-handler format.

The small emitter uses only the 65816 instructions in music_pairs.s. It needs
no host assembler. Every DOC transfer polls BUSY; reset groups retain the
existing 32-NOP service margin. Samples and ordered per-voice writes are exact.
"""
from collections import Counter
import struct
import unit2
import batchcompile


class Code:
    def __init__(self, origin):
        self.origin = origin
        self.data = bytearray()
        self.labels = {}
        self.links = []

    def mark(self, name):
        self.labels[name] = self.origin + len(self.data)

    def emit(self, *values):
        self.data.extend(values)

    def word(self, op, value):
        if not 0 <= value <= 65535:
            raise unit2.HotBankOverflow(value+1)
        self.emit(op, value & 255, value >> 8)

    def jump(self, name):
        self.emit(0x4c)
        self.links.append((len(self.data), name))
        self.emit(0, 0)

    def resolve(self):
        if self.origin+len(self.data) > 65535:
            raise unit2.HotBankOverflow(self.origin+len(self.data))
        for at, name in self.links:
            struct.pack_into('<H', self.data, at, self.labels[name])
        return bytes(self.data)

    def ready(self):
        self.emit(0xaf, 0x3c, 0xc0, 0xe0, 0x30, 0xfa)

    def operand(self):
        self.word(0xb9, unit2.STREAM)
        self.emit(0xc8)

    def address(self, reg):
        self.ready()
        self.emit(0xa9, reg, 0x8f, 0x3e, 0xc0, 0xe0)

    def write(self):
        self.emit(0x8f, 0x3d, 0xc0, 0xe0)


def rows(data):
    player = unit2.Player(data, symbolic=True)
    result = []
    while True:
        pos = player.y
        wait = unit2.wait_byte(data, pos)
        _, writes = player.wake()
        groups = batchcompile.batches([(r, v) for r, v in writes if 4 <= r & 31 < 28])
        result.append((pos, wait, groups, player.y == 0))
        if not player.y:
            return result


def compile_rows(header, records, waves, timeline=()):
    state = [127] * 32
    pair_counts = Counter()
    expanded = []
    for pos, wait, groups, end in records:
        output = []
        for reg, values in groups:
            if reg & 224 != 64:
                output.append((reg, tuple(values), None))
                continue
            at = 0
            while at < len(values):
                r = reg + at
                n = min(len(values) - at, 2 - (r & 1))
                state[r & 31:(r & 31) + n] = values[at:at+n]
                pair = tuple(state[r & 30:(r & 30) + 2])
                pair_counts[pair] += 1
                output.append((r, tuple(values[at:at+n]), pair))
                at += n
        expanded.append((pos, wait, output, end))
    pairs = [(127, 127)] + [p for p, _ in pair_counts.most_common() if p != (127, 127)][:127]
    pair_ids = {p: i for i, p in enumerate(pairs)}
    tokens = []
    uses = Counter()
    for pos, wait, groups, end in expanded:
        out = []
        for reg, values, pair in groups:
            if pair is None:
                key = (reg, len(values), 0, ())
                out.append((key, values))
            elif pair in pair_ids:
                key = (reg, len(values), 3, ())
                out.append((key, (pair_ids[pair],)))
            else:
                key = (reg, len(values), 5, ())
                out.append((key, pair))
            uses[key] += 1
        tokens.append((pos, wait, out, end))

    def handler(c, key):
        r, n, kind, literal = key
        c.address(r)
        if kind in (3,4):
            if kind == 4:
                c.emit(0xa9, literal[0])
            else:
                c.operand()
            c.word(0x8d, unit2.LEVEL + (r & 30))
            if kind == 3:
                c.emit(0xaa)
            c.word(0x9c, unit2.LEVEL + (r & 30) + 1)
        elif kind == 5:
            c.operand()
            c.emit(0x09, 128)
            c.word(0x8d, unit2.LEVEL + (r & 30))
            c.operand()
            c.word(0x8d, unit2.LEVEL + (r & 30) + 1)
        for k in range(n):
            if k:
                c.ready()
            if kind == 3:
                c.word(0xbd, 0x280 if (r + k) & 1 else 0x200)
            elif kind == 4:
                c.word(0xad, (0x280 if (r + k) & 1 else 0x200)+literal[0])
            elif kind == 5:
                c.word(0xad, unit2.LEVEL + ((r + k) & 31))
                if not (r + k) & 1:
                    c.emit(0x29, 127)
                c.emit(0xaa)
                c.word(0xbd, unit2.VSCALE)
            elif kind == 1:
                c.emit(0xa9, literal[k])
            else:
                c.operand()
            c.write()
        if r & 224 == 160 and (kind != 1 or any(v & 3 == 3 for v in literal)):
            c.emit(*([0xea] * 32))
        c.jump('next')

    # Each distinct variable group gets a handler. Literal groups compete by
    # bytes saved, including their handler and independent oracle description.
    selected = set(uses)
    literals = Counter((k[0], k[1], 4 if k[2]==3 else 1, tuple(v))
                       for _, _, gs, _ in tokens for k, v in gs if k[2] in (0,3))
    choices = []
    for key, count in literals.items():
        c = Code(0); handler(c, key)
        saving = count * len(key[3]) - len(c.data) - 6 - len(key[3])
        if saving > 0:
            choices.append((saving, key))
    # The extended opcode escape keeps uncommon groups in the same format.
    selected.update(key for _, key in choices)
    counts = Counter()
    encoded = []
    for pos, wait, gs, end in tokens:
        out = []
        for key, values in gs:
            literal = key[:2] + (4 if key[2]==3 else 1, tuple(values))
            if key[2] in (0,3) and literal in selected:
                key, values = literal, ()
            counts[key] += 1
            out.append((key, values))
        encoded.append((pos, wait, out, end))
    keys = sorted(counts, key=lambda k: (-counts[k], k))
    ids = {k: 4+2*i for i, k in enumerate(keys)}
    stream = bytearray()
    source_times = dict((pos, t) for t, pos in timeline)
    new_times = []
    for pos, wait, gs, end in encoded:
        if pos in source_times:
            new_times.append((source_times[pos], len(stream)))
        stream.append(wait)
        for key, values in gs:
            op = ids[key]
            stream.extend((op,) if op < 255 else (255, op & 255, op >> 8))
            stream.extend(values)
        stream.append(2 if end else 0)
    vectors = (unit2.STREAM + len(stream) + 1) & ~1
    body = vectors + 2*(len(keys)+2)
    c = Code(body)
    c.mark('next'); c.operand()
    if len(keys) > 125:
        c.emit(0xc9, 255, 0xf0, 4)
        c.emit(0xaa); c.word(0x7c, vectors)
        c.emit(0xc2, 0x20)
        c.word(0xb9, unit2.STREAM); c.emit(0xc8, 0xc8, 0xaa)
        c.word(0xa9, 0); c.emit(0xe2, 0x20)
        c.word(0x7c, vectors)
    else:
        c.emit(0xaa); c.word(0x7c, vectors)
    c.mark('end'); c.emit(0x6b)
    c.mark('loop'); c.word(0xa0, 0); c.emit(0x6b)
    for i, key in enumerate(keys):
        c.mark('op'+str(i)); handler(c, key)
    code = c.resolve()
    hotlen = body + len(code)
    if hotlen > 65535:
        raise unit2.HotBankOverflow(hotlen)
    hot = bytearray(hotlen)
    hot[:unit2.STREAM] = header[:unit2.STREAM]
    hot[0x100:0x440] = bytes(0x340)
    hot[0x100:0x200] = bytes([127])*256
    for i, (l, r) in enumerate(pairs):
        hot[0x100+i], hot[0x180+i] = l, r
    hot[0x300:0x304] = bytes((0x5c, c.labels['next'] & 255, c.labels['next'] >> 8, 0x3e))
    hot[unit2.STREAM:unit2.STREAM+len(stream)] = stream
    hot[body:hotlen] = code
    for i, label in enumerate(['end', 'loop'] + ['op'+str(i) for i in range(len(keys))]):
        struct.pack_into('<H', hot, vectors+2*i, c.labels[label])
    descriptions = bytearray(2*(len(keys)+2))
    for i, key in enumerate([None, None] + keys):
        struct.pack_into('<H', descriptions, i*2, len(descriptions))
        if i < 2:
            descriptions.append(254-i)
        else:
            r, n, kind, values = key
            descriptions.extend((1, r, n, kind, *values))
    hot[unit2.LEVEL+4:unit2.LEVEL+28] = bytes(24)
    hot[21] = 48 | (64 if len(keys)>125 else 0)
    hot[22:32] = bytes(10)
    hot[31] = 44
    struct.pack_into('<HH', hot, 6, len(stream), hotlen)
    new = bytes(hot) + waves + descriptions
    verify(new, records)
    return new, new_times, dict(prepared=True, handler_bytes=len(code)+4,
        handlers=len(keys), literal_handlers=sum(k[2] in (1,4) for k in keys),
        hot_bytes=hotlen, stream_bytes=len(stream), pair_dictionary=len(pairs))


def verify(data, records):
    """Check symbolic writes and desired volumes through the loop seam.

    Symbolic equality preserves the lookup result at every master setting.
    The independent Player uses opcode descriptions, not emitted code bytes;
    native execution is checked separately by check_compiled_audio.py.
    """
    player = unit2.Player(data, symbolic=True)
    desired = [127]*32
    for _ in range(2):
        for _, wait, groups, end in records:
            ticks, actual = player.wake()
            assert ticks == wait & 15
            expected = []
            for reg, values in groups:
                for i, value in enumerate(values):
                    expected.append((reg+i, value))
                    if reg & 224 == 64:
                        desired[(reg+i) & 31] = value
            actual_voices=[[] for _ in range(32)]
            expected_voices=[[] for _ in range(32)]
            for r,v in actual:actual_voices[r&31].append((r,v))
            for r,v in expected:expected_voices[r&31].append((r,v))
            for osc in range(4, 28):
                assert actual_voices[osc] == expected_voices[osc], 'prepared writes changed'
                even = osc & 30
                cached = player.u[unit2.LEVEL+even]
                value = (player.u[unit2.LEVEL+osc] & 127) if cached & 128 else (
                    player.u[(0x180 if osc & 1 else 0x100)+cached])
                assert value == desired[osc], 'prepared held-volume cache changed'
            assert (player.y == 0) == end


def compile(data, timeline=()):
    offset, length = struct.unpack_from('<HH', data, 8)
    result = compile_rows(data[:unit2.STREAM], rows(data), data[offset:offset+length], timeline)
    return result


def best_rows(header, records, waves, timeline=()):
    """Prefer direct register handlers when they fit; compact pairs otherwise."""
    from pair_templates import compile_rows as paired
    failures = []
    for compiler in (compile_rows, paired):
        try:
            result = compiler(header, records, waves, timeline)
            stored, _ = unit2.storage(result[0])
            # Direct handlers avoid dynamic pair-address/template dispatch.
            # Cold byte count is a capacity limit, not the playback objective.
            return result
        except (unit2.HotBankOverflow, unit2.ColdBankOverflow) as error:
            failures.append(error)
    cold = [error for error in failures if isinstance(error, unit2.ColdBankOverflow)]
    raise min(cold or failures, key=lambda error: error.required_bytes)
