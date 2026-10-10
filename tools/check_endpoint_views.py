"""Execute the assembled endpoint setup for every transition between views.

Compare all active rows with independent clamping of the original asset,
including synthetic floor pools, and verify every other endpoint-page byte.
This prices native setup instructions, not stock elapsed screen-change time.
"""
import memmap
import json
from pathlib import Path

from check_sight_cast import image
from viewgeometry import SIZES

ROOT = Path(__file__).resolve().parents[1]


def main():
    e, s = image(ROOT/'build/wolf.elf')
    if 'clipSpriteEndpoints' not in s:
        raise SystemExit('This check requires the endpoint view setup in the built game.')
    original = (ROOT/'build/assets/sprite-endpoints.bin').read_bytes()
    slots = list(range(65))+[200, 201, 202, 203]
    compact = bytes(original[p+t] for p in range(0, len(original), 256) for t in slots)
    for floor in range(10):
        commands = (ROOT/f'build/levels/{floor}/spritecmd.bin').read_bytes()
        assert commands[0xc000:0xc000+len(compact)] == compact, floor
        stats = json.loads((ROOT/f'build/levels/{floor}/sprite-stats.json').read_text())
        assert stats['shapes']*stats['frame_bytes'] <= 0xc000, floor
    e.load((memmap.OLD_SPRITE_CMDS+0xc000), commands[0xc000:0xfc28])
    results = []

    def run(view):
        top = (160-view)//2
        e.wr16(s['viewTop'], top)
        e.wr16(s['viewBottom'], top+view)
        e.d, e.db, e.mf, e.xf, e.s = 0x1000, 2, 0, 0, 0x1fff
        e.x = SIZES.index(view)*2
        before = e.cycles
        a = s['clipSpriteEndpoints']
        e.call(a >> 16, a & 65535, long_return=True, sentinel=memmap.TEST_RETURN)
        assert (e.db, e.mf, e.xf, e.s) == (2, 0, 0, 0x1fff)
        expected = bytearray(original)
        for page in range(0, len(original), 256):
            for tex in slots:
                expected[page+tex] = min(top+view, max(top, original[page+tex]))
        assert e.m[memmap.ENDPOINTS:memmap.ENDPOINTS+len(original)] == expected, view
        return e.cycles-before

    for previous in SIZES:
        for current in SIZES:
            e.wr16(s['endpointView'], 65535)
            run(previous)
            cycles = run(current)
            results.append(dict(previous=previous, current=current, cycles=cycles))
    result = dict(transitions=results, endpoint_bytes_per_view=len(compact),
                  compared_bytes=len(original)*32, differences=0,
                  command_bank_reserved_bytes=15400,
                  additional_asset_load_bytes=0)
    out = ROOT/'build/endpoint-views.json'
    out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
