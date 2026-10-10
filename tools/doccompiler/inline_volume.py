"""Keep immutable volume indices beside a batch stream; scale operands at load.

No command, wait, waveform, or scaled DOC value changes. This trades hot RAM
for removing volume decoding from the IRQ. The complete hot head must fit.
"""
import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path
import unit2

FINAL = 0x5a0


def positions(data):
    assert data[21] & 3 == 3
    p = unit2.STREAM
    while data[p] != 0xe0:
        assert data[p] > 0xd0 and data[p] & 15
        p += 1
        count = data[p]; p += 1
        for _ in range(count):
            reg = data[p]; p += 1
            if reg < 224:
                n = 2
            else:
                assert reg == 224
                index = data[p]; p += 1
                if index == 255:
                    reg, n = data[p:p+2]; p += 2
                else:
                    reg, n = data[0x100+index], data[0x200+index]
            if reg & 224 == 64:
                for i in range(n):
                    yield p+i, (reg+i) & 31
            p += n
    assert p + 1 == unit2.STREAM + int.from_bytes(data[6:8], 'little')


def compile(data):
    assert not data[21] & 4
    oldwave = int.from_bytes(data[8:10], 'little')
    assert oldwave == unit2.STREAM + int.from_bytes(data[6:8], 'little')
    backup = bytes(data[pos] for pos, _ in positions(data))
    head = bytearray(data[:oldwave] + backup)
    if len(head) > 65535:
        raise ValueError('inline volume backup exceeds the hot bank')
    head[21] |= 4
    struct.pack_into('<H', head, 22, oldwave)
    struct.pack_into('<H', head, 8, len(head))
    head[FINAL:FINAL+32] = bytes([127]*32)
    for pos, osc in positions(data):
        head[FINAL+osc] = data[pos]
    return bytes(head) + data[oldwave:]


def prepare(data, master=15, cursor=0):
    """Independent oracle for assembly rescaling and cached held levels."""
    u = bytearray(data)
    u[unit2.LEVEL:unit2.LEVEL+32] = u[FINAL:FINAL+32]
    shift = round(8 * __import__('math').log2(15 / master)) if master else 128
    ptr = int.from_bytes(u[22:24], 'little')
    for pos, osc in positions(data):
        lev = data[ptr]; ptr += 1
        u[pos] = unit2.volume(lev + shift)
        if pos < unit2.STREAM + cursor:
            u[unit2.LEVEL+osc] = lev
    assert ptr == int.from_bytes(u[8:10], 'little')
    return u
