"""Verify floor art bytes, source coverage and phase-specific RAM spans.

This is a build check. Native rendering, transition and timing checks remain
necessary to verify when the game reads and writes these regions.
"""
import memmap
import argparse
import itertools
import json
import struct
from functools import lru_cache
from pathlib import Path

from elf import read
from floor_art import shapes
from registered_art import FRAME_LEFT, FRAME_CLIP, FRAME_COMMAND_BANK, FRAME_LIGHT_BANKS
from registered_loads import art_rows, read_rows, ui_rows
from wolfdata import ROOT, PROFILE, maps, vswap, sprite

ASSETS = ROOT/'build/assets'


def overlap(a, b):
    return max(a[0], b[0]) < min(a[1], b[1])


def bounds(rows):
    for start, end, name in rows:
        assert 0 <= start < end <= memmap.FAST_RAM_END or memmap.SLOW_RAM <= start < end <= memmap.BANK_E2, (
            name, hex(start), hex(end), 'outside ROM01 plus 4 MiB')


def disjoint(rows):
    bounds(rows)
    for a, b in itertools.combinations(rows, 2):
        assert not overlap(a, b), (a, b, 'overlapping live spans')


def spans(rows):
    return [(r['address'], r['address']+(ROOT/r['file']).stat().st_size, r['file']) for r in rows]


def memory():
    sections, symbols = read(ROOT/'build/wolf.elf')
    resident = [(s['address'], s['address']+s['size'], 'ELF') for s in sections if s['size']]
    rows = []
    for name in ('load-list.txt', 'menu-cache-loads.txt', 'ui-word-loads.txt'):
        for line in (ASSETS/name).read_text().splitlines():
            filename, address = line.rsplit('@', 1)
            if filename.endswith('/boot-table-seeds.bin'):
                continue        # boot only: RAY_FIXED's pad, zeroed by the boot table builders
            rows.append(dict(file=filename, address=int(address, 0)))
    if (ASSETS/'menu-cache-0.bin').stat().st_size:
        rows.append(dict(file='build/assets/menu-cache-0.bin', address=memmap.MENU_CACHE_0))
    from registered_loads import boot_built
    rows += [dict(file=str(path.relative_to(ROOT)), address=address) for address, path in boot_built()
             if path.name != 'rowcode.bin']
    for name, address in [('ui.bin', memmap.UI), ('view-height.bin', memmap.VIEW_HEIGHT),
                          ('weapon-mask.bin', memmap.WEAPON_RUNS), ('map.bin', memmap.MAP),
                          ('clips.bin', memmap.CLIPS), ('tables.bin', memmap.COS_TABLE),
                          ('rowcode.bin', memmap.ROWCODE), ('logic.bin', memmap.LOGIC_BASE),
                          ('demos.bin', memmap.DEMOS)]:
        rows.append(dict(file='build/assets/'+name, address=address))
    boot = resident + spans(rows)
    disjoint(boot)
    # Paused snapshots, the UI's fast caches and B1 scratch are restored by
    # explicit groups. Keep their code, directories and slow fonts resident.
    ui_files = {r['file'] for r in ui_rows()}
    excluded = ui_files | {'build/assets/graytables.bin', 'build/assets/source-planes.bin',
                          'build/assets/logic.bin', 'build/assets/views/1/weights.bin',
                          'build/assets/ui-words-1.bin',
                          # the boot's gray catalog parts and menu effects (registered_loads.boot_rows)
                          'build/assets/gray-boot-head.bin', 'build/assets/gray-boot-tail.bin',
                          'build/assets/effects-menu.bin'}
    static = resident + spans([r for r in rows if r['file'] not in excluded
                              and '/registered-art-' not in r['file']
                              and '/line-proofs-' not in r['file']
                              and '/effects-floor-' not in r['file']
                              and '/effects-cluster-' not in r['file']
                              and '/song-' not in r['file']])
    # The boot-only seed pad becomes floor art after its builders finish.
    static = [(lo, hi, name) for a, b, name in static
              for lo, hi in ([(a, min(b, memmap.BOOT_SEEDS_ART)),
                             (max(a, memmap.BOOT_SEEDS_ART_END), b)]
                            if name == 'build/assets/ray-fixed.bin' else [(a, b)])
              if lo < hi]
    # The midpoint lookup's right height is a doubled index below 400.
    # Its remaining 112 bytes per row are not read by the renderer.
    from fixed_art import split
    static = [(lo, hi, name) for a, b, name in static
              for lo, hi in (split([(a, b)], memmap.midpoint_art_ranges())[0]
                             if name == 'build/assets/ray-midpoint.bin' else [(a, b)])]
    wall_paint = (memmap.WALL_PAINT, memmap.WALL_PAINT_END, 'wall painter')
    assert all(not overlap(wall_paint, row) for row in boot), 'boot load overlaps wall painter'
    runtime = [wall_paint,
               (memmap.DRAW_BUFFER, memmap.DRAW_BUFFER_END, 'draw buffer'),
               (memmap.PAINT_STACK, memmap.LOADER, 'deferred paint stack'),
               (memmap.SHORT_LIGHT_MAPS, memmap.SHORT_LIGHT_SPARE, 'sixteen short-light horizontal maps'),
               (memmap.SEG_LOGIC_END, (memmap.LOGIC_CODE+0x5c00), 'visibility region IDs'),
               (memmap.SPRITE_SCRATCH, memmap.SPRITE_SCRATCH_END, 'projection and column scratch'),
               (memmap.SILHOUETTES, memmap.SILHOUETTES_END, 'projection silhouettes'),
               (memmap.LOGIC_BASE, memmap.LOGIC_ART_HOLE, 'logic state and active objects'),
               ((memmap.LOGIC_BASE+0xc000), memmap.SPRITE_CMDS, 'logic constants and floor configuration'),
               (memmap.VIS_STAMPS, memmap.RAY_SPAN_HEIGHT, 'visibility and wall cells'),
               (memmap.VIEW_WEIGHTS, (memmap.VIEW_WEIGHTS+0x3c0), 'active perspective weights'),
               (memmap.SIGHT_ROWS, memmap.THRUST_INDEX, 'sight rows and active doors'),
               (memmap.STATIC_INDEX, memmap.RAY_PARTIAL, 'static groups and object cells'),
               (memmap.SPR_RECORDS, (memmap.MENU_FRAME+0x4a00), 'sprite projections and history'),
               (memmap.HEIGHT_TABLE, memmap.SPARE_3D, 'selected view heights'),
               (memmap.DISPLAY_BACKUP, memmap.MENU, 'firmware display backup'),
               (memmap.FWSTATE, memmap.FWSTATE_END, 'firmware state'),
               (memmap.MENU_CACHE_2, (memmap.SLOW_RAM+0x9d00), 'slow word cache'),
               (memmap.FRONTEND_FONT, (memmap.SLOW_RAM+0xaea8), 'slow small font'),
               (memmap.PALBUF, (memmap.SLOW_RAM+0xb200), 'death palette'),
               (memmap.RAW_PLANES, (memmap.BANK_E1+0xc000), 'original map planes')]
    # Floor rows replace only the local gray lookup windows, never the
    # shared index or resident conversion code.
    gray = [(memmap.GRAY_BASE, memmap.GRAY_RECS, 'shared gray index'),
            (memmap.GRAY_FLOOR, memmap.MENU_CACHE_8, 'floor/page gray windows')]
    protected = static + runtime + gray
    bounds(protected)
    checked = []
    for floor in range(PROFILE.floors):
        art = spans(art_rows(floor))
        effects = spans(read_rows(ROOT/f'build/sound/effects-floor-{floor:02}-loads.json', ROOT/'build/sound'))
        disjoint(art + effects)
        # Raw effects write whole sectors from their own start address,
        # which need not itself be sector-aligned.
        padded_effects = [(a, a + ((b-a+511) & ~511), name) for a, b, name in effects
                          if memmap.SFX_BASE <= a < memmap.SFX_BASE_END]
        for a in art:
            for b in padded_effects:
                assert not overlap(a, b), (floor, a, b, 'raw effect padding')
        for a in art + effects:
            for b in protected:
                assert not overlap(a, b), (floor, a, b)
        for view in range(4):
            weights = json.loads((ASSETS/'view-weight-loads.json').read_text())[view]
            weapons = json.loads((ROOT/f'build/levels/{floor}/view-weapon-loads.json').read_text())[view]
            disjoint(art + effects + spans(weights + weapons) + [wall_paint])
        checked.append(dict(floor=floor, art_bytes=sum(b-a for a,b,_ in art)))
    return dict(floors=checked, fast_ram_last_bank='41', resident_lights=4,
                boot_spans=len(boot), protected_game_spans=len(protected), selected_views=4)


def art(floor):
    from check_palette_bindings import check
    check(ROOT, [floor])
    folder = ROOT/f'build/levels/{floor}'
    image = bytearray(memmap.FAST_RAM_END)
    loads = art_rows(floor)
    for row in loads:
        raw = (ROOT/row['file']).read_bytes()
        image[row['address']:row['address']+len(raw)] = raw
    receipt = json.loads((ROOT/f'build/palettes/{floor}.json').read_text())
    # Synthetic floor-pool strips use reserved source indices populated by
    # the existing coverage converter, including a constant floor gray.
    sprite_lights = json.loads((folder/'pool-colors.json').read_text())
    lights = (sprite_lights, receipt['wall_lights'])
    tables = [[(bytes(pair[0] for pair in row), bytes(pair[1] for pair in row))
               for row in kind] for kind in lights]
    @lru_cache(maxsize=8192)
    def mapped(raw, kind, light):
        a, b = tables[kind][light]
        result = bytearray(2*len(raw))
        result[::2], result[1::2] = raw.translate(a), raw.translate(b)
        return bytes(result)
    frames = json.loads((folder/'sprites.json').read_text())
    offsets = struct.unpack('<%dH'%((folder/'spriteFrame.bin').stat().st_size//2), (folder/'spriteFrame.bin').read_bytes())
    actors, objects, weapons = shapes(maps()[floor])
    from sprite_simplify import mirror_shape
    from wolf_source import sprite_ids
    mirrored = mirror_shape()
    aliases = {len(sprite_ids())} if mirrored in objects else set()
    assert set(map(int, frames)) == actors | objects | weapons | aliases
    for alias in aliases:
        assert frames[str(alias)]['mirror_of'] == mirrored
        normal = memmap.SPRITE_CMDS + offsets[mirrored]
        companion = memmap.SPRITE_CMDS + offsets[alias]
        assert image[normal:normal+202] == image[companion:companion+202]
    pages, base, _ = vswap()
    comparisons = 0
    for shape_text, host in frames.items():
        shape = int(shape_text)
        frame = memmap.SPRITE_CMDS + offsets[shape]
        source = sprite(pages[base+host.get('mirror_of', shape)])
        assert image[frame+FRAME_LEFT:frame+FRAME_LEFT+2] == bytes((source['left'], source['right']))
        thresholds = [max((min(b,64-a) for a,b,_ in col), default=0) for col in source['columns']]
        for cut in range(32):
            used = [x for x,limit in enumerate(thresholds, source['left']) if limit>cut]
            expected = bytes((min(used), max(used))) if used else bytes((64,0))
            assert image[frame+FRAME_CLIP+cut*2:frame+FRAME_CLIP+cut*2+2] == expected
        if host['weapon']:
            continue
        command_bank = struct.unpack_from('<H', image, frame+FRAME_COMMAND_BANK)[0]
        assert command_bank < 0x42
        for x, column in enumerate(host['columns']):
            pointer = command_bank*65536 + struct.unpack_from('<H', image, frame+x*2)[0]
            for start, stop, raw in sorted(column, reverse=True):
                assert image[pointer:pointer+2] == bytes((start, stop))
                for light in range(4):
                    offset = struct.unpack_from('<H', image, pointer+2+light*2)[0]
                    bank = image[frame+FRAME_LIGHT_BANKS+light]
                    at = bank*65536 + offset + (start*2 if start<200 else 0)
                    expected = mapped(bytes(raw), 0, light)
                    assert at>>16 == (at+len(expected)-1)>>16
                    assert image[at:at+len(expected)] == expected, (floor, shape, x, light)
                    comparisons += 1
                pointer += 10
            assert image[pointer:pointer+2] == b'\0\0'
    # Every page the renderer draws must be loaded; check every page the floor loads.
    import fixed_art
    meta = folder/'fixed.json'
    wall_pages = set(json.loads(meta.read_text()).get('wall_pages') or fixed_art.wall_pages(floor)) if meta.exists() \
        else set(fixed_art.wall_pages(floor))
    drawn = set(fixed_art.wall_pages(floor))
    assert drawn <= wall_pages, (floor, sorted(drawn - wall_pages))
    for page in sorted(wall_pages):
        if len(pages[page]) != 4096: continue
        for x in range(64):
            token, page_id = struct.unpack_from('<2H', image, memmap.WALL_COLUMNS+page*256+x*4)
            assert page_id == page<<8 and token%16 == 0
            raw = pages[page][x*64:(x+1)*64]
            for light in range(4):
                offset, bank = struct.unpack_from('<2H', image, memmap.WALL_LIGHT_POINTERS+token+light*4)
                assert bank & 255 == 0
                at = (bank << 8) + offset
                expected = mapped(raw, 1, light)
                assert at>>16 == (at+127)>>16
                assert image[at:at+128] == expected, (floor, page, x, light)
                comparisons += 1
    return dict(floor=floor, frames=len(frames), exact_mapped_runs=comparisons)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory-only', action='store_true')
    args = parser.parse_args()
    report = dict(memory=memory())
    if not args.memory_only:
        report['art'] = []
        for floor in range(PROFILE.floors):
            report['art'].append(art(floor))
            print('Checked original art and four lights for floor', floor+1, flush=True)
    (ROOT/'build/registered-assets-check.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Registered asset checks passed.')


if __name__ == '__main__': main()
