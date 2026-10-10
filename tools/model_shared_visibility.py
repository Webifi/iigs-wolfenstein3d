"""Audit native wall-cast actor coverage on both widths' slowest frames.

The reference wall build stamps empty cells only when an object needs them.
This fixture marks every empty cell, matching the shared-cast runtime's floor
stamps. Full door, pushwall and adaptive-span code executes. Coverage is a
visibility model, not a rendered-picture verdict or a MAME timing.
"""
import argparse
import json
from pathlib import Path
import struct

from check_sight_cast import image
import wolfsim as w


class Cast:
    def __init__(self, view, elf):
        self.e, self.symbols = e, s = image(elf)
        # View setup clips the floor's sprite endpoints from this record.
        world=s.get('LOGICBANK',0x28)<<16
        self.world=world
        build=elf.resolve().parent if (elf.resolve().parent/'assets').is_dir() else Path('build')
        e.load(world+65536,(build/'levels/0/spritecmd.bin' if (build/'levels').is_dir() else build/'assets/spritecmd.bin').read_bytes())
        e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
        # Memory starts zeroed; skip only zero fill and eager warmup. Lazy
        # ray-page expansion still executes the real code, including MVN.
        if 'rpWarm' in s:e.wr16(s['rpWarm'], 1)
        if 'rpIndex' in s:e.wr16(s['rpIndex'], 65535)  # no view directory exists in this fresh fixture
        e.call(2, s['InitRayTextureDirectory'] & 65535, sentinel=0x2ffef)
        e.wr16(s['screenHold'], 1)
        e.a = {160: 0, 214: 1, 240: 2, 320: 3}[view]
        e.call(2, s['setView'] & 65535, sentinel=0x2ffef)

    def cast(self, game):
        e, s = self.e, self.symbols
        e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
        grid = [(tile if tile & 128 else tile & 63) or 0x8000 for tile in game.tilemap]
        e.load(self.world+0x32000, struct.pack('<4096H', *grid))
        for i, door in enumerate(game.doors):
            e.wr16(s['doorOrient']+2*i, int(door['vertical']))
            e.wr16(s['doorPosition']+2*i, game.doorposition[i] >> 8)
        e.wr16(s['pwallPosition'], game.pwallpos*4)
        angle = e.rd16(self.world+s['DEG1024']+2*game.player.angle)
        for name, value in (('PX', game.player.x >> 8), ('PY', game.player.y >> 8),
                            ('ANGLE', angle), ('FIRST', 1)):
            e.wr16(0x1000+s[name], value)
        e.call(2, s['castFrame'] & 65535, sentinel=0x2ffef)
        stamp = e.rd16(0x1000+s['VISSTAMP'])
        return {i for i in range(4096) if e.rd16(self.world+0x30000+2*i) == stamp}


def coverage(game, seen):
    old = {i for i, value in enumerate(game.spotvis) if value}
    missing, extra = [], []
    actor = game.player.next
    while actor:
        if actor.state.shapenum:
            cell = actor.tilex*64+actor.tiley
            target = {cell} | {cell+i for i in (-1, 1, -65, -64, -63, 65, 64, 63)
                              if not game.tilemap[cell+i]}
            if old & target and not seen & target:
                missing.append(actor.index)
            if seen & target and not old & target:
                extra.append(actor.index)
        actor = actor.next
    return dict(frame=game.frame, missing=missing, extra=extra)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', type=Path, required=True)
    ap.add_argument('--prefix', default='astra13-corpse')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    results = []
    for demo in range(4):
        chosen = {}
        for view in (214, 320):
            path = Path(f'build/tests/{args.prefix}-{view}-{demo}/measure.json')
            timing = json.loads(path.read_text())['frame_times']
            chosen[view] = {r['frame'] for r in sorted(timing, key=lambda r: -r['ns'])[:20]}
        rigs = {view: Cast(view, args.elf) for view in chosen}
        rows = {view: [] for view in chosen}
        data = w.demo_chunks()[demo]
        game = w.Game(data['mapon'], viewwidth=240)
        game.ray_columns = list(range(4, 240, 8))
        packets = data['data']
        for offset in range(0, len(packets)-len(packets) % 3, 3):
            buttons, cx, cy = packets[offset:offset+3]
            if offset+3 == len(packets):
                game.playstate = w.EX_COMPLETED
            game.play_frame(buttons, cx-256 if cx > 127 else cx, cy-256 if cy > 127 else cy)
            for view, frames in chosen.items():
                if game.frame in frames:
                    rows[view].append(coverage(game, rigs[view].cast(game)))
            if game.playstate:
                break
        for view, samples in rows.items():
            assert {r['frame'] for r in samples} == chosen[view]
            row = dict(demo=demo, view=view, missing=sum(len(r['missing']) for r in samples),
                       extra=sum(len(r['extra']) for r in samples), frames=samples)
            results.append(row)
            print({k: v for k, v in row.items() if k != 'frames'}, flush=True)
    args.out.write_text(json.dumps(dict(elf=str(args.elf), prefix=args.prefix, cases=results), indent=2)+'\n')


if __name__ == '__main__':
    main()
