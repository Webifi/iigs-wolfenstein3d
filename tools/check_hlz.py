"""Run the linked HLZ decoder (src/iigs/hlz.inc) in emu816 on store units and compare
every output byte with tools/hlz.py.

Each unique unit of a store (episode.bin + episode.json, decoded and checked by its
sha256) is packed with hlz.compress, placed in its stage bank the way the floor loader
places it, and decoded by CodecDispatch at the unit's own address. The check also
asserts that no byte outside the output changed (guard bytes on both sides and the
tables' stage area excepted), that the return context is DecodeFloorUnit's, and it
counts nominal cycles (emu816) for the setup and for the whole decode.

The store's own LZSA1 and LZ16 units also run through CodecDispatch (which passes
them on to DecodeFloorUnit), checked and timed the same way.

--as-stored decodes each packed unit as the store holds it (HLZ, LZSA1 or LZ16).
--music (with --as-stored) decodes the song halves (bank MUSIC_BASE) the way a
music-list load does: loadMixed 0, loadMusic set, a WOLFMS03 list, stage BOOT_STAGE.

Usage (cwd = a built stage): python3 tools/check_hlz.py --store DIR --out FILE.json
       [--as-stored [--music]] [--cache DIR] [--jobs N] [--limit N]
"""
import argparse
import hashlib
import json
import struct
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import memmap
import hlz
import storage_codec
from elf import read
from emu816 import Emu

GUARD = 0xa5
TABLES = 2 * 1024


class Native:
    def __init__(self, elf, loader):
        self.emu = Emu()
        segments, self.symbols = read(elf)
        segments += read(loader)[0]
        for seg in segments:
            self.emu.load(seg['address'], seg['data'])
        self.code = [(seg['address'], seg['address'] + len(seg['data'])) for seg in segments]
        self.base = bytes(self.emu.m)
        s = self.symbols
        self.setup_range = (memmap.SEG_HLZ_SETUP, memmap.SEG_HLZ_SETUP_END)

    def run(self, data, payload, address, floor, music=False):
        e = self.emu
        e.m[:] = self.base
        blocks = (len(payload) + 511) // 512
        size = len(data)
        end = address + size
        # the loader's stage for the unit; the other one when the output overlaps it
        # (units the store keeps raw, tested here for the decoder alone)
        for stage in (((memmap.BOOT_STAGE >> 16),) if music else
                      ((memmap.GEN_PAGES if floor else memmap.BOOT_STAGE) >> 16,
                       (memmap.BOOT_STAGE if floor else memmap.GEN_PAGES) >> 16)):
            stage_end = (stage << 16) + blocks * 512 + TABLES
            if not (address < stage_end and end + 2 > stage << 16):
                break
        else:
            raise AssertionError('output overlaps both stages')
        # guard bytes around the output (not on loaded code), then the packed unit
        guards = [g for g in list(range(max(address - 16, 0), address)) + list(range(end, end + 16))
                  if not any(a <= g < b for a, b in self.code)]
        for g in guards:
            e.m[g] = GUARD
        e.load(stage << 16, payload + bytes(blocks * 512 - len(payload)))

        s = self.symbols
        record = memmap.EPDIR + 64                  # a record after the list header
        if music:
            e.wr16(memmap.EPDIR + 6, 0x3330)        # WOLFMS03
        e.wr16(record, address & 0xffff)
        e.wr16(record + 2, (address >> 16) | 0x100 | 0x4000)
        e.wr16(record + 4, 0)
        e.wr16(record + 6, blocks)
        e.wr16(memmap.LV_RECORD, record)
        e.wr16(s['loadMixed'], 0 if music else 1)   # only the floor list path sets it
        # SelectStage patches the stage bank into the LZSA1/LZ16 decoder as a load does
        e.wr16(s['loadAux'], 0 if stage == memmap.GEN_PAGES >> 16 or music else 1)
        e.wr16(s['loadMusic'], 0x4000 if music else 0)
        e.wr16(s['loadProbe'], 0)
        e.db = e.d = 0
        e.s = 0x1ff
        e.mf = e.xf = 0
        e.call(s['SelectStage'] >> 16, s['SelectStage'] & 0xffff)
        assert e.rd16(s['stageBank']) == stage
        e.wr16(s['stageStart'], 0)
        e.wr16(memmap.SEGADDR, address & 0xffff)
        e.wr8(memmap.SEGADDR + 2, address >> 16)
        e.db = e.d = 0
        e.s = 0x1ff
        e.mf = e.xf = 0
        e.a = e.x = e.y = 0
        e.cycles = 0
        e.hist = {}
        # JSL from bank 0 as levelio.s does: the other codecs return through
        # DecodeFloorUnit's RTS in bank 0, so the return trap is a bank-0 byte (BUF).
        e.call(s['CodecDispatch'] >> 16, s['CodecDispatch'] & 0xffff, long_return=True, limit=60_000_000,
               sentinel=memmap.BUF)
        out = bytes(e.m[address:end])
        ok = out == data
        outside = all(e.m[g] == GUARD for g in guards)
        context = (e.db, e.d, e.mf, e.xf) == (0, 0, 1, 0)
        a, b = self.setup_range
        setup = sum(c for pc, (n, c) in e.hist.items() if a <= pc < b)
        hlzunit = (s['hlzUnit'], s['hlzRep'])
        setup += sum(c for pc, (n, c) in e.hist.items() if hlzunit[0] <= pc < hlzunit[1])
        return dict(exact=ok, outside_kept=outside, context=context, cycles=e.cycles, setup_cycles=setup)


def kind(asset):
    for key, name in (('song-', 'music'), ('sight', 'sight'), ('/restore-', 'pause'), ('effects', 'effects'),
                      ('weapon', 'weapons'), ('source-planes', 'map'), ('linked logic', 'logic'), ('spriteFrame', 'logic')):
        if key in asset:
            return name
    if asset.startswith('build/fixed/') or 'registered-art' in asset or 'fixed-' in asset or 'fixed_gen' in asset:
        return 'art'
    return 'other'


_native = None


def _work(job):
    global _native
    elf, loader, cache, item, data, old = job
    if _native is None:
        _native = Native(elf, loader)
    if cache is None:
        # --as-stored: the unit's own packed payload (HLZ, LZSA1 or LZ16)
        try:
            result = _native.run(data, old, item['address'], item['floor'], item.get('music', False))
        except Exception as error:
            result = dict(exact=False, outside_kept=False, context=False, cycles=0, setup_cycles=0, error=str(error))
        result.update(item, bytes=len(data))
        return result
    key = hashlib.sha256(Path(hlz.__file__).read_bytes() + data).hexdigest()
    path = Path(cache) / (key + '.hlz')
    if path.exists():
        payload = path.read_bytes()
    else:
        payload = hlz.compress(data)
        path.write_bytes(payload)
    stats = {}
    assert hlz.decode(payload, len(data), stats) == data
    try:
        result = _native.run(data, payload, item['address'], item['floor'])
    except Exception as error:  # a trap in the decoder: report the unit
        result = dict(exact=False, outside_kept=False, context=False, cycles=0, setup_cycles=0, error=str(error))
    result.update(item, bytes=len(data), hlz_bytes=len(payload), hlz_blocks=(len(payload) + 511) // 512,
                  literals=stats.get('literals', 0), matches=stats.get('matches', 0), reps=stats.get('reps', 0),
                  match_bytes=stats.get('match_bytes', 0))
    if old is not None:
        # the store's own LZSA1/LZ16 payload: CodecDispatch passes it on to DecodeFloorUnit
        try:
            other = _native.run(data, old, item['address'], item['floor'])
            result.update(old_exact=other['exact'] and other['outside_kept'] and other['context'],
                          old_cycles=other['cycles'])
        except Exception as error:
            result.update(old_exact=False, old_cycles=0, old_error=str(error))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elf', type=Path, default=Path('build/wolf.elf'))
    ap.add_argument('--loader', type=Path, default=Path('build/boot/loader.elf'))
    ap.add_argument('--store', type=Path, required=True, help='folder with episode.bin and episode.json')
    ap.add_argument('--cache', type=Path, default=Path('build/hlzcache'))
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--as-stored', action='store_true',
                    help='decode each packed unit as the store holds it (HLZ, LZSA1, LZ16)')
    ap.add_argument('--music', action='store_true',
                    help='with --as-stored: only the song halves, loaded the way a music-list load loads them')
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    store = (args.store / 'episode.bin').read_bytes()
    rows = json.loads((args.store / 'episode.json').read_text())
    groups = {}
    for r in rows:
        groups.setdefault(r['first_block'], set()).add(r['group'].split('/')[0])
    jobs = []
    seen = set()
    for r in rows:
        if r['first_block'] in seen:
            continue
        seen.add(r['first_block'])
        payload = store[r['first_block'] * 512:(r['first_block'] + r['blocks']) * 512]
        data = storage_codec.decode(payload, r['bytes'], r['codec'])
        if hashlib.sha256(data).hexdigest() != r['sha256']:
            raise SystemExit('store unit differs from its manifest: block %d' % r['first_block'])
        item = dict(first_block=r['first_block'], asset=r['asset'], address=r['address'], kind=kind(r['asset']),
                    floor='floor' in groups[r['first_block']], store_blocks=r['blocks'], store_codec=r['codec'])
        if args.as_stored:
            if args.music:
                if r['address'] >> 16 != memmap.MUSIC_BASE >> 16:
                    continue
                item['music'] = True
            if r['codec'] in ('hlz', 'lz16', 'lzsa1'):
                jobs.append((str(args.elf), str(args.loader), None, item, data, payload))
            continue
        if len(data) < 1024:
            continue  # the store builder does not take HLZ below HLZ_MIN_BYTES
        old = payload if r['codec'] in ('lz16', 'lzsa1') else None
        jobs.append((str(args.elf), str(args.loader), str(args.cache), item, data, old))
    jobs.sort(key=lambda j: -len(j[4]))
    if args.limit:
        jobs = jobs[:args.limit]
    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for n, result in enumerate(pool.map(_work, jobs, chunksize=1), 1):
            results.append(result)
            if not (result['exact'] and result['outside_kept'] and result['context'] and result.get('old_exact', True)):
                print('FAIL', result, flush=True)
            if n % 50 == 0:
                print(f'{n}/{len(jobs)} units', flush=True)
    bad = [r for r in results if not (r['exact'] and r['outside_kept'] and r['context'] and r.get('old_exact', True))]
    summary = {}
    for r in results:
        name = r['kind'] + ('/' + r['store_codec'] if args.as_stored else '')
        k = summary.setdefault(name, dict(units=0, bytes=0, cycles=0, setup_cycles=0, literals=0, matches=0, reps=0))
        k['units'] += 1
        for f in ('bytes', 'cycles', 'setup_cycles', 'literals', 'matches', 'reps'):
            k[f] += r.get(f, 0)
        if 'old_cycles' in r:
            k['old_units'] = k.get('old_units', 0) + 1
            k['old_bytes'] = k.get('old_bytes', 0) + r['bytes']
            k['old_cycles'] = k.get('old_cycles', 0) + r['old_cycles']
    for k in summary.values():
        k['cycles_per_byte'] = round(k['cycles'] / k['bytes'], 2)
        if k.get('old_bytes'):
            k['old_cycles_per_byte'] = round(k['old_cycles'] / k['old_bytes'], 2)
        k['loop_cycles_per_byte'] = round((k['cycles'] - k['setup_cycles']) / k['bytes'], 2)
    args.out.write_text(json.dumps(dict(units=len(results), failures=len(bad), kinds=summary, results=results), indent=1) + '\n')
    print(f'HLZ native: {len(results)} units, {len(bad)} failures')
    for name, k in sorted(summary.items()):
        print(f"{name:8} units {k['units']:4} bytes {k['bytes']:8} cycles/byte {k['cycles_per_byte']:6} "
              f"(loop {k['loop_cycles_per_byte']}, setup {k['setup_cycles'] // max(1, k['units'])} per unit); "
              f"store LZSA1/LZ16 units {k.get('old_units', 0)}: {k.get('old_cycles_per_byte', '-')} cycles/byte")
    if bad:
        sys.exit(1)


if __name__ == '__main__':
    main()
