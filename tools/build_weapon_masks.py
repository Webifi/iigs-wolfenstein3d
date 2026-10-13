"""Weapon occlusion intervals for every view, made once at build time.

The full 10-byte records retain the original scaler entry, source, banks and
cut as a build-time oracle. The prepared renderer loads coverage-only runs:
two bytes of row bounds. Separate literal pose drawers own the pixel stores.
Other renderer configurations retain their original six-byte run format.
"""
import json
import struct
import re
from wolfdata import ROOT, PROFILE
from wolf_source import sprite_ids
from buildconfig import config
from assetspace import Space,segments
from viewgeometry import SIZES,weapon_height
import memmap

STRIDE = 10   # full build-time record, before coverage_only compaction
PAD = 2       # directory entries kept beside the weapon's columns: the paint reads one column past its edge


def source_pixels(full, pose, vi):
    """Screen byte -> original weapon-image offset, using ScalePost sampling."""
    view = SIZES[vi]
    height = weapon_height(view)
    width = height//2
    left, screen_left = (view-width)//2, (160-view)//2
    directory = struct.unpack_from('<H', full, 2*(pose*4+vi))[0]
    pixels = {}
    for col in range(left, left+width):
        pointer = struct.unpack_from('<H', full, directory+2*col)[0]
        for run in range(full[pointer]):
            bounds, _, source, banks, _ = struct.unpack_from('<5H', full, pointer+2+run*10)
            assert banks >> 8 == 9
            for y in range(bounds & 255, bounds >> 8):
                texel = (y-(80-height//2))*64//height
                offset = source+2*texel+(y & 1)-0xc800
                pixels[y*160+screen_left+col] = offset
    return pixels


def coverage_bounds(full):
    """Exact first/exclusive-last byte columns used by the literal drawers."""
    result = []
    for pose in range(20):
        for vi, view in enumerate(SIZES):
            screen_left = (160-view)//2
            columns = {address % 160-screen_left for address in source_pixels(full, pose, vi)}
            first, limit = (min(columns), max(columns)+1) if columns else (0, 0)
            assert 0 <= first <= limit <= view
            result.append(first | limit << 8)
    return result


def coverage_only(full, colors, compact=False):
    """Share equal coverage; whole-pose drawers handle every color change.

    Pose identities are shared only when coverage and rendered pixels match
    on every floor. Equal coverage alone must still redraw changed colors.
    """
    blob = bytearray(20*len(SIZES)*2)
    runs, translated, pictures = {}, {}, {}
    for pose in range(20):
        for vi, view in enumerate(SIZES):
            width = weapon_height(view)//2
            first = (view-width)//2-PAD
            old = struct.unpack_from('<H', full, (pose*4+vi)*2)[0]
            directory = len(blob)
            if not compact:
                blob.extend(bytes((width+2*PAD)*2))
            struct.pack_into('<H', blob, (pose*4+vi)*2, directory-2*first)
            pointers = []
            for i in range(width+2*PAD):
                pointer = struct.unpack_from('<H', full, old+2*(first+i))[0]
                if pointer not in translated:
                    count = full[pointer]
                    raw = bytearray(full[pointer:pointer+2])
                    for n in range(count):
                        raw.extend(full[pointer+2+STRIDE*n:pointer+4+STRIDE*n])
                    raw.extend(bytes(2))
                    key = bytes(raw)
                    if key not in runs:
                        runs[key] = len(blob)
                        blob.extend(raw)
                    translated[pointer] = runs[key]
                pointers.append(translated[pointer])
                if not compact:
                    struct.pack_into('<H', blob, directory+2*i, translated[pointer])
            pixels = tuple(sorted((address, tuple(c[offset] for c in colors))
                                  for address, offset in source_pixels(full, pose, vi).items()))
            coverage = struct.pack('<%dH' % len(pointers), *pointers)
            key = view, coverage, pixels
            if key in pictures:
                struct.pack_into('<H', blob, (pose*4+vi)*2, pictures[key])
            else:
                if compact:
                    directory = len(blob)
                    blob.extend(coverage)
                    struct.pack_into('<H', blob, (pose*4+vi)*2, directory-2*first)
                pictures[key] = directory-2*first
    old_empty = struct.unpack_from('<H', full, len(full)-2)[0]
    empty_directory = len(blob)
    blob.extend(struct.pack('<H', translated[old_empty])*max(SIZES))
    return blob, empty_directory

def prepared():
    mode = config()
    four = mode['colors'] == 'four'
    return four and mode.get('scaler') != 'groups' and mode['pixels'] != 'true'

def scaler_tables():
    """Height list, scaler banks and the row code addresses of build/gen/scalers.inc and rowcode.bin."""
    inc = (ROOT/'build/gen/scalers.inc').read_text()
    heights = [int(x) for x in re.search(r'scaleHeight: .word (.*)', inc)[1].split(',')]
    banks = [int(x) for x in re.search(r'scaleBank: .word (.*)', inc)[1].split(',')]
    rows = (ROOT/'build/assets/rowcode.bin').read_bytes()
    assert len(rows) == len(heights) * 322
    return heights, banks, rows

def main():
    shapes=json.loads((ROOT/'build/assets/sprites.json').read_text())
    commands=(ROOT/'build/assets/weapon-sourcecmd.bin').read_bytes()
    frames=json.loads((ROOT/'build/assets/weapon-sourceframes.json').read_text())
    true=config()['pixels']=='true'
    ready=prepared()
    if ready:heights,banks,rowcode=scaler_tables()
    blob=bytearray(20*len(SIZES)*2);directories=[];runs={};literals=[]
    space=Space(((memmap.NP_WEAPON_CMDS,(memmap.NP_WEAPON_CMDS+0x7800)),(memmap.NP_TRUE_HORIZONTAL+(ROOT/'build/assets/horizontal.bin').stat().st_size,memmap.ART_BRIGHT))) if true else None
    ids = sprite_ids()
    for shape in range(ids['SPR_KNIFEREADY'], ids['SPR_CHAINREADY'] + 5):
        for view in SIZES:
            top=(160-view)//2;bottom=top+view
            h=weapon_height(view);full_top=80-h//2
            columns=view*2 if true else view
            width=h if true else h//2;left=(columns-width)//2
            directory=len(blob)
            if ready:
                # the weapon's scaler: SimpleScaleShape's even height, the nearest height of the list
                n=min(range(len(heights)),key=lambda i:abs(heights[i]-h))
                entry=lambda row:struct.unpack_from('<H',rowcode,n*322+row*2)[0]
            first=left-PAD
            if ready:
                # Only the weapon's columns and PAD beside them have an entry (the others read as empty);
                # the pointer in the head table is biased so that 2 * column indexes it all the same.
                directories.append(directory-2*first);blob.extend(bytes((width+2*PAD)*2))
            else:
                directories.append(directory);blob.extend(bytes(columns*2))
            for col in (range(first,left+width+PAD) if ready else range(columns)):
                u=(col-left)*64//width
                intervals=()
                if left<=col<left+width and 0<=u<64:
                    f=frames[shape]
                    p=(struct.unpack_from('<H',commands,f+u*2)[0]|(commands[f+128+u]<<16))-memmap.SPRITE_CMDS
                    projected=[]
                    while struct.unpack_from('<H',commands,p)[0]:
                        ab,source,bank=struct.unpack_from('<3H',commands,p);p+=6
                        a=max(top,full_top+((ab&255)*h+63)//64)
                        b=min(bottom,full_top+((ab>>8)*h+63)//64)
                        if b>a:projected.append((a,b,source,bank))
                    intervals=tuple(projected)
                key=(view,intervals) if ready else intervals
                if key not in runs:
                    raw=bytearray(struct.pack('<BB',len(intervals),min((a for a,b,_,_ in intervals),default=0))) # count, top row
                    for a,b,source,bank in intervals:
                        if ready:
                            # the bank word as the paint adds it: bytes swapped, plus the scaler's bank
                            joined=(((bank&255)<<8|bank>>8)+banks[n])&65535
                            cut=0 if b==bottom else entry(b)
                            raw.extend(struct.pack('<5H',a|(b<<8),(entry(a)-1)&65535,source,joined,cut))
                        else:raw.extend(struct.pack('<3H',a|(b<<8),source,bank))
                    raw.extend(bytes(2)) # same stream sentinel as source commands
                    if true:
                        address=space.allocate(len(raw))
                        # Bank 14 commands use the lower half; the optional
                        # bank 1F tail uses the upper half. One pointer bit
                        # selects the bank without a parallel far directory.
                        assert (address>>16==0x14 and address&65535<0x8000) or (address>>16==0x1f and address&65535>=0x8000)
                        runs[key]=address&65535;literals.append((address,raw))
                    else:
                        runs[key]=len(blob);blob.extend(raw)
                struct.pack_into('<H',blob,directory+(col-first if ready else col)*2,runs[key])
    empty=runs[(view,())] if ready else runs[()]
    empty_directory=len(blob)
    blob.extend(struct.pack('<H',empty)*max(SIZES)*(2 if true else 1))
    if len(blob)>65536:raise ValueError('weapon commands exceed one bank')
    for n,pointer in enumerate(directories):struct.pack_into('<H',blob,n*2,pointer)
    if ready:
        # Retained as an independent build-time oracle and for diagnostic tools.
        (ROOT/'build/assets/weapon-mask-full.bin').write_bytes(blob)
        (ROOT/'build/gen/weapon_bounds.inc').write_text(
            'weaponBounds: .word '+','.join(map(str, coverage_bounds(blob)))+'\n')
        bounds=[]
        for pose in range(20):
            for vi,view in enumerate(SIZES):
                pixels=source_pixels(blob,pose,vi)
                bounds += [min((a//160 for a in pixels),default=0),max((a//160+1 for a in pixels),default=0)]
        (ROOT/'build/gen/buffer_weapon.inc').write_text('bufferWeaponRows: .byte '+','.join(map(str,bounds))+'\n')
        colors = [(ROOT/f'build/levels/{f}/weapon-pixels-00.bin').read_bytes() for f in range(PROFILE.floors)]
        full = blob
        blob, empty_directory = coverage_only(full, colors)
        if len(blob) > memmap.WEAPON_RUNS_SIZE:
            # Discard only unused directories from identical poses. Keep
            # different pictures distinct even when their coverage agrees.
            blob, empty_directory = coverage_only(full, colors, compact=True)
        assert len(blob) <= memmap.WEAPON_RUNS_SIZE, 'weapon coverage overlaps the pose drawers'
    (ROOT/'build/gen/weapon_empty.inc').write_text('EMPTY_WEAPON_MASK .equ '+str(empty_directory)+'\n')
    (ROOT/'build/assets/weapon-mask.bin').write_bytes(blob)
    (ROOT/'build/assets/weapon-loads.json').write_text(json.dumps(segments(literals,ROOT/'build/assets','weapon-runs'))+'\n')
    print('weapon masks:',len(blob),'bytes,',len(runs),'unique intervals')

if __name__=='__main__':main()
