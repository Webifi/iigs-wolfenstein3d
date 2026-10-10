"""Execute the registered overlay controller with instrumented loader fixtures.

The actual assembled controller and its SHR copies run in Emu816. Disk reads
are fixtures; this does not claim firmware, integrated art or frame timing QA.
"""
import memmap
import argparse
import json
from pathlib import Path
import subprocess

from elf import read
from emu816 import Emu


class Halted(Exception):
    pass


class Bench(Emu):
    def __init__(self, executable):
        super().__init__()
        self.extra_p = 0
        segments, self.sym = read(executable)
        for segment in segments:
            self.load(segment['address'], segment['data'])
        self.loads = []
        self.fail = None
        self.screen = bytes((i * 29 + 3) & 255 for i in range(0x8000))
        self.load(memmap.SHR, self.screen)
        self.raw = bytes((i * 13 + 7) & 255 for i in range(8192))
        self.load(memmap.RAW_PLANES, self.raw)
        self.slow = bytes((i * 11 + 1) & 255 for i in range(0x8eff))
        self.load(memmap.MENU_CACHE_2, self.slow)

    def getp(self):
        return super().getp() | self.extra_p

    def setp(self, p):
        self.extra_p = p & 12
        super().setp(p)

    def rtl(self):
        self.pc = (self.pop16() + 1) & 65535
        self.pb = self.pop8()

    def step(self):
        pc = self.pb << 16 | self.pc
        if pc == self.sym['OverlayHalted']:
            raise Halted()
        if pc == self.sym['LoadAuxData']:
            group = self.a
            self.loads.append(group)
            # Model firmware display damage and B1's bank-$1D staging write.
            self.load((memmap.SHR+0x6200), bytes([0xcc]) * 0x1e00)
            self.load(memmap.BOOT_STAGE, bytes([0xdd]) * 65536)
            if 245 <= group < 305:
                # The group's final raw bank-$1D record repairs the staging.
                self.load(memmap.BOOT_STAGE, bytes([group - 245]) * 65536)
            self.wr16(self.sym['overlayGameCold'], 1)
            self.a, self.x, self.y = 0xdead, 0xbeef, 0xcafe
            self.c = int(group == self.fail)
            self.rtl()
            return
        if pc == self.sym['UiFwKeep']:
            # The real helper preserves P but changes A/X/Y through MVN.
            self.a, self.x, self.y = 0xffff, 0x1000, 0xfc00
            self.rtl()
            return
        opcode = self.rd8(pc)
        if opcode in (0x58, 0x78, 0xd8, 0xf8):
            if opcode == 0x58:
                self.extra_p &= ~4
            elif opcode == 0x78:
                self.extra_p |= 4
            elif opcode == 0xd8:
                self.extra_p &= ~8
            else:
                self.extra_p |= 8
        super().step()

    def invoke(self, name, a=0x1357, flags=0xcf):
        self.a, self.x, self.y = a, 0x1234, 0x5678
        self.d, self.db, self.s = 0x1100, 2, 0x1fff
        self.setp(flags)
        state = (self.a, self.x, self.y, self.d, self.db, self.s, self.getp())
        address = self.sym[name]
        self.call(address >> 16, address & 65535, long_return=True)
        assert state == (self.a, self.x, self.y, self.d, self.db, self.s, self.getp()), name
        assert bytes(self.m[memmap.SHR:memmap.RAW_PLANES]) == self.screen, name
        assert bytes(self.m[memmap.RAW_PLANES:(memmap.BANK_E1+0xc000)]) == self.raw, name
        assert bytes(self.m[memmap.MENU_CACHE_2:(memmap.SLOW_RAM+0xaeff)]) == self.slow, name


def build(root, out, assembler, linker):
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / 'fixture.s'
    fixture.write_text('''              .section testcode, text, root
              .public LoadAuxData, UiFwKeep, ProbeFloorData
LoadAuxData:  rtl
UiFwKeep:     rtl
ProbeFloorData: .byte 0xdb
              .section testdata, data, root
              .public levelIndex, weaponViewIndex
levelIndex:   .word 0
weaponViewIndex: .word 2
''')
    (out / 'overlay_groups.inc').write_text('AUX_WEIGHTS_BASE .equ 0\nAUX_WEAPONS_BASE .equ 4\nAUX_UI .equ 244\nAUX_GAME_BASE .equ 245\nAUX_DEMOS_BASE .equ 305\n')
    # Use a controlled profile header so stale generated headers cannot make
    # this a successful test of an empty #if WOLF_REGISTERED branch.
    (out / 'logic.inc').write_text('#define WOLF_REGISTERED 1\n')
    (out / 'campaign.inc').write_text('CAMPAIGN_FLOORS .equ 60\n')
    layout = out / 'test.scm'
    layout.write_text('''(define memories '(
(memory Overlays (address (#x3f0000 . #x3f1fff)) (section registeredmenu))
(memory Fixture (address (#x000800 . #x0008ff)) (section testcode))
(memory State (address (#x028000 . #x0280ff)) (section testdata))))
''')
    objects = []
    for source in (root / 'src/iigs/ui_overlays.s', fixture):
        obj = out / (source.stem + '.o')
        subprocess.run([assembler, '--code-model=large', '--data-model=medium', '-I', str(out),
                        '-o', str(obj), str(source)], check=True)
        objects.append(str(obj))
    executable = out / 'overlays.elf'
    subprocess.run([linker, '-o', str(executable), str(layout), *objects, '--hosted'], check=True)
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assembler', default='as65816')
    parser.add_argument('--linker', default='ln65816')
    parser.add_argument('--out', type=Path, default=Path('build/ui-overlay-check'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    exe = build(root, args.out.resolve(), args.assembler, args.linker)
    b = Bench(exe)
    b.invoke('EnsureUIAssets')
    assert b.loads == []
    # Every floor/view key, followed by a warm frame/restore request.
    cases = 0
    for floor in range(60):
        b.invoke('OverlayFloorChanging')
        b.wr16(b.sym['levelIndex'], floor)
        for view in range(4):
            b.wr16(b.sym['weaponViewIndex'], view * 2)
            before = len(b.loads)
            b.invoke('EnsureViewAssets', view)
            assert b.loads[before:] == [view, 4 + floor * 4 + view, 245 + floor]
            assert b.m[memmap.BOOT_STAGE:memmap.BOOT_STAGE_END] == bytes([floor]) * 65536
            b.invoke('EnsureGameplayAssets')
            assert len(b.loads) == before + 3, 'warm game performed disk I/O'
            cases += 1
        before = len(b.loads)
        b.invoke('EnsureUIAssets')
        assert b.loads[before:] == [244]
        snapshot = bytes([0x8a]) * 32000
        b.load(memmap.SNAP_PIX, snapshot)
        for _ in range(4):
            b.invoke('EnsureUIAssets')
        assert b.m[memmap.SNAP_PIX:memmap.SNAP_PIX_END] == snapshot
        assert len(b.loads) == before + 1, 'warm UI performed disk I/O'
        b.invoke('EnsureGameplayAssets')
        assert b.loads[-3:] == [3, 4 + floor * 4 + 3, 245 + floor]
        before = len(b.loads)
        b.invoke('OverlayB1Clobbered')
        b.invoke('EnsureGameplayAssets')
        assert b.loads[before:] == [245 + floor], 'B1 repair reloaded unchanged views'
    for demo in range(4):
        b.invoke('LoadDemoAssets', demo)
        assert b.loads[-1] == 305+demo
        b.invoke('EnsureGameplayAssets')
        assert b.loads[-1] == 304
        assert b.m[memmap.BOOT_STAGE:memmap.BOOT_STAGE_END] == bytes([59])*65536
    # Exercise every native width/status combination on warm public calls.
    before = len(b.loads)
    for flags in range(256):
        b.invoke('EnsureGameplayAssets', flags=flags)
        b.invoke('OverlayB1Clobbered', flags=flags)
        b.wr16(b.sym['overlayGameCold'], 0)
    assert len(b.loads) == before
    for group, entry, a in [(244, 'EnsureUIAssets', 0), (0, 'EnsureViewAssets', 0),
                             (4, 'EnsureViewAssets', 0), (245, 'EnsureGameplayAssets', 0)]:
        failing = Bench(exe)
        failing.wr16(failing.sym['overlayUICold'], 1)
        failing.wr16(failing.sym['weaponViewIndex'], 0)
        failing.fail = group
        try:
            failing.invoke(entry, a)
        except Halted:
            assert failing.rd16(failing.sym['overlayFailedGroup']) == group
            assert failing.loads[-1] == group
            assert bytes(failing.m[memmap.SHR:memmap.RAW_PLANES]) == failing.screen
        else:
            raise AssertionError('failed overlay returned to a drawing caller')
    segments, symbols = read(exe)
    result = dict(floor_view_cases=cases, status_cases=256, load_failure_cases=4,
                  warm_ui_preserves_snapshot=True, raw_planes_preserved=True,
                  slow_words_and_steel_preserved=True, firmware_display_restored=True,
                  registered_bytes=sum(len(s['data']) for s in segments if s['address'] >> 16 == 0x3f),
                  scope=__doc__)
    (args.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
