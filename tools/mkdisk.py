#!/usr/bin/env python3
"""Pack bootable 800 KiB floppy sets and hard disk images in ProDOS block order.

The loader reads WOLF.DATA segments by physical block number. Keep payload
blocks contiguous; ProDOS index blocks follow them. Block 0 is the boot code,
block 1 the WOLFGS header, blocks 2-5 the directory and block 6 the bitmap.
WOLF.BOOT has its index at block 7 and its loader bytes at blocks 8-14.
Larger volumes may put the bitmap at the end, leaving the loader fixed.

Every disk header names the home disk and the blocks of WOLF.SETTINGS,
WOLF.SETX, WOLF.MENU and the eight WOLF.SAVE files. On floppies the home disk
is the last boot disk, or disk 2 when boot data fits on disk 1. Disk 1 holds
boot data and is not requested again after boot. Settings and saves must be
written on the home disk. --no-readme omits the optional on-disk text file.

--store supplies the level store. Headers map its logical blocks to physical
runs: first block, count, disk block, disk number and logical block bit 16.
The floor table selects each floor's disks. --disk-units and --campaign give
floppy_layout the load dependencies and routes. A split floor has an episode
part and a floor part; the loader reads the part already in the drive first.
The layout must keep each complete transition within its disk-change bound.

--hd-only keeps the store on disk at a virtual address outside IIgs RAM and
packs at most two ProDOS volumes. --hd names the first volume; a second gets
the numbered companion name. --scsi adds Apple partition-map device images
containing those same volumes.

--picture-file supplies an SHR image and its load address. Its 64 blocks load
in PIC_ORDER: palettes, row selectors, then interlaced pixel rows. --picture
selects the equivalent picture from a WAD lump.
"""

import memmap
from pathlib import Path
import argparse
import datetime
import json
import os
import struct
import sys
import zlib

import b1
import elf

BLOCK = 512
DISK_BLOCKS = 1600
DIR_BLOCKS = (2, 3, 4, 5)       # the volume directory
SAVE_SLOTS = 8                  # WOLF.SAVE0..7 on the home disk
SAVE_DATA = memmap.SAVE_BLOCKS  # checked world bound plus the selected header
SAVE_RESERVE = SAVE_DATA        # the split withholds this many, plus the index
SAVE_COST = SAVE_SLOTS * (SAVE_RESERVE + 1)  # each reserved file plus its index
BITMAP_BLOCK = 6                # the bitmap: blocks 6-7 at most (8192 blocks)
HD_MAX_BLOCKS = 65535           # ProDOS volume block count is a word
HD_FILE_BLOCKS = 32767          # ProDOS file EOF is 24 bits
HD_FREE = 256                   # free blocks on the hard disk volume
APM_PART = 64                   # --scsi: the first block of the partition
LOADER_FIRST = 8                # STAGE2_BLOCK and STAGE2_COUNT of boot.s
LOADER_BLOCKS = 7
DATA_FIRST = LOADER_FIRST + LOADER_BLOCKS
HDR_FLOOR_DISKS = memmap.HDR_FLOOR_DISKS - memmap.HDR   # the disk of each floor
FLOOR_DISKS = memmap.HDR_FLOOR_DISKS_SIZE               #   (a byte each)
HDR_HOME_DISK = memmap.HDR_HOME_DISK - memmap.HDR       # the home disk (bits 0-6);
PLAY_IMAGE = 0x80                                       #   the boot loads the play cache
RUN_BYTES = 8                   # a store run after the header's segments
BOOT_RUN_SLOTS = 8              # header entries a boot disk keeps for its store runs
HDR_BUILD = 432                 # the build ID (4 bytes), the same on all
HDR_SETTINGS = 436              #   disks; the block of WOLF.SETTINGS on
HDR_RESDISKS = 438              #   the home disk; the last disk with data
HDR_STOREBANKS = 439            #   below the store; the banks of the store
HDR_MENU = 440                  # home disk: first block of WOLF.MENU, its blocks
HDR_SAVE = 444                  # home disk: first block of WOLF.SAVE0, and the
HDR_STRIDE = 446                #   stride to the next save file
PIC_ORDER = 448                 # the picture block order
MAX_SEGMENTS = (HDR_FLOOR_DISKS - 16) // RUN_BYTES    # segments and store runs
LOAD_CELLS = 34                 # the cells of the load bar for the load,
                                #   as LOAD_CELLS of src/iigs/loadbar.inc
FWSTATE, FWSTATE_END = memmap.FWSTATE, memmap.FWSTATE_END   # ui_bridge.s keeps a copy of the firmware state here: nothing loads into it
STORE_BANK = 0x42               # first optional RAM-store bank; slow RAM always loads
SEG_PIC = 1
SEG_B1 = 2                      # the segment is the B1 stream of its data
                                #   (tools/b1.py: u16 the length, then B1)
PIC_BLOCKS = 64
SETTINGS_ADDR = memmap.SETTINGS_IN        # SETTINGS_IN of src/iigs/m_config65.s


SETX_ADDR = memmap.SLOT_NAMES            # SlotExt in src/iigs/wolf.scm


def setx_bytes():
    """A valid empty WOLF.SETX: no names, quick slot 255, eight saves.

    Bytes 8-9 are the word sum of bytes 10-511, so the empty block's sum is
    255 + 8.
    """
    img = bytearray(BLOCK)
    img[0:8] = b'WOLFSLT1'
    img[10] = 255
    img[11] = 8
    struct.pack_into('<H', img, 8, sum(img[10:]))
    return bytes(img)

# ProDOS file types and access bits
TYPE_TXT, TYPE_BIN, TYPE_CFG = 0x04, 0x06, 0x5a
READ, WRITE, RENAME, DESTROY = 0x01, 0x02, 0x40, 0x80
INVISIBLE = 0x04                # GS/OS: the Finder does not show the file

README = """Wolfenstein 3D for the Apple IIgs

Disk {n} of {total}

To play, put disk 1 in the 3.5-inch drive and start the IIgs. The game
needs a stock 2.8 MHz IIgs with a 4 MB expansion card. Keep every disk
in this set; loading may ask for another disk. Ten floors and the four
recorded demos load natively. Elevators and the secret floor advance through
the bonus tally. BJ escapes the boss floor, and both ending pages play.

W/S or Up/Down walk, Left/Right turn, A/D strafe, Space uses doors,
F or Control fires, and 1-4 select an owned weapon. - and = choose the
view size. Esc opens the menu. Options changes sound, music and controls.
Mouse X turns and Y walks; button 0 fires and button 1 strafes.
Save Game stores the player, the actors, the doors, the pushwalls, the
maps and the level clock. Save Game and Save Settings write only to disk 1.
"""

README_HD = """Wolfenstein 3D for the Apple IIgs

To play, start the IIgs from this volume. The game needs a stock 2.8 MHz
IIgs with a 4 MB expansion card. Ten floors and four recorded demos load
natively. Elevators and the secret floor advance through the bonus tally;
BJ escapes the boss floor, and both ending pages play. Esc opens the menu.
W/S or Up/Down walk, Left/Right turn, A/D strafe, Space uses doors,
F or Control fires, and 1-4 select an owned weapon. - and = choose the
view size. Options changes sound, music and controls. Mouse X turns and
Y walks; button 0 fires and button 1 strafes. Save Game stores the player,
the actors, the doors, the pushwalls, the maps and the level clock.
Settings and saves use this volume.
"""


def picture_order():
    """The palettes (block 63), the row palettes (62), then the pixel
    blocks: every 8th, the 4th ones between them, the 2nd ones, the rest."""
    order = [63, 62]
    for start, step in ((0, 8), (4, 8), (2, 4), (1, 2)):
        order += [b for b in range(start, 62, step) if b not in order]
    return order


def wad_lump(data, name):
    """The offset of lump name in the WAD bytes data, or None."""
    if data[:4] not in (b'IWAD', b'PWAD'):
        return None
    n, off = struct.unpack_from('<ii', data, 4)
    for i in range(n):
        pos, size, nm = struct.unpack_from('<ii8s', data, off + 16 * i)
        if nm.rstrip(b'\0').decode() == name:
            return pos
    return None


def elf_segments(path):
    data = open(path, 'rb').read()
    if data[:4] != b'\x7fELF':
        sys.exit(f'{path}: not an ELF file')
    if data[4] != 1:
        sys.exit(f'{path}: expected ELF32')
    endian = '<' if data[5] == 1 else '>'
    (e_entry, e_phoff, _e_shoff, _flags, _ehsize, e_phentsize, e_phnum) = \
        struct.unpack_from(endian + 'IIIIHHH', data, 24)
    segments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, _memsz, _flags, _align = \
            struct.unpack_from(endian + 'IIIIIIII', data, off)
        if p_type == 1 and p_filesz > 0:
            if memmap.IRQ_EXEC <= p_paddr < (memmap.LC_RAM+0xf00):
                if p_paddr + p_filesz > (memmap.LC_RAM+0xf00):
                    sys.exit('IRQ execution section crosses its reserved range')
                p_paddr -= 0x2200  # $DC00-$DEFF executes; $BA00-$BCFF loads
            segments.append((p_paddr, data[p_offset:p_offset + p_filesz]))
    return e_entry, segments


def compress_runs(runs, below, cache):
    """The runs below address below as B1 segments: each run in chunks
    that do not cross a bank, a chunk compressed when that saves a block
    (else it stays a raw run). Runs of 3 items (store regions) stay."""
    out = []
    for run in runs:
        if len(run) == 3 or run[0] >= below:
            out.append(run)
            continue
        addr, payload = run
        pos = 0
        while pos < len(payload):
            a = addr + pos
            n = min(len(payload) - pos, 0x10000 - (a & 0xffff))
            data = payload[pos:pos + n]
            if a >> 16 == 0x1d:
                # This bank is B1 staging during boot. Load its live art raw
                # last, after all compressed lower banks have been decoded.
                out.append((a,data));pos+=n;continue
            enc = struct.pack('<H', n & 0xffff) + b1.compress(data, cache)
            enc += bytes(-len(enc) % BLOCK)
            if len(enc) + BLOCK <= n:           # (a length of 64 KB is 0)
                out.append((a, enc, 'b1'))
            else:
                out.append((a, data))
            pos += n
    # Higher live banks may also contain B1 tables. Staging becomes art only
    # after every resident decoder call; the on-disk episode still comes last.
    return sorted(out,key=lambda r:(r[0]>=below,r[0]>>16==0x1d))


GAP_BLOCKS = 16                 # zero fill between runs of one bank: the disk 1
                                #   header has room for only 44 segments


def punch_setx(runs):
    """Drop 02:CC00 from a merged run. The WOLF.SETX seedling is the only
    load of that block; gap fill must not write zeros over it."""
    lo, hi = SETX_ADDR, SETX_ADDR + BLOCK
    out = []
    for run in runs:
        if len(run) != 2:
            out.append(run)
            continue
        addr, payload = run
        end = addr + len(payload)
        if end <= lo or addr >= hi:
            out.append(run)
            continue
        if addr < lo:
            head = payload[:lo - addr]
            if len(head) % BLOCK:
                sys.exit('slotExt hole splits a block')
            out.append((addr, head))
        if end > hi:
            tail = payload[hi - addr:]
            if len(tail) % BLOCK:
                sys.exit('slotExt hole splits a block')
            out.append((hi, tail))
    return out


def merge(segments, gap=0):
    """Merge segments into runs of consecutive 512 byte blocks. Runs in one
    bank that are at most gap blocks apart join into one, the gap filled
    with zeros: nothing loads there, and B1 packs the zeros to nothing.
    Bank 0 keeps its gaps: the loader works in $7800-$7FFF while it loads."""
    blocks = {}
    for addr, payload in segments:
        pos = 0
        while pos < len(payload):
            a = addr + pos
            blk = a & ~(BLOCK - 1)
            off = a - blk
            n = min(BLOCK - off, len(payload) - pos)
            b = blocks.setdefault(blk, bytearray(BLOCK))
            b[off:off + n] = payload[pos:pos + n]
            pos += n
    runs = []
    for blk in sorted(blocks):
        end = runs[-1][0] + len(runs[-1][1]) if runs else 0
        if runs and end == blk:
            runs[-1][1].extend(blocks[blk])
        elif runs and gap and blk >= 0x10000 and blk >> 16 == (end - 1) >> 16 and blk - end <= gap * BLOCK:
            runs[-1][1].extend(bytes(blk - end))
            runs[-1][1].extend(blocks[blk])
        else:
            runs.append([blk, bytearray(blocks[blk])])
    return [(a, bytes(b)) for a, b in runs]


# --------------------------------------------------------------------------
# ProDOS volumes

def index_blocks(n):
    """The index blocks of a ProDOS file of n data blocks: none (seedling),
    one (sapling), or a master index and one for each 256 (tree)."""
    if n <= 1:
        return 0
    if n <= 256:
        return 1
    return 1 + -(-n // 256)


def data_capacity(readme=True):
    """Data blocks with README and its index; caller reserves disk-1 settings."""
    readme_blocks = -(-len(README.format(n=9, total=9).encode()) // BLOCK) if readme else 0
    overhead = readme_blocks + index_blocks(readme_blocks)
    n = DISK_BLOCKS - DATA_FIRST
    while DATA_FIRST + n + index_blocks(n) + overhead > DISK_BLOCKS:
        n -= 1
    return n


def bitmap_blocks(blocks):
    return -(-blocks // (8 * BLOCK))


def prodos_time(t):
    """A ProDOS date and time (a year of 0-39 is 2000-2039)."""
    return struct.pack('<HH', (t.year % 100) << 9 | t.month << 5 | t.day,
                       t.hour << 8 | t.minute)


def index_block(pointers):
    """An index block (or master index block): the low bytes of the block
    numbers, then the high bytes at 256."""
    b = bytearray(BLOCK)
    for i, p in enumerate(pointers):
        b[i] = p & 0xff
        b[256 + i] = p >> 8
    return b


class Volume:
    """A ProDOS volume image: the boot and header blocks, the volume
    directory and bitmap, and files with their data in chosen blocks."""

    def __init__(self, name, blocks, stamp):
        self.name = name
        self.blocks = blocks
        self.stamp = stamp
        self.img = bytearray(blocks * BLOCK)
        self.free = [True] * blocks
        # Large HD volumes keep the bitmap at the end; boot still reads block 8.
        self.bitmap_start = BITMAP_BLOCK if blocks <= 8192 else blocks-bitmap_blocks(blocks)
        self.bitmap = range(self.bitmap_start, self.bitmap_start + bitmap_blocks(blocks))
        for b in (0, 1, *DIR_BLOCKS, *range(BITMAP_BLOCK, min(LOADER_FIRST, BITMAP_BLOCK+bitmap_blocks(blocks))), *self.bitmap):
            self.free[b] = False
        self.entries = []

    def write(self, block, data):
        self.img[block * BLOCK:block * BLOCK + len(data)] = data

    def take(self, blocks):
        for b in blocks:
            if not self.free[b]:
                sys.exit(f'{self.name}: block {b} used twice')
            self.free[b] = False

    def alloc(self):
        b = self.free.index(True)
        self.free[b] = False
        return b

    def add_file(self, name, ftype, aux, access, data, blocks=None, allocated=False):
        """File name with data in blocks (a list of block numbers), else in
        the first free blocks; its index blocks go to the first free
        blocks after that."""
        n = max(1, -(-len(data) // BLOCK))
        if blocks is None:
            blocks = [self.alloc() for _ in range(n)]
        else:
            blocks = list(blocks)
            if len(blocks) != n:
                sys.exit(f'{name}: {n} blocks of data, {len(blocks)} blocks given')
            if not allocated:self.take(blocks)
        for i, b in enumerate(blocks):
            self.write(b, data[i * BLOCK:(i + 1) * BLOCK])
        if n == 1:
            storage, key, used = 1, blocks[0], 1
        elif n <= 256:
            storage, key, used = 2, self.alloc(), n + 1
            self.write(key, index_block(blocks))
        else:
            storage, key = 3, self.alloc()
            subs = []
            for i in range(0, n, 256):
                subs.append(self.alloc())
                self.write(subs[-1], index_block(blocks[i:i + 256]))
            self.write(key, index_block(subs))
            used = n + 1 + len(subs)
        e = bytearray(39)
        e[0] = storage << 4 | len(name)
        e[1:1 + len(name)] = name.encode()
        e[16] = ftype
        struct.pack_into('<HH', e, 17, key, used)
        e[21:24] = len(data).to_bytes(3, 'little')
        e[24:28] = self.stamp
        e[30] = access
        struct.pack_into('<H', e, 31, aux)
        e[33:37] = self.stamp
        struct.pack_into('<H', e, 37, DIR_BLOCKS[0])
        self.entries.append(e)
        return blocks

    def add_saves(self):
        """Eight world files. The aux word is the first data block. The data
        blocks of a file are one run, and the next file starts one index
        block later, so the game can step by a fixed stride."""
        first = None
        stride = SAVE_DATA + 1
        for slot in range(SAVE_SLOTS):
            name = f'WOLF.SAVE{slot}'
            blocks = self.add_file(name, TYPE_BIN, 0, READ | WRITE | RENAME | DESTROY,
                                   bytes(SAVE_DATA * BLOCK))
            if blocks != list(range(blocks[0], blocks[0] + SAVE_DATA)):
                sys.exit(f'{name} data is not one contiguous run')
            if first is None:
                first = blocks[0]
            if blocks[0] != first + slot * stride:
                sys.exit(f'{name} is not on the save stride')
            struct.pack_into('<H', self.entries[-1], 31, blocks[0])
        return first

    def image(self):
        """The image with the volume directory and the bitmap."""
        h = bytearray(39)
        h[0] = 0xf0 | len(self.name)
        h[1:1 + len(self.name)] = self.name.encode()
        h[24:28] = self.stamp
        h[30] = READ | WRITE | RENAME | DESTROY
        h[31] = 39                              # entry length
        h[32] = 13                              # entries in a block
        struct.pack_into('<HHH', h, 33, len(self.entries), self.bitmap_start, self.blocks)
        slots = [h] + self.entries
        if len(slots) > 13 * len(DIR_BLOCKS):
            sys.exit(f'{self.name}: too many files')
        for i, blk in enumerate(DIR_BLOCKS):
            b = bytearray(BLOCK)
            struct.pack_into('<HH', b, 0, DIR_BLOCKS[i - 1] if i else 0,
                             DIR_BLOCKS[i + 1] if i + 1 < len(DIR_BLOCKS) else 0)
            for k, e in enumerate(slots[13 * i:13 * (i + 1)]):
                b[4 + 39 * k:4 + 39 * (k + 1)] = e
            self.write(blk, b)
        bitmap = bytearray(BLOCK * len(self.bitmap))
        for b in range(self.blocks):
            if self.free[b]:
                bitmap[b >> 3] |= 0x80 >> (b & 7)
        self.write(self.bitmap_start, bitmap)
        return bytes(self.img)


def place(text):
    """A load address: a number, or a tools/memmap.py name with an optional +offset."""
    import memmap
    text = text.strip()
    try:
        return int(text, 0)
    except ValueError:
        name, _, offset = text.partition('+')
        if name not in memmap.NAMES:
            sys.exit(f'unknown memory map name in a load address: {text}')
        return memmap.NAMES[name] + (int(offset, 0) if offset else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--boot', required=True)
    ap.add_argument('--loader', required=True)
    ap.add_argument('--elf', required=True)
    ap.add_argument('--entry', type=place)
    ap.add_argument('--data', action='append', default=[],
                    help='FILE@ADDR, loaded at a 512 byte aligned address')
    ap.add_argument('--picture', help='the WAD lump to show while the disks load')
    ap.add_argument('--picture-file', help='FILE@ADDR: first 32 KB of the SHR picture file (the boot screen)')
    ap.add_argument('--picture-reuse', action='append', default=[],
                    help='FILE@ADDR: load after the picture, reusing only its first 31 KB of fast RAM')
    ap.add_argument('--store', help='FILE@ADDR: the level store, after all other data')
    ap.add_argument('--boot-song', help='INTRO unit FILE@ADDR, reusing its aligned store streams')
    ap.add_argument('--disk-units', help='build/assets/episode-disk.json: the store blocks of each load (floppies)')
    ap.add_argument('--campaign', help='build/gen/campaign.json: the floor routes (floppies)')
    ap.add_argument('--max-disks', type=int, default=8, help='the most floppies the layout may use')
    ap.add_argument('--data-list', action='append', default=[],
                    help='a file of FILE@ADDR lines, as --data (unaligned addresses allowed)')
    ap.add_argument('--menu', help='WOLF.MENU: the front end pictures and title, on disk 1 and the hard disk')
    ap.add_argument('--hd-only', action='store_true', help='one or two hard disk volumes with the level store kept on disk')
    ap.add_argument('--no-readme', action='store_true', help='omit host documentation from every game volume')
    ap.add_argument('--hd', help='also one volume with all the data, for a hard disk')
    ap.add_argument('--hd-store', help='FILE@ADDR: the store of the hard disk volume (raw units: '
                    'a hard disk reads faster than B1 decodes), else --store')
    ap.add_argument('--scsi', help='also that volume with an Apple partition map')
    ap.add_argument('--out', required=True, help='output name prefix')
    ap.add_argument('--compress', action='store_true',
                    help='the data below the store as B1 segments (the loader decodes them)')
    ap.add_argument('--b1cache', help='the cache directory of tools/b1.py')
    args = ap.parse_args()

    boot = open(args.boot, 'rb').read()
    loader = open(args.loader, 'rb').read()
    if len(boot) > BLOCK:
        sys.exit('boot block too large')
    if len(loader) > LOADER_BLOCKS * BLOCK:
        sys.exit('loader too large')
    loader = loader.ljust(LOADER_BLOCKS * BLOCK, b'\0')

    entry, segments = elf_segments(args.elf)
    _segs, symbols = elf.read(args.elf)
    setx_addr = symbols.get('slotExt')
    if setx_addr != SETX_ADDR:
        sys.exit(f'slotExt at {setx_addr!r} is not the 512-byte block at {SETX_ADDR:#x}')
    # The seedling is the only disk copy. A second copy inside the data file
    # would be another boot read of the same block.
    kept = []
    for addr, payload in segments:
        if addr < SETX_ADDR + BLOCK and addr + len(payload) > SETX_ADDR:
            if addr != SETX_ADDR or payload != setx_bytes():
                sys.exit('the slotExt segment is not the empty WOLF.SETX block')
            continue
        kept.append((addr, payload))
    segments = kept
    if args.entry is not None:
        entry = args.entry
    for spec in args.data:
        path, addr = spec.rsplit('@', 1)
        addr = place(addr)
        if addr % BLOCK:
            sys.exit(f'{spec}: address not block aligned')
        segments.append((addr, open(path, 'rb').read()))
    for lst in args.data_list:
        for spec in open(lst).read().split():
            path, addr = spec.rsplit('@', 1)
            segments.append((place(addr), open(path, 'rb').read()))
    store = None
    if args.store:
        path, addr = args.store.rsplit('@', 1)
        store = (place(addr), open(path, 'rb').read())
        if store[0] % BLOCK:
            sys.exit(f'{args.store}: address not block aligned')
    pic = None
    picfile = None
    if args.picture_file:
        path, addr = args.picture_file.rsplit('@', 1)
        pic = place(addr)
        picfile = open(path, 'rb').read()
        if pic % BLOCK or len(picfile) < PIC_BLOCKS * BLOCK:
            sys.exit(f'{args.picture_file}: less than {PIC_BLOCKS} blocks, or not at a block')
        # Only the SHR screen is needed at boot. The extra 4 KB of the
        # game's picture record is loaded by W_LoadSet with the title;
        # retaining it here would overwrite INTRO at $2A8000.
        segments.append((pic, picfile[:PIC_BLOCKS * BLOCK]))
    if args.picture:
        for addr, payload in segments:
            pos = wad_lump(payload, args.picture)
            if pos is not None:
                pic = addr + pos
                break
        if pic is None:
            sys.exit(f'{args.picture}: no such lump in the data')
        if pic % BLOCK:
            sys.exit(f'{args.picture}: not block aligned')

    spans = sorted((a, a + len(p)) for a, p in segments)
    boot_song = None
    if args.boot_song:
        path, addr = args.boot_song.rsplit('@', 1)
        boot_song = (place(addr), open(path, 'rb').read())
        spans.append((boot_song[0], boot_song[0] + len(boot_song[1])))
        spans.sort()
    for (a0, e0), (a1, e1) in zip(spans, spans[1:]):
        if a1 < e0:
            sys.exit(f'data at ${a1:06X}-${e1:06X} overlaps data at ${a0:06X}-${e0:06X}')
    for start, end in spans:
        if not 0 <= start < end <= 0x1000000:
            sys.exit(f'resident data at ${start:X}-${end:X} is outside 24-bit memory')
        if start < FWSTATE_END and end > FWSTATE:
            sys.exit(f'data at ${start:06X}-${end:06X} overlaps the firmware state copy at ${FWSTATE:06X}-${FWSTATE_END:06X} (FWSTATE in src/iigs/ui_bridge.s)')
        if start < 0x8000 and end > 0x6000 and not (start >= 0x6000 + len(loader) and end <= 0x7800):
            sys.exit(f'data at ${start:06X}-${end:06X} overlaps the resident loader or its buffers ($6000-$7FFF)')

    reuse = []
    for spec in args.picture_reuse:
        path, addr = spec.rsplit('@', 1)
        addr, data = place(addr), open(path, 'rb').read()
        end = addr + ((len(data) + BLOCK - 1) // BLOCK) * BLOCK
        if picfile is None or addr % BLOCK or not data or not (pic <= addr < end <= pic + 0x7c00):
            sys.exit(f'{spec}: reuse must stay in picture pixels, preserving its SCBs and palettes')
        for start, payload in segments + reuse:
            if start == pic and payload == picfile[:PIC_BLOCKS * BLOCK]:
                continue
            if addr < start + len(payload) and start < end:
                sys.exit(f'{spec}: picture reuse overlaps resident data at ${start:06X}')
        reuse.append((addr, data))

    runs = merge(segments, GAP_BLOCKS)
    if store is not None:
        # data above the store (8 MB only: the loader loads the banks from
        # $40 only with the store) goes after it on the disks
        send = store[0] + len(store[1])
        if any(a < send and a + len(p) > store[0] for a, p in runs):
            sys.exit('data inside the store')
        runs = [r for r in runs if r[0] < store[0]] + merge([store]) + \
            [r for r in runs if r[0] >= send]
    picdata = None
    if pic is not None:
        # take the picture blocks out of the runs; they go first
        blocks = {}
        rest = []
        for addr, payload in runs:
            for i in range(len(payload) // BLOCK):
                a = addr + i * BLOCK
                if pic <= a < pic + PIC_BLOCKS * BLOCK:
                    blocks[(a - pic) // BLOCK] = payload[i * BLOCK:(i + 1) * BLOCK]
                else:
                    rest.append((a, payload[i * BLOCK:(i + 1) * BLOCK]))
        runs = merge(rest)
        picdata = b''.join(blocks[b] for b in picture_order())
    # The picture is already on SHR when these later segments arrive. Do not
    # feed them through picture extraction or fill the retained palette gap.
    if reuse:
        runs = merge(runs + reuse)
    # the hard disk volume: the data as it is, and its own store
    runs = punch_setx(runs)
    hd_runs = [r[:2] for r in runs if not (store and store[0] <= r[0] < store[0] + len(store[1]))]
    hd_store = store
    if args.hd_store:
        path, addr = args.hd_store.rsplit('@', 1)
        hd_store = (place(addr), open(path, 'rb').read())
    if hd_store:
        hd_runs = sorted(hd_runs + merge([hd_store]), key=lambda r: r[0])
    if args.compress and not args.hd_only:
        runs = compress_runs(runs, store[0] if store else 1 << 24, args.b1cache)

    # Split (address, data, flags) segments across boot disks. Reserve
    # settings, save names and save files on the home disk.
    capacity = data_capacity(readme=not args.no_readme)
    menu = open(args.menu, 'rb').read() if args.menu else b''
    menu_blocks = len(menu) // BLOCK
    if len(menu) % BLOCK:
        sys.exit(f'{args.menu}: not a whole number of blocks')
    menu_cost = menu_blocks + index_blocks(menu_blocks) if menu else 0
    if args.hd_only:
        if not args.hd or not hd_store:
            sys.exit('--hd-only needs --hd and --store')
        # The store address is virtual in this mode. Registered EP05 uses
        # $1000000 so the large store cannot overlap resident slow-RAM fonts.
        segs = ([(pic, picdata, SEG_PIC)] if picdata else []) + [(a, p, 0) for a, p in hd_runs]
        write_hd_only(segs, hd_store, args.hd, args.scsi, boot, loader, entry,
                      menu, setx_addr)
        return
    if store is None or not (args.disk_units and args.campaign):
        sys.exit('floppies need --store, --disk-units and --campaign (tools/floppy_layout.py)')
    # Disk 1: the boot data only; the game never asks for it after the boot. The home disk,
    # the last boot disk (disk 2 when the boot data fits disk 1): WOLF.SETTINGS, WOLF.SETX,
    # WOLF.MENU, the saves, the store blocks of the title, then floors (tools/floppy_layout.py).
    # The other disks: the store blocks of floors.
    import floppy_layout
    sbase, send = store[0], store[0] + len(store[1])
    resident = ([(pic, picdata, SEG_PIC)] if picdata else []) + [
        (r[0], r[1], SEG_B1 if len(r) == 3 else 0) for r in runs if not sbase <= r[0] < send]
    units = json.loads(Path(args.disk_units).read_text())
    play_image = 'play_floors' in units
    if play_image:
        resident.append((memmap.PLAY_CACHE, play_cache_image(store[1]), 0))
    boot_disks = [[]]
    free = capacity
    slots = MAX_SEGMENTS - 2 - BOOT_RUN_SLOTS
    for seg in resident:
        n = len(seg[1]) // BLOCK
        if n > free or len(boot_disks[-1]) == slots:
            boot_disks.append([])
            free = capacity
            slots = MAX_SEGMENTS - BOOT_RUN_SLOTS
        boot_disks[-1].append(seg)
        free -= n
    if len(boot_disks) == 1:
        boot_disks.append([])
        free = capacity
    home = len(boot_disks)
    home_room = free - 2 - menu_cost - SAVE_COST
    home_runs = MAX_SEGMENTS - 2 - len(boot_disks[-1])
    print(f'mkdisk: the boot reads disks 1-{home}; disk {home} is the home disk '
          f'({home_room} blocks free for the title and floors)')
    layout = floppy_layout.plan(units, json.loads(Path(args.campaign).read_text()), capacity,
                                home_room, args.max_disks, len(boot_disks), home, home_runs)
    packed = store[1] + bytes(-len(store[1]) % BLOCK)
    disks = []
    for number, plan in enumerate(layout['disks'], 1):
        segs = list(boot_disks[number - 1]) if number <= len(boot_disks) else []
        segs += [(sbase + first * BLOCK, packed[first * BLOCK:(first + count) * BLOCK], 0)
                 for first, count in plan['runs']]
        disks.append(segs)

    build = zlib.crc32(loader)
    for segs in disks:
        for _, payload, _ in segs:
            build = zlib.crc32(payload, build)
    # Directory dates use SOURCE_DATE_EPOCH in UTC, or the fixed date below,
    # so packing the same inputs does not depend on the wall clock.
    raw = os.environ.get('SOURCE_DATE_EPOCH')
    if raw:
        when = datetime.datetime.fromtimestamp(int(raw), datetime.timezone.utc)
    else:
        when = datetime.datetime(2026, 9, 27, 0, 0, tzinfo=datetime.timezone.utc)
    stamp = prodos_time(when)
    # The store never loads at boot: an 8 MB IIgs keeps the blocks it reads.
    resdisks = len(boot_disks)
    common = dict(stamp=stamp, boot=boot, loader=loader, entry=entry, build=build,
                  sbase=sbase, send=send, resdisks=resdisks, sbanks=0, setx_addr=setx_addr,
                  no_readme=args.no_readme, floor_disks=layout['floor_disk'])
    common['boot_aliases'] = song_aliases(store, boot_song) if boot_song else []
    aliases = common['boot_aliases']
    common['step'] = common['step_ram'] = bar_step(boot_read_blocks(disks, resdisks, aliases, False))
    # The home disk first: every header names the blocks of its files.
    order = [home] + [num for num in range(1, len(disks) + 1) if num != home]
    home_files = None
    for num in order:
        out = f'{args.out}{num}.po'
        img, files = volume(f'WOLF.DISK{num}', DISK_BLOCKS, disks[num - 1], num, len(disks),
                            f'WOLF.DATA{num}', README.format(n=num, total=len(disks)), out, menu=menu,
                            home=home, home_files=home_files, play_image=play_image, **common)
        home_files = home_files or files
        open(out, 'wb').write(img)
    if args.hd:
        segs = ([(pic, picdata, SEG_PIC)] if picdata else []) + [(a, p, 0) for a, p in hd_runs]
        n = sum(len(p) // BLOCK for _, p, _ in segs)
        blocks = (LOADER_FIRST + LOADER_BLOCKS + 1 + n + index_blocks(n) + (0 if args.no_readme else 3)
                  + HD_FREE + menu_cost + SAVE_COST)
        if blocks > 8192:
            blocks += bitmap_blocks(blocks)
        hd = dict(common, resdisks=1, floor_disks=[0] * FLOOR_DISKS)
        hd['boot_aliases'] = song_aliases(hd_store, boot_song) if boot_song else []
        hd.update(sbase=hd_store[0], send=hd_store[0] + len(hd_store[1]))
        hd['step'] = hd['step_ram'] = bar_step(boot_read_blocks([segs], 1, hd['boot_aliases'], False))
        img, _ = volume('WOLF', (blocks + 7) & ~7, segs, 1, 1, 'WOLF.DATA', README_HD, args.hd,
                        menu=menu, **hd)
        open(args.hd, 'wb').write(img)
        if args.scsi:
            open(args.scsi, 'wb').write(partitioned(img))
            print(f'{args.scsi}: the volume at block {APM_PART} of an Apple partition map')
    for num, plan in enumerate(layout['disks'], 1):
        print(f'disk {num}: {len(plan["blocks"])} store blocks, floors '
              + (' '.join(str(f + 1) for f in plan['floors']) or 'none'))
    print(f'entry ${entry:06X}, {len(disks)} disk(s), build {build:08X}, bar step {common["step"]}')


def partitioned(volume_img):
    """A device image: an Apple partition map (the driver descriptor in
    block 0, the map entries from block 1: the map, the ProDOS partition)
    and the volume at block APM_PART."""
    blocks = APM_PART + len(volume_img) // BLOCK
    img = bytearray(APM_PART * BLOCK) + volume_img
    struct.pack_into('>2sHI', img, 0, b'ER', BLOCK, blocks)
    parts = ((b'Apple', b'Apple_partition_map', 1, APM_PART - 1),
             (b'WOLF', b'Apple_PRODOS', APM_PART, blocks - APM_PART))
    for i, (name, ptype, start, count) in enumerate(parts):
        e = 512 * (1 + i)
        struct.pack_into('>2sHIII32s32sII', img, e, b'PM', 0, len(parts), start, count,
                         name, ptype, 0, count)
        struct.pack_into('>I', img, e + 88, 0x37)       # valid, allocated, in use,
    return bytes(img)                                   #   readable, writable


def data_first():
    """The first block of the data file: after the loader (its index
    block is block 7)."""
    return DATA_FIRST


def play_cache_image(data):
    """The play cache as the boot loads it into PLAY_CACHE from disk 1: the store blocks that
    the root's play table places (tools/build_registered_episode.py play_cache, "PC02": the
    runs from its run offset to its end, 10 bytes each: first block, blocks, address, bank,
    slot; src/iigs/leveldirectory.s playLookup)."""
    sig, _, _, _, _, run_at, end = struct.unpack_from('<4s6H', data, BLOCK)
    if sig != b'PC02':
        sys.exit(f'the store root has no play table ({sig!r})')
    image = bytearray()
    for at in range(BLOCK + run_at, BLOCK + end, 10):
        first, count, low, bank, _ = struct.unpack_from('<5H', data, at)
        offset = (bank << 16 | low) - memmap.PLAY_CACHE
        if not 0 <= offset <= memmap.PLAY_CACHE_SIZE - count * BLOCK:
            sys.exit(f'play table run at ${bank:02X}:{low:04X} is outside PLAY_CACHE')
        image.extend(bytes(max(0, offset + count * BLOCK - len(image))))
        image[offset:offset + count * BLOCK] = data[first * BLOCK:(first + count) * BLOCK]
    return bytes(image)


def song_aliases(store, song):
    """Validate and reference INTRO chunks already present in the level store."""
    base, data = store
    dest, expected = song
    count, = struct.unpack_from('<H', data, 6)
    for k in range(count):
        off, n, _, disk, _, _ = struct.unpack_from('<IHBBHH', data, 8 + 12*k)
        active = False
        rebuilt = bytearray()
        aliases = []
        for j in range(n):
            e = data[off+10*j:off+10*j+10]
            kind, = struct.unpack_from('<H', e)
            src = int.from_bytes(e[5:8], 'little')
            length, = struct.unpack_from('<H', e, 8)
            if 0xffe0 <= kind < 0xfff0:
                active = kind == 0xffea
            elif active and kind == 0xfffc:
                raw, = struct.unpack_from('<H', data, src-base)
                part = b1.decode(data[src-base+2:src-base+length], raw)
                address = dest + len(rebuilt)
                if disk != 1 or src % BLOCK or (address & 0xffff) + raw > 0x10000:
                    raise ValueError('INTRO boot stream must be aligned, bank-safe and on disk 1')
                aliases.append((address, src, -(-length // BLOCK)))
                rebuilt += part
            elif active and kind == 0xfffb:
                if rebuilt != expected:
                    raise ValueError('INTRO boot alias differs from the song unit')
                return aliases
    raise ValueError('INTRO boot song not found in the store')


def bar_step(blocks):
    """Blocks per load-bar cell. The loader fills LOAD_CELLS cells, one
    every this many blocks, then fills any shortfall at once."""
    step = max(1, -(-blocks // LOAD_CELLS))
    if step > 511:
        sys.exit('too much data for the progress bar step')
    return step


def boot_read_blocks(disks, resdisks, aliases, store):
    """Blocks the loader reads at boot. Without the store in RAM: every
    resident segment on disks 1..resdisks, including slow RAM. With it:
    every segment on every disk. Plus the boot-song aliases (extra reads)
    the WOLF.SETTINGS block and the WOLF.SETX block on disk 1."""
    n = 0
    use = disks if store else disks[:resdisks]
    for segs in use:
        for addr, payload, _flags in segs:
            if store or (addr >> 16) < STORE_BANK or addr >= memmap.SLOW_RAM:
                n += len(payload) // BLOCK
    n += sum(count for _dest, _src, count in aliases)
    n += 2
    return n


def hd_data_first(blocks, disk):
    """First payload block after the fixed metadata and disk-1 loader."""
    return 6 + min(2, bitmap_blocks(blocks)) + (LOADER_BLOCKS + 1 if disk == 1 else 0)


def hd_required_blocks(payload_blocks, blocks, disk, menu_blocks):
    indexes = sum(index_blocks(min(HD_FILE_BLOCKS, payload_blocks - start))
                  for start in range(0, payload_blocks, HD_FILE_BLOCKS))
    tail_bitmap = bitmap_blocks(blocks) if blocks > 8192 else 0
    resident_files = (2 + SAVE_COST + menu_blocks + index_blocks(menu_blocks)) if disk == 1 else 0
    return (hd_data_first(blocks, disk) + payload_blocks + indexes + tail_bitmap
            + resident_files + HD_FREE)


def hd_volume_blocks(payload_blocks, disk, menu_blocks):
    """Smallest eight-block-rounded volume; 65535 is also a valid size."""
    blocks = 8
    while True:
        required = hd_required_blocks(payload_blocks, blocks, disk, menu_blocks)
        if required > HD_MAX_BLOCKS:
            raise ValueError('hard disk payload exceeds the 65535-block ProDOS volume limit')
        if required <= blocks:
            return blocks
        blocks = min(HD_MAX_BLOCKS, (required + 7) & ~7)


def hd_payload_capacity(disk, menu_blocks):
    lo, hi = 0, HD_MAX_BLOCKS
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if hd_required_blocks(mid, HD_MAX_BLOCKS, disk, menu_blocks) <= HD_MAX_BLOCKS:
            lo = mid
        else:
            hi = mid - 1
    return lo


def second_volume_path(path):
    path = Path(path)
    return path.with_name(path.stem + '2' + path.suffix)


def write_hd_only(segs, store, hd, scsi, boot, loader, entry, menu, setx_addr):
    """Keep all resident data on disk 1, then fill at most two ProDOS volumes."""
    sbase, raw = store
    if not raw or sbase % BLOCK:
        sys.exit('disk-only store must be nonempty and block aligned')
    if len(menu) % BLOCK:
        sys.exit('menu is not a whole number of blocks')
    send = sbase + len(raw)
    resident = [(a, p, f) for a, p, f in segs if not sbase <= a < send]
    for addr, payload, _flags in resident:
        if not 0 <= addr < addr + len(payload) <= min(sbase, 0x1000000):
            sys.exit('disk-only resident data must be below the virtual store and within 24-bit memory')
        if len(payload) % BLOCK:
            sys.exit('disk-only resident data is not a whole number of blocks')
    if len(resident) + 2 > MAX_SEGMENTS:
        sys.exit('too many resident boot segments')
    packed_store = raw + bytes(-len(raw) % BLOCK)
    store_blocks = len(packed_store) // BLOCK
    resident_blocks = sum(len(p) // BLOCK for _, p, _ in resident)
    menu_blocks = len(menu) // BLOCK
    capacity = hd_payload_capacity(1, menu_blocks)
    if resident_blocks >= capacity:
        sys.exit('resident data and writable game files leave no room for the store on disk 1')
    # One volume: a floor load reads one disk (src/iigs/leveldirectory.s storeFromDisk).
    if resident_blocks + store_blocks > capacity:
        sys.exit(f'the hard disk volume holds {capacity} blocks; the boot data and the store need '
                 f'{resident_blocks + store_blocks}')
    disks = [resident + [(sbase, packed_store, 0)]]
    sizes = [hd_volume_blocks(sum(len(p) // BLOCK for _, p, _ in disks[0]), 1, menu_blocks)]
    build = 0
    for _, payload, _ in segs:
        build = zlib.crc32(payload, build)
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '1790467200'))
    stamp = prodos_time(datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc))
    # Resident slow-RAM font data above $420000 must count too. The virtual
    # store never contributes boot reads, including on an expanded machine.
    step = bar_step(resident_blocks + 2)
    home_files = None
    for number, (disk, blocks) in enumerate(zip(disks, sizes), 1):
        out = hd if number == 1 else second_volume_path(hd)
        image, files = volume('WOLF' if number == 1 else 'WOLF.DATA2', blocks, disk,
                              number, len(disks), 'WOLF.DATA', '', out, stamp=stamp,
                              boot=boot, loader=loader, entry=entry, step=step, step_ram=step,
                              build=build, sbase=sbase, send=sbase + len(packed_store),
                              resdisks=1, sbanks=0, floor_disks=[0] * FLOOR_DISKS, menu=menu,
                              setx_addr=setx_addr, disk_only=True, home_files=home_files)
        home_files = home_files or files
        Path(out).write_bytes(image)
        if scsi:
            sout = scsi if number == 1 else second_volume_path(scsi)
            Path(sout).write_bytes(partitioned(image))
    print(f'entry ${entry:06X}, build {build:08X}, registered disk-only store '
          f'{len(raw)} bytes on {len(disks)} ProDOS volume(s)')


def volume(name, blocks, segs, num, ndisks, dataname, readme, out, stamp, boot, loader, entry,
           step, step_ram, build, sbase, send, resdisks, sbanks, floor_disks, boot_aliases=(), menu=b'',
           setx_addr=0, disk_only=False, no_readme=False, home=1, home_files=None, play_image=False):
    """The ProDOS volume image of disk num of ndisks with the segments segs
    (address, data, flags): the boot block, the header, WOLF.BOOT, the data
    file, on the home disk WOLF.SETTINGS, WOLF.SETX, WOLF.MENU and the saves, README.
    Every header names the home disk and the blocks of its files: home_files, the second
    value this returns for the home disk. Returns (image, files)."""
    vol = Volume(name, blocks, stamp)
    if not disk_only or num == 1:
        vol.write(0, boot)
        vol.add_file('WOLF.BOOT', TYPE_BIN, 0x6000, READ | INVISIBLE, loader,
                     range(LOADER_FIRST, LOADER_FIRST + LOADER_BLOCKS))
    data = b''.join(payload for _, payload, _ in segs)
    n = len(data) // BLOCK
    first = vol.free.index(True)
    # The store blocks on this disk: runs of the first store block, the count and the
    # first disk block, split where bit 16 of the store block changes.
    runs = []
    block = first
    for addr, payload, flags in segs:
        cnt = len(payload) // BLOCK
        if sbase <= addr < send:
            sb = (addr - sbase) // BLOCK
            while cnt:
                take = min(cnt, 0x10000 - (sb & 0xffff), 0xffff)
                if runs and runs[-1][0] + runs[-1][1] == sb and runs[-1][2] + runs[-1][1] == block \
                        and runs[-1][0] >> 16 == sb >> 16 and runs[-1][1] + take <= 0xffff:
                    runs[-1][1] += take
                else:
                    runs.append([sb, take, block])
                sb += take
                block += take
                cnt -= take
        else:
            block += cnt
    if disk_only and first != hd_data_first(blocks, num):
        sys.exit(f'{name}: unexpected disk-only data start {first}')
    elif not disk_only and blocks == DISK_BLOCKS and first != data_first():
        sys.exit(f'{name}: the data starts at block {first}, not {data_first()}')
    if disk_only:
        # ProDOS file lengths are 24-bit. Reserve all payload blocks before
        # allocating file indexes, keeping the native store map contiguous.
        payload_blocks=list(range(first,first+n));vol.take(payload_blocks)
        for number,start in enumerate(range(0,n,HD_FILE_BLOCKS)):
            count=min(HD_FILE_BLOCKS,n-start)
            filename=dataname if number==0 else dataname+str(number+1)
            vol.add_file(filename,TYPE_BIN,0,READ,data[start*BLOCK:(start+count)*BLOCK],
                         payload_blocks[start:start+count],allocated=True)
    else:
        vol.add_file(dataname, TYPE_BIN, 0, READ, data, range(first, first + n))
    hdr = bytearray(BLOCK)
    hdr[0:6] = b'WOLFGS'
    hdr[6] = num
    hdr[7] = ndisks
    struct.pack_into('<I', hdr, 10, entry & 0xffffff)
    # The entry point occupies bytes10..12. Byte13 holds the ninth bits
    # of the two progress steps; old headers left it zero.
    hdr[13] = (step >> 8) | ((step_ram >> 8) << 1)
    struct.pack_into('<BB', hdr, 14, step & 255, step_ram & 255)
    struct.pack_into('<I', hdr, HDR_BUILD, build)
    block = first
    headsegs = []
    for addr, payload, flags in segs:
        if not sbase <= addr < send:
            headsegs.append((addr | flags << 24, block, len(payload) // BLOCK))
        block += len(payload) // BLOCK
        if flags & SEG_PIC:
            hdr[PIC_ORDER:PIC_ORDER + PIC_BLOCKS] = bytes(picture_order())
    if num == 1:
        for dest, src, count in boot_aliases:
            block = first
            for addr, payload, flags in segs:
                if flags == 0 and addr <= src and src + count*BLOCK <= addr + len(payload):
                    headsegs.append((dest | SEG_B1 << 24, block + (src-addr)//BLOCK, count))
                    break
                block += len(payload)//BLOCK
            else:
                raise ValueError('INTRO boot alias is outside disk-1 data')
    files = None
    if num == home:
        files = dict(settings=vol.add_file('WOLF.SETTINGS', TYPE_CFG, 0, READ | WRITE | RENAME | DESTROY,
                                           bytes(BLOCK))[0], menu=(0, 0))
        headsegs.append((SETTINGS_ADDR, files['settings'], 1))
        xblock = vol.add_file('WOLF.SETX', TYPE_CFG, 0, READ | WRITE | RENAME | DESTROY,
                              setx_bytes())[0]
        headsegs.append((setx_addr, xblock, 1))
        if menu:
            mblocks = vol.add_file('WOLF.MENU', TYPE_BIN, 0, READ, menu)
            if mblocks != list(range(mblocks[0], mblocks[0] + len(mblocks))):
                sys.exit('WOLF.MENU is not in consecutive blocks')
            files['menu'] = (mblocks[0], len(mblocks))
        files['save'] = vol.add_saves()
        home_files = files
    if home_files is None:
        sys.exit(f'{name}: the home disk {home} is written after disk {num}')
    struct.pack_into('<H', hdr, HDR_SETTINGS, home_files['settings'])
    struct.pack_into('<HH', hdr, HDR_MENU, *home_files['menu'])
    struct.pack_into('<HH', hdr, HDR_SAVE, home_files['save'], SAVE_DATA + 1)
    hdr[HDR_HOME_DISK] = home | (PLAY_IMAGE if play_image else 0)
    hdr[HDR_RESDISKS] = resdisks
    hdr[HDR_STOREBANKS] = sbanks
    # A floor's byte (tools/floppy_layout.py plan): bits 4-6 its episode disk - 1 (0: none),
    # bits 0-2 its floor disk - 1; bits 3 and 7 are 0.
    if len(floor_disks) > FLOOR_DISKS or not all(
            d & 0x88 == 0 and (d >> 4) + 1 <= ndisks and (d & 7) + 1 <= ndisks for d in floor_disks):
        sys.exit(f'{name}: invalid floor disk table {floor_disks}')
    hdr[HDR_FLOOR_DISKS:HDR_FLOOR_DISKS + len(floor_disks)] = bytes(floor_disks)
    if 16 + RUN_BYTES * (len(headsegs) + len(runs)) > HDR_FLOOR_DISKS:
        sys.exit(f'{name}: {len(headsegs)} segments and {len(runs)} store runs, more than {MAX_SEGMENTS}')
    hdr[8] = len(headsegs)
    for i, seg in enumerate(headsegs):
        struct.pack_into('<IHH', hdr, 16 + i * 8, *seg)
    at = 16 + RUN_BYTES * len(headsegs)
    for sb, cnt, db in runs:
        struct.pack_into('<HHHBB', hdr, at, sb & 0xffff, cnt, db, num, sb >> 16)
        at += RUN_BYTES
    vol.write(1, hdr)
    if not disk_only and not no_readme:
        vol.add_file('README', TYPE_TXT, 0, READ | WRITE | RENAME | DESTROY,
                     readme.replace('\n', '\r').encode())
    print(f'{out}: {len(headsegs)} segments, {n} data blocks, {sum(vol.free)} of {blocks} '
          f'blocks free')
    return vol.image(), files


if __name__ == '__main__':
    main()
