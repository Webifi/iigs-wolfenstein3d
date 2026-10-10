"""Load a floor through the real checkpoint menu and verify its native assets.

A private disk's WOLF.SETTINGS checkpoint supplies starting stats. This loader
fixture bypasses the later mutable-world restore; full saves are tested by
check_saved_world.py. Every floor record still uses the shared native loader.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import shutil
from elf import read
import music_capture

ROOT = Path(__file__).resolve().parents[1]


def checkpoint(source, out, floor):
    data = bytearray(source.read_bytes())
    if len(data) <= 800 * 1024:
        raise ValueError('this checkpoint route currently requires the complete hard disk image')
    settings = bytearray(512)
    settings[:8] = b'WOLFSET\x02'
    settings[12:16] = bytes((1, 1, 1, 5))
    sections, symbols = read(ROOT / 'build/wolf.elf')
    keys = symbols['boundKeys']
    for section in sections:
        address, payload = section['address'], section['data']
        if address <= keys and keys + 40 <= address + len(payload):
            settings[32:52] = payload[keys-address:keys-address+40:2]
            break
    else:
        raise ValueError('default controls missing from ELF')
    # frontend.inc: floor-start checkpoint, pistol and untouched starting stats.
    values = (1, 3, floor, 3, 100, 8, 1, 1, 1, 0, 0, 40000, 0, 0, 0)
    struct.pack_into('<16H', settings, 232, *values, sum(values) & 0xffff)
    struct.pack_into('<H', settings, 8, sum(settings[12:496]) & 0xffff)
    block = struct.unpack_from('<H', data, 512 + 436)[0]
    assert 0 < block < len(data)//512
    data[block*512:(block+1)*512] = settings
    fixture = out / 'checkpoint-source.po'
    fixture.write_bytes(data)
    if data[512:518] == b'WOLFGS' and data[519] == 2:
        companion = source.with_name(source.stem+'2'+source.suffix)
        shutil.copyfile(companion, fixture.with_name(fixture.stem+'2'+fixture.suffix))
    return fixture


def checkpoint_lua():
    """Keep stat-only loader fixtures separate from complete saved-world proofs."""
    _, symbols = read(ROOT / 'build/wolf.elf')
    if 'LoadWorldRead' in symbols:
        # ui_save.s RestoreSlot reads the world file before the floor (gamesave.s
        # LoadWorldRead) and puts it in after (LoadWorldApply). This fixture has no
        # world file: both return carry clear at once (CLC; RTL) and StartFloor
        # builds the fresh floor.
        return r"""
checkpointTap=mem:install_read_tap(@START@,@START@,"checkpoint-floor-only",function()
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=@BANK@ then return end
 mem:write_u16(@READ@,0x6b18)
 mem:write_u16(@APPLY@,0x6b18)
 print('CHECKPOINT_WORLD_BYPASS')
end)
""".replace('@START@', str(symbols['RestoreSlot'])).replace('@BANK@', str(symbols['RestoreSlot'] >> 16)).replace(
            '@READ@', str(symbols['LoadWorldRead'])).replace('@APPLY@', str(symbols['LoadWorldApply']))
    if 'LoadWorld' not in symbols:
        return ''
    return r"""
checkpointTap=mem:install_read_tap(@START@,@START@,"checkpoint-floor-only",function()
 if manager.machine:side_effects_disabled() or cpu.state.PB.value~=@BANK@ then return end
 -- StartFloor still loads/initializes the native floor. This fixture has no
 -- saved mutable world; its near LoadWorld bridge returns carry clear.
 mem:write_u16(@LOAD@,0x6018)
 print('CHECKPOINT_WORLD_BYPASS')
end)
""".replace('@START@',str(symbols['UiStartSavedFloor'])).replace('@BANK@',str(symbols['UiStartSavedFloor']>>16)).replace('@LOAD@',str(symbols['LoadWorld']))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('floor', type=int, choices=range(10), help='zero-based floor index')
    ap.add_argument('--disk', type=Path, default=ROOT / 'build/wolf-hd.po')
    ap.add_argument('--machine', choices=('apple2gsr1', 'apple2gs'), default='apple2gsr1')
    ap.add_argument('--name', help='retain a separately named regression run')
    ap.add_argument('--check-loading-music', action='store_true',
                    help='verify the music player runs while native floor art expands')
    args = ap.parse_args()
    source = args.disk.resolve(strict=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    name = args.name or 'native-floor%d-%s' % (args.floor, args.machine)
    out = ROOT / 'build/tests' / name
    out.mkdir(parents=True, exist_ok=True)
    fixture = checkpoint(source, out, args.floor)
    (out/'observe.lua').write_text(checkpoint_lua() + music_capture.lua() +
                                 (music_capture.art_lua() if args.check_loading_music else ''))
    command = [sys.executable, str(ROOT/'tools/ui_test.py'), '--name', name,
               '--disk', str(fixture), '--hd', '--machine', args.machine,
               '--check-floor', str(args.floor), '--seconds', '200', '--lua', str(out/'observe.lua'), '--steps',
               'wait=1;sleep=1;key=Esc;wait=2;sleep=0.4;key=Down;key=Return;wait=4;sleep=0.4;key=Return;wait=0;sleep=4;snap=loaded;end=']
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=540)
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    if result.returncode:
        raise SystemExit(result.returncode)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    songs=music_capture.events((out/'mame.log').read_text())
    expected=(3,11,9,12,3,11,9,12,2,0)[args.floor]
    assert [s['song'] for s in songs]==[7,expected],songs
    art=music_capture.art_events((out/'mame.log').read_text())
    if args.check_loading_music:
        assert art and art[-1]['floor']==args.floor and art[-1]['song']==expected,art
        assert art[-1]['active']==1 and art[-1]['interrupts_enabled'] and art[-1]['music_wakes']>0,art
    evidence = dict(floor=args.floor, machine=args.machine, disk_sha256=source_hash,
                    fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    method=__doc__,
                    asset_checks=json.loads((out/'asset-checks.json').read_text()),
                    song_starts=songs,glu_violations=0,art_music=art,
                    log=(out/'mame.log').read_text())
    (out/'result.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print('Evidence:', out/'result.json')


if __name__ == '__main__':
    main()
