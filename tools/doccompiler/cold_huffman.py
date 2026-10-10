"""WDP3 kind-0 storage, decoded only while a song is loading.

Huffman codes wrap the existing byte-LZ tokens. The native loader keeps the
1,020-byte tree in its sound region and reuses the same DOC upload window.
"""
from collections import Counter
import heapq
import struct


def make_tree(data):
    heap = [(n, v, v) for v, n in sorted(Counter(data).items())]
    if len(heap) == 1:
        value = heap[0][2]
        heap.append((0, (value+1)&255, (value+1)&255))
    heapq.heapify(heap)
    sequence = 256
    while len(heap) > 1:
        left, right = heapq.heappop(heap), heapq.heappop(heap)
        heapq.heappush(heap, (left[0]+right[0], sequence, (left[2], right[2])))
        sequence += 1
    codes, table = {}, bytearray()
    def visit(node, bits=0, depth=0):
        if isinstance(node, int):
            codes[node] = bits, depth
            return 0x8000 | node
        at = len(table)
        table.extend(bytes(4))
        left = visit(node[0], bits*2, depth+1)
        right = visit(node[1], bits*2+1, depth+1)
        struct.pack_into('<HH', table, at, left, right)
        return at
    visit(heap[0][2])
    return bytes(table), codes


def encode(data, codes):
    out, accumulator, bits = bytearray(), 0, 0
    for value in data:
        code, count = codes[value]
        accumulator = (accumulator << count) | code
        bits += count
        while bits >= 8:
            bits -= 8
            out.append(accumulator >> bits)
            accumulator &= (1 << bits)-1
    if bits:
        out.append(accumulator << (8-bits))
    return bytes(out)


class Reader:
    def __init__(self, data, start, end, table, relocated=0):
        if not 4 <= len(table) <= 1020 or len(table) % 4:
            raise ValueError('invalid music Huffman tree size')
        self.data, self.source, self.end, self.table = data, start, end, table
        self.bits = self.buffer = 0
        self.relocated, self.margin = relocated, 65536
        # Validate all branches before following untrusted compressed data.
        visited = set()
        def visit(at):
            if at in visited or at % 4 or at+4 > len(table):
                raise ValueError('invalid music Huffman tree branch')
            visited.add(at)
            for child in struct.unpack_from('<HH', table, at):
                if child & 0x8000:
                    if child & 0x7f00:
                        raise ValueError('invalid music Huffman leaf')
                else:
                    visit(child)
        visit(0)
        if len(visited)*4 != len(table):
            raise ValueError('unreachable music Huffman tree node')

    def byte(self):
        node = 0
        while not node & 0x8000:
            if not self.bits:
                if self.source >= self.end:
                    raise ValueError('truncated music Huffman stream')
                self.buffer = self.data[self.source]
                self.source += 1
                self.bits = 8
            self.bits -= 1
            side = (self.buffer >> self.bits) & 1
            node = struct.unpack_from('<H', self.table, node+side*2)[0]
        return node & 255

    def block(self, length):
        out = bytearray()
        def put(value):
            if len(out) >= self.source+self.relocated:
                raise ValueError('music expansion overwrites unread Huffman input')
            out.append(value)
            self.margin = min(self.margin, self.source+self.relocated-len(out))
        while len(out) < length:
            token = self.byte()
            count = token+1 if token < 128 else (token&127)+3
            if len(out)+count > length:
                raise ValueError('music LZ run exceeds the declared output')
            if token < 128:
                for _ in range(count):
                    put(self.byte())
            else:
                distance = self.byte() | (self.byte() << 8)
                if not 0 < distance <= len(out):
                    raise ValueError('music LZ distance is outside this block')
                for _ in range(count):
                    put(out[-distance])
        return bytes(out)

    def finish(self):
        if self.source != self.end or self.buffer & ((1 << self.bits)-1):
            raise ValueError('extra data after music Huffman stream')


def expand(data):
    start, wave_packed, hot_packed, hot_length, table_size, block, packed, kind = struct.unpack_from('<8H', data, 8)
    if kind != 0 or block not in (1024, 2048) or start < max(block, 32+table_size):
        raise ValueError('invalid WDP3 Huffman window')
    if start+wave_packed != packed or packed+hot_packed != len(data):
        raise ValueError('invalid WDP3 Huffman boundaries')
    table = data[32:32+table_size]
    reader = Reader(data, start, packed, table)
    wave_length = struct.unpack_from('<H', data, 6)[0]
    delta = bytearray()
    while len(delta) < wave_length:
        delta.extend(reader.block(min(block, wave_length-len(delta))))
    reader.finish()
    waves, previous = bytearray(), 0
    for value in delta:
        previous = (previous+value)&255
        waves.append(previous)
    hot_reader = Reader(data, packed, len(data), table, 65536-len(data))
    hot = hot_reader.block(hot_length)
    hot_reader.finish()
    return hot, bytes(waves), min(reader.margin, hot_reader.margin)


def container(hot, waves, base, compress, block):
    delta = bytes((v-(waves[i-1] if i else 0))&255 for i, v in enumerate(waves))
    raw_wave = b''.join(compress(delta[i:i+block]) for i in range(0, len(delta), block))
    raw_hot = compress(hot)
    table, codes = make_tree(raw_wave+raw_hot)
    wave, commands = encode(raw_wave, codes), encode(raw_hot, codes)
    start = max(block, 32+len(table))
    required = start+len(wave)+len(commands)
    if required > 65536:
        return None, required
    header = bytearray(32)
    struct.pack_into('<4s10H', header, 0, b'WDP3', base, len(waves), start, len(wave),
                     len(commands), len(hot), len(table), block, start+len(wave), 0)
    data = bytes(header+table+bytes(start-32-len(table))+wave+commands)
    restored_hot, restored_waves, margin = expand(data)
    assert restored_hot == hot and restored_waves == waves
    return (data, margin), required
