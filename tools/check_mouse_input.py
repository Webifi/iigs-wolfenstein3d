"""Execute linked input arithmetic; check gains, report splitting and signs."""
import json
from pathlib import Path
from elf import read
from emu816 import Emu
from gen_mouse import TURN, MOVE

ROOT = Path(__file__).resolve().parents[1]
segments, symbols = read(ROOT / 'build/wolf.elf')
e = Emu()
for segment in segments:
    e.load(segment['address'], segment['data'])

def signed(n): return n - 65536 if n & 32768 else n

def call(name):
    a = symbols[name]
    e.call(a >> 16, a & 65535, long_return=True)

cases = 0
cycles = []
for speed in range(16):
    for dx in list(range(-65, 66)) + [-2047, -1000, -256, 256, 1000, 2047]:
        e.db = 2
        e.d = 0x1000
        e.wr16(symbols['mouseSensitivity'], speed)
        e.wr16(symbols['mouseWalk'], 1)
        e.wr16(symbols['mouseCountX'], dx)
        e.wr16(symbols['mouseCountY'], dx)
        e.wr16(symbols['mouseFracX'], 0)
        e.wr16(symbols['mouseFracY'], 0)
        before = e.cycles
        call('MouseControls')
        assert signed(e.x) == int(dx * TURN[speed] / 256), (speed, dx, signed(e.x), TURN[speed])
        assert signed(e.y) == int(dx * MOVE[speed] * 2 / 256), (speed, dx, signed(e.y), MOVE[speed])
        assert signed(e.x) * 256 + signed(e.rd16(symbols['mouseFracX'])) == dx * TURN[speed]
        assert signed(e.y) * 256 + signed(e.rd16(symbols['mouseFracY'])) == dx * MOVE[speed] * 2
        cycles.append(e.cycles-before)
        cases += 1
    for gesture in ([1]*100, [-1]*100, [1,-1]*50, [63,13,-5,-71], [10,0,0,-10]):
        e.wr16(symbols['mouseFracX'],0)
        e.wr16(symbols['mouseFracY'],0)
        total = 0
        for dx in gesture:
            e.wr16(symbols['mouseCountX'],dx)
            e.wr16(symbols['mouseCountY'],0)
            call('MouseControls')
            total += signed(e.x)
        assert total*256 + signed(e.rd16(symbols['mouseFracX'])) == sum(gesture)*TURN[speed], (speed,gesture,total,signed(e.rd16(symbols['mouseFracX'])),sum(gesture)*TURN[speed])
        cases += 1
for n in range(1024,32768,17):
    e.a=n
    e.db=0x28
    call('MouseAngleDivide')
    assert e.a==n//20
    assert e.db==0x28
    cases += 1
# Changing turn/strafe mode discards only the incompatible horizontal
# fraction, even when several zero reports precede the first moving report.
for speed in range(16):
    e.db=2;e.d=0x1000
    e.wr16(symbols['mouseSensitivity'],speed)
    e.wr16(symbols['mouseWalk'],0)
    e.wr16(0x104a,0)
    e.wr16(symbols['mouseCountX'],1);e.wr16(symbols['mouseCountY'],0)
    call('MouseControls')
    e.wr16(0x104a,64)
    for dx in (0,0,13):
        e.wr16(symbols['mouseCountX'],dx);e.wr16(symbols['mouseCountY'],dx)
        call('MouseControls')
    assert signed(e.x)*256+signed(e.rd16(symbols['mouseFracX']))==13*MOVE[speed]
    assert e.y==0 and e.rd16(symbols['mouseFracY'])==0
    cases+=1
# Invalid sensitivity values return to the default. Reserved bytes are untouched.
for reserved in (0,1,255):
    for stored in range(256):
        e.wr8(0x7c00+15,stored);e.wr8(0x7c00+20,reserved)
        e.wr16(symbols['mouseFracX'],123);e.wr16(symbols['mouseFracY'],42)
        call('MouseSettingsLoad')
        expected=stored if stored<16 else 4
        assert e.rd16(symbols['mouseSensitivity'])==expected
        assert e.rd16(symbols['mouseFracX'])==e.rd16(symbols['mouseFracY'])==0
        call('MouseSettingsStore')
        assert e.rd8(0x7c00+15)==expected and e.rd8(0x7c00+20)==reserved
        cases+=1
print(json.dumps({'cases':cases,'max_nominal_cycles_two_axes':max(cycles),'turn_q8':TURN,'move_q8':MOVE}))
