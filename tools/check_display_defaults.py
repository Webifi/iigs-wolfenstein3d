"""Native MAME checks for automatic view/Fast walls and independent saved painting choices.

Use --baseline to record the old defaults without asserting new behavior.
AppleSqueezer cases use the emulated card at its default 14 MHz, with its
normal DOC slowdown. No presence-byte or timing fixtures are installed.
Select a MAME build with apple2gs1as/apple2gsas through WOLF_MAME.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import check_view_default as v

v.MODELS['zip8'] = [('a2_config', 7, 0, 3), ('bus_timing', 6, 6, 4)]
v.MODELS['twgs12'] = [('a2_config', 7, 0, 5), ('bus_timing', 6, 6, 4),
                      ('bus_timing', 1024, 0, 1024), ('bus_timing', 2048, 0, 2048),
                      ('bus_timing', 4096, 0, 0), ('twgs_rom', 1, 0, 1)]
# The real ROM resets IRQ logic to CARD even when this startup port requests Off.
v.MODELS['twgs12-portoff'] = [(tag, mask, default, 4096 if mask == 4096 else value)
                         for tag, mask, default, value in v.MODELS['twgs12']]
for model, cpu in (('twgs7', 1), ('twgs8', 3)):
    v.MODELS[model] = [(tag, mask, default, cpu if tag == 'a2_config' else value)
                       for tag, mask, default, value in v.MODELS['twgs12']]
v.MODELS['twgs7-8k'] = [(tag, mask, default, 0 if mask == 2048 else value)
                         for tag, mask, default, value in v.MODELS['twgs7']]
v.MODELS['twgs12-rom3'] = v.MODELS['twgs12']
v.MACHINES['twgs12-rom3'] = ('apple2gs', '5M')  # Wolf requires more than 4 MB total
for model, machine in (('as-rom1', 'apple2gs1as'), ('as-rom3', 'apple2gsas')):
    v.MODELS[model] = []
    v.MACHINES[model] = (machine, '14M')
MODELS = ('stock', 'zip7', 'zip8', 'zip12', 'twgs7', 'twgs7-8k', 'twgs8', 'twgs12', 'twgs12-portoff', 'twgs12-rom3', 'as-rom1', 'as-rom3')

down = ['key=Down', 'sleep=0.3']
save = v.SAVE_ROOT + v.SAVE + ['end=']
v.FLOWS['paint-buffered'] = v.TO_OPTIONS + down * 5 + ['key=Right', 'sleep=0.5'] + save
v.FLOWS['paint-back'] = v.TO_OPTIONS + down * 5 + ['key=Right', 'sleep=0.5', 'key=Left', 'sleep=0.5'] + save
v.FLOWS['walls-off'] = v.TO_OPTIONS + down * 6 + ['key=Right', 'sleep=0.5'] + save
v.FLOWS['walls-back'] = v.TO_OPTIONS + down * 6 + ['key=Right', 'sleep=0.5', 'key=Left', 'sleep=0.5'] + save
v.FLOWS['view-back'] = v.TO_OPTIONS + down * 2 + ['key=Right', 'sleep=0.5', 'key=Left', 'sleep=0.5'] + save
v.FLOWS['play'] = v.NEW_GAME + ['snap=play', 'end=']
v.FLOWS['keys-back'] = v.NEW_GAME + ['key=Equals', 'waitframes=2', 'key=Minus', 'waitframes=2'] + v.SAVE_GAME

cases = {}
def add(name, model, view=255, paint=255, walls=255, *, fresh=False, flow=None, source=None, **want):
    kind, size, enabled = (1, 1, 0) if model == 'stock' else (3, 3, 1) if model.startswith('as-') or model == 'twgs8' else (2, 2, 1)
    settings = 'disk' if source else 'fresh' if fresh else dict(view=view, paint=paint, walls=walls)
    expected = dict(ran=view >= 4 or walls == 255, size=size, view=(size if view >= 4 else view)*2,
                    paint=paint if paint < 2 else 0, walls=enabled if walls == 255 else walls >> 2,
                    kind=kind, sview=view, spaint=paint, swalls=walls)
    expected.update(want)
    cases[name] = (model, settings, flow, source, expected)

for model in MODELS:
    add('fresh-'+model, model, fresh=True)
for model in ('twgs7', 'twgs7-8k', 'twgs8', 'twgs12', 'twgs12-portoff'):
    add('seiflag-'+model, model, fresh=True, flow='seiflag', sei=True)
for model in ('stock', 'zip7', 'twgs7-8k', 'zip12', 'twgs12', 'as-rom1'):
    add('explicit-view-'+model, model, view=0)
    add('both-explicit-'+model, model, view=3, paint=1)
    for paint in (0, 1):
        for walls in (4, 2):
            add(f'independent-p{paint}-w{walls}-{model}', model, view=1, paint=paint, walls=walls)
add('shade-stock', 'stock', fresh=True, flow='shade', disk=(255, 0), disk_paint=255, disk_walls=255)
add('shade-on-zip12', 'zip12', source='shade-stock', shade=0)
add('paint-buffered-zip12', 'zip12', fresh=True, flow='paint-buffered', spaint=1, disk_paint=1, disk_walls=255)
cases['paint-buffered-zip12'][4]['paint'] = 1
add('buffered-auto-on-stock', 'stock', paint=1, walls=255, source='paint-buffered-zip12')
add('paint-back-zip12', 'zip12', fresh=True, flow='paint-back', spaint=0, disk_paint=0, disk_walls=255)
add('paint-back-on-stock', 'stock', paint=0, walls=255, source='paint-back-zip12')
add('walls-off-zip12', 'zip12', fresh=True, flow='walls-off', swalls=2, disk_walls=2)
# The option change happens after the probe: it must not suppress that probe.
cases['walls-off-zip12'][4]['walls'] = 0
add('walls-off-again-zip12', 'zip12', walls=2, source='walls-off-zip12')
add('walls-back-zip12', 'zip12', fresh=True, flow='walls-back', swalls=4, disk_walls=4)
add('walls-back-on-stock', 'stock', walls=4, source='walls-back-zip12')
add('view-back-zip12', 'zip12', fresh=True, flow='view-back', sview=2, disk=(2, 1), disk_paint=255, disk_walls=255)
add('view-back-on-stock', 'stock', view=2, source='view-back-zip12')
add('keys-back-stock', 'stock', fresh=True, flow='keys-back', sview=1, disk=(1, 1), disk_paint=255, disk_walls=255)
add('keys-back-on-zip12', 'zip12', view=1, source='keys-back-stock')
for model in MODELS:
    add('play-'+model, model, fresh=True, flow='play')
for model in ('zip7', 'twgs7-8k', 'twgs12', 'as-rom1'):
    add('play-buffered-'+model, model, paint=1, flow='play')
for model in ('zip7', 'twgs7-8k'):
    add('walls-off-'+model, model, fresh=True, flow='walls-off', swalls=2, disk_walls=2)
    cases['walls-off-'+model][4]['walls'] = 0
    add('walls-off-again-'+model, model, walls=2, source='walls-off-'+model)
for model in ('stock', 'zip7', 'twgs7-8k'):
    add('inject-'+model, model, fresh=True, flow='inject')
add('invalid-paint-zip12', 'zip12', paint=128)
v.CASES = cases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf', type=Path, required=True)
    p.add_argument('--disk', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--prefix', default='display-defaults')
    p.add_argument('--only', nargs='+')
    p.add_argument('--baseline', action='store_true')
    a = p.parse_args()
    a.seconds, a.steps = 100, None
    result = dict(elf_sha256=hashlib.sha256(a.elf.read_bytes()).hexdigest(),
                  disk_sha256=hashlib.sha256(a.disk.read_bytes()).hexdigest(),
                  mame_sha256=hashlib.sha256(Path(v.MAME).read_bytes()).hexdigest(), cases={})
    for name in a.only or cases:
        model = cases[name][0]
        r = v.run_case(a.prefix, name, a)
        bad = v.check(r, name, a.baseline)
        if r.get('final', {}).get('why') == 'timeout': bad.append('timed out')
        want = cases[name][4]
        if not a.baseline:
            for k in ('paint', 'sview', 'spaint', 'walls', 'swalls'):
                if r.get('display', {}).get(k) != want[k]: bad.append(f'{k}: wanted {want[k]}, got {r.get("display")}')
            if want['ran'] and r.get('exit', {}).get('kind') != want['kind']: bad.append('wrong class')
            if want['ran']:
                if not r.get('exit', {}).get('A') or not r.get('exit', {}).get('B'):
                    bad.append('timing loops did not both run')
                entry, restored = r.get('entry', {}), r.get('restored', {})
                for field in ('P', 'DB', 'D', 'S', 'dp'):
                    if entry.get(field) != restored.get(field): bad.append('probe did not restore '+field)
                if restored.get('dpbad') != 0: bad.append('firmware direct page bytes changed')
                if restored.get('cardwrites') != 0: bad.append('probe wrote to the accelerator card')
                for state in ('measuring', 'measureb'):
                    if r.get(state, {}).get('P', 4) & 4: bad.append('CPU IRQs masked during '+state)
                if model.startswith('twgs'):
                    for state in ('measuring', 'measureb', 'restored'):
                        if r.get(state, {}).get('tw', 0) & 254 != entry.get('tw', 0) & 254:
                            bad.append('TWGS configuration changed at '+state)
                    if entry.get('tw', 0) & 8: bad.append('TWGS CARD setting not active on entry')
                if restored.get('stackmin', 0) < 0x1200: bad.append('probe exceeded game stack')
            if name.startswith('play-'):
                display = r.get('display', {})
                if display.get('frames', 0) < 2: bad.append('no completed gameplay frames')
                if display.get('width') != (160, 214, 240, 320)[want['size']]: bad.append('wrong rendered width')
                if display.get('wallpath') != want['walls']: bad.append('wrong active painter')
            if 'disk_paint' in want and (r['disk_paint'] != want['disk_paint'] or not r['disk_checksum_valid']):
                bad.append('saved Painting/checksum mismatch')
            if 'disk_walls' in want and (r['disk_walls'] != want['disk_walls'] or not r['disk_checksum_valid']):
                bad.append('saved Fast walls/checksum mismatch')
        r['failures'] = bad
        result['cases'][name] = r
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2)+'\n')
        print(name, json.dumps({k:r.get(k) for k in ('exit','boot','display','disk_sview','disk_paint','disk_walls','failures')}), flush=True)
    sys.exit(any(r['failures'] for r in result['cases'].values()))

if __name__ == '__main__':
    main()
