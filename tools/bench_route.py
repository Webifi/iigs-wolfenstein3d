"""The benchmark route: one lap of the big room of E1M1, a diagonal, a full
spin and the walk back, as steps of the camera pose. The front end draws one
picture for each step and times them. Units are the game's: 256 to a tile and
1024 to a turn, 0 east and a left turn adds."""
import math

from wolfdata import maps, PROFILE

STEP = 128                    # half a tile a picture: the game walks about 0.48 at eleven pictures a second
TURN = 32                     # the keyboard turns 5 units a tic, 6 tics a picture
START = (int(28.5 * 256), int(36.5 * 256), 0)
if PROFILE.spear:
    # The source spawn is valid in every mission. The logic benchmark uses its
    # recorded demo; the camera-only frontend makes one turn at this spawn.
    info = maps()[0]['planes'][1]
    spawn = next(i for i, code in enumerate(info) if 19 <= code <= 22)
    START = (spawn % 64 * 256 + 128, spawn // 64 * 256 + 128,
             ((1 - (info[spawn] - 19)) * 256) % 1024)
EAST, NORTH, WEST, SOUTH = 0, 256, 512, 768
MARGIN = 96                   # no pose closer than this to a wall or a door


def vector(angle):
    return (round(STEP * math.cos(angle * math.tau / 1024)), -round(STEP * math.sin(angle * math.tau / 1024)))


def steps():
    """[(pictures, dx, dy, dangle)]"""
    if PROFILE.spear:
        return [(1024 // TURN, 0, 0, TURN)]
    out = []

    def walk(angle, tiles):
        dx, dy = vector(angle)
        out.append((int(tiles * 256) // STEP, dx, dy, 0))

    def turn(units):
        out.append((units // TURN, 0, 0, TURN))

    walk(EAST, 12)
    turn(256)
    walk(NORTH, 6)
    turn(256)
    walk(WEST, 12)
    turn(256)
    walk(SOUTH, 6)
    turn(320)                  # to 22.5 degrees
    dx, dy = vector(64)
    out.append((26, dx, dy, 0))
    turn(1024)                 # one whole turn
    turn(448)                  # to face west
    walk(WEST, 12)
    return out


def poses():
    x, y, a = START
    yield x, y, a
    for n, dx, dy, da in steps():
        for _ in range(n):
            x, y, a = (x + dx) & 0xffff, (y + dy) & 0xffff, (a + da) & 1023
            yield x, y, a


def check():
    """Every pose is in the open floor of the room with room to spare."""
    plane = maps()[0]['planes'][0]

    def solid(cx, cy):
        t = plane[cy * 64 + cx]
        return t < 64 or 90 <= t <= 101

    count = 0
    for x, y, a in poses():
        count += 1
        for cx in ((x - MARGIN) // 256, (x + MARGIN) // 256):
            for cy in ((y - MARGIN) // 256, (y + MARGIN) // 256):
                if solid(cx, cy):
                    raise SystemExit(f'route pose {count} ({x}, {y}) is too close to a wall')
    return count


def asm(label='benchRoute'):
    out = [f'{label}:', '              .word ' + ', '.join(str(v) for v in START)]
    for n, dx, dy, da in steps():
        out.append(f'              .word {n}, {dx & 0xffff}, {dy & 0xffff}, {da}')
    out.append('              .word 0, 0, 0, 0')
    return out


if __name__ == '__main__':
    print(check(), 'poses,', sum(n for n, *_ in steps()), 'pictures')
