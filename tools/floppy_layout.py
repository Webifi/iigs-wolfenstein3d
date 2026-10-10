"""Floppy layout. Disk 1 holds the boot data only: the game never asks for it after the boot.

The boot ends on the home disk (tools/mkdisk.py HDR_HOME_DISK): the last boot disk, never
disk 1 (disk 2 when the boot data fits disk 1). The home disk holds WOLF.SETTINGS, WOLF.SETX,
WOLF.MENU, the saves and the store blocks of the front end (the title, the high scores, the
victory: a game over or an ending returns to the title), and as many floors as fit after
them: with the home disk in the drive, New Game and Load of its first floors ask for one disk.
When the boot keeps the play blocks in RAM ("play_floors" in episode-disk.json), disk 1
holds their image (mkdisk.py), and only the floors whose art takes that RAM read them from
their disks.

Floors with one part: each disk holds the complete loads of consecutive floors in
play order (a secret floor follows the floor of its secret exit), so the next floor is on the
same disk or on a later one: at most one disk change. Floors with two parts: see
plan.

The store builder writes build/assets/episode-disk.json: for each floor the store blocks its
load reads, the blocks of the loads during play, and the blocks of the title. The game finds
a store block through the run table in the header of the disk in the drive
(src/iigs/leveldirectory.s storeFromDisk); the header's floor table names each floor's disks.

Usage: python3 tools/floppy_layout.py [--max-disks N]   (cwd: a build stage)
"""
import json
import sys
from pathlib import Path

MAX_DISKS = 8                   # maximum number of disks in a campaign set
MAX_RUNS = 44                   # store runs in a disk header without segments (tools/mkdisk.py)


def blocks(ranges):
    """The store blocks of [[first, count], ...]."""
    return {b for first, count in ranges for b in range(first, first + count)}


def runs(block_set):
    """Sorted [first, count] of the blocks, adjacent ones merged."""
    out = []
    for b in sorted(block_set):
        if out and out[-1][0] + out[-1][1] == b:
            out[-1][1] += 1
        else:
            out.append([b, 1])
    return out


def filled(block_set, max_runs):
    """The blocks plus the smallest gaps between their runs, so that they form at most max_runs
    runs: a disk header lists that many."""
    r = runs(block_set)
    if len(r) <= max_runs:
        return block_set
    gaps = sorted((r[i + 1][0] - r[i][0] - r[i][1], i) for i in range(len(r) - 1))
    out = set(block_set)
    for size, i in gaps[:len(r) - max_runs]:
        out |= set(range(r[i][0] + r[i][1], r[i + 1][0]))
    return out


def play_order(campaign):
    """Floor indices in play order: each episode from its start along the normal exits, with
    a secret floor right after the floor of its secret exit."""
    floors = {f['index']: f for f in campaign['floors']}
    order = []
    for episode in campaign['episodes']:
        seen = set()
        f = episode['start']
        while f is not None and f not in seen and f in floors:
            seen.add(f)
            order.append(f)
            secret = floors[f]['secret']
            if secret < 0x4000 and secret not in seen and secret in floors:
                seen.add(secret)
                order.append(secret)
            nxt = floors[f]['normal']
            f = nxt & 0x3fff if nxt < 0xfffe else None
        order += [n for n in episode['floors'] if n not in seen]
    if sorted(order) != sorted(floors):
        raise ValueError('play order does not hold every floor once')
    return order


def routes(campaign):
    """(from floor, to floor) for every exit that loads another floor."""
    return [(f['index'], f[key] & 0x3fff) for f in campaign['floors']
            for key in ('normal', 'secret', 'victory', 'spear') if f[key] < 0xfffe]


def play_cache_floors(units):
    """{floor: the play blocks its loads read from the disk}: all play blocks on every floor,
    or, when the boot keeps the play blocks in RAM ("play_floors" in episode-disk.json:
    {floor: ranges}), the blocks of the RAM that a floor's art takes, on that floor and on the
    floors entered from it (their loads read them back)."""
    if 'play_floors' in units:
        return {int(f): blocks(r) for f, r in units['play_floors'].items()}
    return {f: blocks(units['play']) for f in range(len(units['floors']))}


def title_blocks(units):
    """The store blocks of the home disk's front end."""
    return blocks(units['title'])


def parts(entry):
    """A floor entry of episode-disk.json: its episode-disk part and its floor-disk part. A list
    of ranges is a floor with one part (on its floor disk)."""
    if isinstance(entry, dict):
        return blocks(entry['shared']), blocks(entry['own'])
    return set(), blocks(entry)


def pack(groups, need, extra, capacity, start=None):
    """Disks of consecutive groups of floors, each disk as full as capacity allows; a group
    never splits. extra(group) is what a disk holding the group needs besides the floors'
    parts. start: the first disk, already holding blocks (dict(blocks, capacity, max_runs)).
    Returns [dict(floors, blocks, capacity, max_runs)]."""
    disks, current = [], None
    if start is not None:
        current = dict(start, floors=[], blocks=set(start['blocks']), home=True)
        disks.append(current)
    for group in groups:
        own = set().union(*[need[f] for f in group]) | extra(group)
        if not own:
            continue
        if len(filled(own, MAX_RUNS)) > capacity:
            raise ValueError(f'floors {" ".join(str(f + 1) for f in group)}: '
                             f'{len(filled(own, MAX_RUNS))} blocks, one disk holds {capacity}')
        if current is None or len(filled(current['blocks'] | own, current['max_runs'])) > current['capacity']:
            current = dict(floors=[], blocks=set(), capacity=capacity, max_runs=MAX_RUNS)
            disks.append(current)
        current['floors'] += [f for f in group if need[f]]
        current['blocks'] |= own
    return disks


def plan(units, campaign, capacity, home_room, max_disks=MAX_DISKS, boot_disks=1, home_disk=1,
         home_runs=MAX_RUNS):
    """units: episode-disk.json. Disks 1 to boot_disks hold the boot data; home_disk is the last
    of them, with home_room blocks free for store blocks after its files and boot data and
    home_runs store runs in its header: the title blocks, then the first floors of a series.
    Floors with one part: each disk holds consecutive floors in play order.
    Floors with two parts: a floor reads its episode part, then its floor part, or the reverse
    (the disk in the drive first), so every next floor is one disk change when both floors are
    on the same two disks. A secret exit gives two routes of different length to the floor
    after it, so a disk boundary inside an episode cannot be one change on both routes: each
    episode stays whole on one episode disk and one floor disk. A disk holds whole episodes.
    The home disk continues the floor series or the episode series, whichever gives fewer
    disks (the floor series on a tie).
    The play blocks go with the parts of the floors that read them from the disk: a load ends
    on either disk of its two, so with both parts.
    Returns dict(floor_disk, disks, ...); floor_disk is a byte per floor: bits 4-6 the episode
    disk - 1 (0: none), bits 0-2 the floor disk - 1."""
    split = [parts(e) for e in units['floors']]
    play_floors = play_cache_floors(units)
    title = filled(title_blocks(units), home_runs)
    if len(title) > home_room:
        raise ValueError(f'disk {home_disk}: the title blocks need {len(title)}, '
                         f'{home_room} are free after the boot data, menu and saves')
    order = play_order(campaign)
    two = any(shared for shared, _ in split)
    if two:
        groups = [[f for f in order if f in set(e['floors'])] for e in campaign['episodes']]
    else:
        groups = [[f] for f in order]
    plays = lambda group: set().union(*[play_floors.get(f, set()) for f in group])
    home = dict(blocks=title, capacity=home_room, max_runs=home_runs)
    position = {f: i for i, f in enumerate(order)}
    layouts = []
    for merged in (('floor', 'episode') if two else ('floor',)):
        series = [('episode', pack(groups, [s for s, _ in split], plays if two else lambda g: set(), capacity,
                                   home if merged == 'episode' else None)),
                  ('floor', pack(groups, [o for _, o in split], plays, capacity,
                                 home if merged == 'floor' else None))]
        disks = [dict(floors=[], blocks=set(), kind='boot') for _ in range(boot_disks)]
        disks[home_disk - 1]['blocks'] = title
        data = []
        for kind, ds in series:
            for d in ds:
                if d.get('home'):
                    disks[home_disk - 1] = dict(floors=d['floors'], kind=kind, home=True,
                                                blocks=filled(d['blocks'], home_runs))
                elif d['floors']:
                    data.append((position[d['floors'][0]], kind, d))
        for _, kind, d in sorted(data, key=lambda x: (x[0], x[1] != 'episode')):
            disks.append(dict(floors=d['floors'], kind=kind, blocks=filled(d['blocks'], MAX_RUNS)))
        layouts.append(disks)
    disks = min(layouts, key=len)
    if len(disks) > max_disks:
        raise ValueError(f'{len(disks)} disks, more than {max_disks}: ' +
                         ', '.join(f'disk {n} {len(d["blocks"])} blocks' for n, d in enumerate(disks, 1)))
    if len(disks) > 8:
        raise ValueError(f'{len(disks)} disks: the floor table has 3 bits per disk')
    floor_disk = [0] * len(split)
    for number, disk in enumerate(disks, 1):
        for f in disk['floors']:
            floor_disk[f] |= (number - 1) << 4 if disk['kind'] == 'episode' else number - 1
        disk['runs'] = runs(disk['blocks'])
    layout = dict(floor_disk=floor_disk, disks=disks, home_disk=home_disk, boot_disks=boot_disks)
    check(units, campaign, layout)
    return layout


def check(units, campaign, layout):
    """Each floor's parts on its disks (the play blocks with each part where the floor reads
    them from the disk), the title blocks on the home disk, no floor data on disk 1 or on
    another boot disk but the home disk. One part per floor: no route back to an earlier disk.
    Two parts: both floors of every route inside an episode on the same two disks."""
    disks, floor_disk, home_disk = layout['disks'], layout['floor_disk'], layout['home_disk']
    play_floors = play_cache_floors(units)
    if not title_blocks(units) <= disks[home_disk - 1]['blocks']:
        raise ValueError(f'disk {home_disk}: title blocks missing')
    episode_disk = lambda f: (floor_disk[f] >> 4 & 7) + 1 if floor_disk[f] >> 4 & 7 else 0
    floor_disk_of = lambda f: (floor_disk[f] & 7) + 1
    for f, entry in enumerate(units['floors']):
        shared, own = parts(entry)
        if f in play_floors:
            own = own | play_floors[f]
            shared = shared and shared | play_floors[f]
        for part, number in ((shared, episode_disk(f)), (own, floor_disk_of(f))):
            if not part:
                continue
            if (number <= layout['boot_disks'] and number != home_disk) or not part <= disks[number - 1]['blocks']:
                raise ValueError(f'floor {f + 1}: blocks missing on disk {number}')
    episode = {f: n for n, e in enumerate(campaign['episodes']) for f in e['floors']}
    two = any(episode_disk(f) for f in range(len(floor_disk)))
    for a, b in routes(campaign):
        if two and episode.get(a) == episode.get(b) and floor_disk[a] != floor_disk[b]:
            raise ValueError(f'floor {a + 1} -> {b + 1} changes disks inside an episode')
        if not two and floor_disk_of(b) < floor_disk_of(a):
            raise ValueError(f'floor {a + 1} -> {b + 1} goes back from disk {floor_disk_of(a)} to {floor_disk_of(b)}')


def main():
    import mkdisk
    args = sys.argv[1:]
    limit = int(args[args.index('--max-disks') + 1]) if '--max-disks' in args else MAX_DISKS
    units = json.loads(Path('build/assets/episode-disk.json').read_text())
    campaign = json.loads(Path('build/gen/campaign.json').read_text())
    capacity = mkdisk.data_capacity(readme=False)
    layout = plan(units, campaign, capacity, capacity, limit)
    for n, d in enumerate(layout['disks'], 1):
        floors = ' '.join(str(f + 1) for f in d['floors']) or 'title'
        print(f'disk {n}: {len(d["blocks"])} blocks, {len(d["runs"])} runs, floors {floors}')


if __name__ == '__main__':
    main()
