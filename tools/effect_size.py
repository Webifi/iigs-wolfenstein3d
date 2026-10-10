#!/usr/bin/env python3
"""Legacy lossy effects reduction and floor cache planning.

This path trims ends, estimates a 90%-energy bandwidth, resamples, caps at
4095 samples and peak-normalizes. Those operations are not proof of preserved
sound or listening acceptance. prepare_effects.py provides a separate opt-in
source-preserving preparation; the current native player still uses this path.
Floor plans pin frequent sounds in pages 0..47; pages 48..63 remain a pool.
"""
import math
import native_host
import os
from functools import lru_cache
import struct
import wave
from pathlib import Path

from wolfaudio import DOC_RATE, NAMES, effects
from wolfdata import PROFILE, ROOT, source_data
from effect_sources import selected_samples
from wolfsim import (
    BOSSOBJ, DOGOBJ, GUARDOBJ, ITEM, OFFICEROBJ, PUSHABLETILE, SSOBJ, Game,
)

# FC 1096 on a 4096-byte table: 26320 * 1096 / 4096.
SOURCE_RATE = DOC_RATE * 1096 / 4096
SR = 894886 / 34
SHARE = 0.90
KMIN, KMAX = 6, 16
TAIL_DB = 30
MAXLEN = 4095
FADE = 256
PAGES = 64
PIN_PAGES = 48          # pages 48-63 stay a pool on every floor
# 31 pins, stride 64. sound.s indexes the plan as floor * 64.
PLAN_SLOTS = 31
STRIDE = 64
# Sights, shots and guns are offered the pin first, after legacy reduction.
KEEP = (
    'HALTSND', 'GUTENTAGSND', 'SCHUTZADSND', 'DOGBARKSND',
    'NAZIFIRESND', 'SSFIRESND', 'BOSSFIRESND', 'DOGATTACKSND',
    'ATKPISTOLSND', 'ATKMACHINEGUNSND', 'ATKGATLINGSND',
)
OUT = Path(__file__).resolve().parents[1] / 'build/effects-reduced'

GUARD_SCREAMS = (
    'DEATHSCREAM1SND', 'DEATHSCREAM2SND', 'DEATHSCREAM3SND', 'DEATHSCREAM4SND',
    'DEATHSCREAM5SND', 'DEATHSCREAM7SND', 'DEATHSCREAM8SND', 'DEATHSCREAM9SND',
)
ITEM_SOUND = {
    'bo_gibs': 'SLURPIESND', 'bo_alpo': 'HEALTH1SND', 'bo_firstaid': 'HEALTH2SND',
    'bo_key1': 'GETKEYSND', 'bo_key2': 'GETKEYSND', 'bo_key3': 'GETKEYSND',
    'bo_key4': 'GETKEYSND', 'bo_cross': 'BONUS1SND', 'bo_chalice': 'BONUS2SND',
    'bo_bible': 'BONUS3SND', 'bo_crown': 'BONUS4SND', 'bo_clip': 'GETAMMOSND',
    'bo_clip2': 'GETAMMOSND', 'bo_machinegun': 'GETMACHINESND',
    'bo_chaingun': 'GETGATLINGSND', 'bo_food': 'HEALTH1SND',
    'bo_fullheal': 'BONUS1UPSND',
}
# Sight, shot and death follow lact.s: an officer takes the boss sight and
# death paths and the guard shot path.
CLASS_SOUND = {
    GUARDOBJ: ('HALTSND', 'NAZIFIRESND', GUARD_SCREAMS),
    OFFICEROBJ: ('GUTENTAGSND', 'NAZIFIRESND', ('MUTTISND',)),
    SSOBJ: ('SCHUTZADSND', 'SSFIRESND', ('LEBENSND',)),
    DOGOBJ: ('DOGBARKSND', 'DOGATTACKSND', ('DOGDEATHSND',)),
    BOSSOBJ: ('GUTENTAGSND', 'BOSSFIRESND', ('MUTTISND',)),
}


def bessel_i0(x):
    s = term = 1.0
    k = 1
    while term > 1e-12 * s:
        term *= (x / (2 * k)) ** 2
        s += term
        k += 1
    return s


def resample(x, n):
    """x (values 1..255, around 128) as n samples of the same length of time."""
    step = len(x) / n
    fc = 0.46 / step
    half = 8 / (2 * fc)
    beta = 7.0
    i0b = bessel_i0(beta)
    grid = 64
    kern = []
    for g in range(int(half * grid) + 2):
        u = g / grid
        if u > half:
            kern.append(0.0)
            continue
        sinc = 2 * fc if u == 0 else math.sin(2 * math.pi * fc * u) / (math.pi * u)
        w = bessel_i0(beta * math.sqrt(1 - (u / half) ** 2)) / i0b
        kern.append(sinc * w)
    xs = [v - 128 for v in x]
    if native_host.library():
        y = native_host.effect_filter(xs, kern, n, step, half, grid)
    else:
        y = []
        for k in range(n):
            c = (k + 0.5) * step - 0.5
            lo = max(0, math.ceil(c - half))
            hi = min(len(xs) - 1, math.floor(c + half))
            acc = 0.0
            for j in range(lo, hi + 1):
                acc += xs[j] * kern[int(abs(c - j) * grid + 0.5)]
            y.append(acc)
    a = 0.12
    z = [y[k] + a * (2 * y[k] - y[k - 1 if k else k] - y[k + 1 if k + 1 < n else k])
         for k in range(n)]
    return [min(255, max(1, int(round(v + 128)))) for v in z]


@lru_cache(maxsize=8)
def fft_rotations(n):
    return tuple(complex(math.cos(-2*math.pi*k/size), math.sin(-2*math.pi*k/size))
                 for size in (1<<j for j in range(1,n.bit_length())) for k in range(size//2))


def fft(a):
    if len(a)>1 and native_host.library():
        result=native_host.fft(a,fft_rotations(len(a)),twiddle_first=True)
        if result is not None:
            return result
    return fft_python(a)


def fft_python(a):
    n = len(a)
    if n == 1:
        return a
    ev, od = fft_python(a[0::2]), fft_python(a[1::2])
    out = [0] * n
    for k in range(n // 2):
        t = complex(math.cos(-2 * math.pi * k / n), math.sin(-2 * math.pi * k / n)) * od[k]
        out[k] = ev[k] + t
        out[k + n // 2] = ev[k] - t
    return out


def band(x, rate):
    """The frequency below which SHARE of the energy of x lies."""
    n = 1024
    w = [0.5 - 0.5 * math.cos(2 * math.pi * i / n) for i in range(n)]
    xs = [v - 128 for v in x]
    xs += [0] * max(0, n - len(xs))
    acc = [0.0] * (n // 2)
    if len(xs) < n:
        f = fft([xs[i] * w[i] for i in range(n)])
        acc = [abs(v) ** 2 for v in f[:n // 2]]
    else:
        for s in range(0, len(xs) - n + 1, n // 2):
            f = fft([xs[s + i] * w[i] for i in range(n)])
            for k in range(n // 2):
                acc[k] += abs(f[k]) ** 2
    total = sum(acc) or 1.0
    c = 0.0
    for k, p in enumerate(acc):
        c += p
        if c >= SHARE * total:
            return (k + 1) * rate / n
    return rate / 2


def trim(x):
    peak = max((abs(v - 128) for v in x), default=0)
    thr = max(3, peak * 10 ** (-TAIL_DB / 20))
    lo, hi = 0, len(x)
    while lo < hi and abs(x[lo] - 128) <= thr:
        lo += 1
    while hi > lo and abs(x[hi - 1] - 128) <= thr:
        hi -= 1
    return x[lo:hi]


def limit(x):
    if len(x) <= MAXLEN:
        return x
    x = x[:MAXLEN]
    for i in range(FADE):
        g = (FADE - i) / (FADE + 1)
        j = MAXLEN - FADE + i
        x[j] = min(255, max(1, int(round(128 + (x[j] - 128) * g))))
    return x


def small(x, rate, kmin=KMIN):
    """(samples, rate) at the lowest SR/k that keeps the band, k from kmin to 16."""
    x = trim(x)
    if not x:
        return [128], rate
    b = band(x, rate)
    k = max(kmin, min(KMAX, int(SR * 0.42 / b))) if b else KMAX

    def size(kk):
        return math.ceil(len(x) * SR / kk / rate)

    def table(n):
        t = 256
        while t < n + 1:
            t *= 2
        return t

    if size(4) <= 2047:
        k = 4
    elif b > 0.42 * SR / k:
        for up in range(max(4, kmin), k):
            if size(up) <= MAXLEN and table(size(up)) == table(size(k)):
                k = up
                break
    new = SR / k
    if new < rate - 0.5:
        x = resample(x, max(1, round(len(x) * new / rate)))
    else:
        new = rate
    return limit(x), new


def table_bytes(n):
    t = 256
    while t < n + 1:
        t *= 2
    return t


def freq_word(rate, size_code):
    """DOC frequency word: round the rate ratio, then round for the size shift."""
    raw = int(round(rate * 65536 / DOC_RATE))
    bias = (1 << size_code) >> 1
    return (raw + bias) >> size_code


def pack(order, pages_of, limit=PIN_PAGES, owner=None):
    """Greedy best-fit into pages 0..limit-1. Returns placed, pool_lo, owner."""
    owner = [None] * limit if owner is None else list(owner)
    placed = {}
    for sid in order:
        n = pages_of[sid]
        if n > limit or n <= 0:
            continue
        best = None
        for st in range(0, limit - n + 1, n):
            if any(owner[p] is not None for p in range(st, st + n)):
                continue
            a, b = st, st + n
            while a > 0 and owner[a - 1] is None:
                a -= 1
            while b < limit and owner[b] is None:
                b += 1
            fit = (b - a, st)
            if best is None or fit < best:
                best = fit
        if best:
            st = best[1]
            for p in range(st, st + n):
                owner[p] = sid
            placed[sid] = st
    pool = 0
    while pool < limit and owner[pool] is not None:
        pool += 1
    if pool == limit:
        pool = limit
    return placed, pool, owner


def floor_weights():
    """Count source-map spawns at every difficulty for the common pin planner."""
    from effect_closure import pin_weights
    return pin_weights()


def pcm_of(effect):
    if effect['pcm'] is not None:
        return [max(1, b) for b in effect['pcm']]
    return list(preserved_samples()[effect['id']])


@lru_cache(maxsize=1)
def preserved_samples():
    """Reject unrelated OPL inputs before applying the legacy lossy reduction."""
    from effect_sources import manifest
    from audio_package import checked,contained
    folder=selected_samples(PROFILE)
    if not (folder/'samples.toml').is_file():
        raise ValueError('effects require a preserved effects/ym3812 folder with samples.toml and individual .u8 files; set WOLF_EFFECT_SAMPLES to select another folder')
    receipt=manifest(source_data(),folder)
    return {r['id']:checked(contained(folder,r['file']),r['payload_sha256'])
            for r in receipt['effects'] if r['kind']=='preserved-ym3812'}


def finish_row(row, samples, rate):
    samples = [1 if b == 0 else b for b in samples]
    pages = table_bytes(len(samples)) // 256
    size_code = pages.bit_length() - 1
    row.update(samples=samples, rate=rate, pages=pages, size_code=size_code,
               fc=freq_word(rate, size_code))
    return pages


def assign(rows):
    """Sights, shots and guns are pinned first. A sound that does not fit
    pages 0..47 stays unpinned at its already-reduced rate."""
    weights = floor_weights()
    names = {r['name']: r['id'] for r in rows}
    keep = {names[name] for name in KEEP if name in names}
    plans = []
    pages = {r['id']: r['pages'] for r in rows}
    for floor, w in enumerate(weights):
        order = sorted(w, key=lambda s: (-w[s] / pages[s], -w[s], s))
        prot = [s for s in order if s in keep and w.get(s, 0) > 0]
        rest = [s for s in order if s not in prot]
        placed, _, owner = pack(prot, pages)
        more, pool, _ = pack(rest, pages, owner=owner)
        placed.update(more)
        if len(placed) > PLAN_SLOTS:
            ranked = sorted(placed, key=lambda s: (w[s] / pages[s], w[s], -s))
            for sid in ranked:
                if len(placed) <= PLAN_SLOTS:
                    break
                if sid not in keep:
                    del placed[sid]
        plans.append(dict(floor=floor, pool=pool, placed=placed, weight=w, protect=set(prot)))
        pinned = sum(rows[s]['pages'] for s in placed)
        lost = [rows[s]['name'] for s in prot if s not in placed]
        print(f'floor {floor}: {len(placed)} pinned, {pinned} pages, pool at {pool}'
              + (f', unpinned {lost}' if lost else ''), flush=True)
    return plans


def levelize(rows):
    """Peak-normalize each table and load its descriptor level from levels.json.

    The current file is an interim flat policy, level 255 for every effect.
    It does not preserve the inputs' relative peaks or loudness. The descriptor
    level applies at effects volume 15; this function does not alter that file.
    """
    import json
    from wolfaudio import ROOT
    levels = json.loads((ROOT / 'data/sound/levels.json').read_text())['levels']
    for row in rows:
        peak = max((abs(b - 128) for b in row['samples']), default=0) or 1
        gain = 127 / peak
        row['samples'] = [min(255, max(1, 128 + int(round((b - 128) * gain)))) for b in row['samples']]
        row['level'] = levels[str(row['id'])]['level']


def reduced_bank():
    """Reduce every effect with the legacy policy, then plan pins in pages 0..47."""
    rows = []
    for effect in effects():
        raw = pcm_of(effect)
        samples, rate = small(raw, SOURCE_RATE)
        row = dict(id=effect['id'], name=effect['name'], priority=effect['priority'],
                   original=len(raw))
        pages = finish_row(row, samples, rate)
        rows.append(row)
        print(f'{effect["id"]:02} {effect["name"]} {len(raw)} -> {len(row["samples"])} '
              f'at {row["rate"]:.0f} Hz, {pages} pages', flush=True)
    plans = assign(rows)
    levelize(rows)
    return rows, plans


def write_ab(rows, plans):
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('*.wav'):
        old.unlink()
    lines = []
    for row in rows:
        if row['original'] == len(row['samples']) and abs(row['rate'] - SOURCE_RATE) < 1:
            continue
        orig = pcm_of(next(e for e in effects() if e['id'] == row['id']))
        stem = f'{row["id"]:02}-{row["name"]}'
        for tag, data, rate in (
            ('7043', orig, round(SOURCE_RATE)),
            ('reduced', row['samples'], max(1, round(row['rate']))),
        ):
            path = OUT / f'{stem}-{tag}.wav'
            with wave.open(str(path), 'wb') as f:
                f.setparams((1, 1, rate, 0, 'NONE', 'not compressed'))
                f.writeframes(bytes(data))
        floors = [str(p['floor']) for p in plans if row['id'] in p['placed']]
        line = (f'{row["id"]:02} {row["name"]} {round(SOURCE_RATE)}Hz {row["original"]} -> '
                f'{round(row["rate"])}Hz {len(row["samples"])} table {row["pages"] * 256} '
                f'pinned {",".join(floors) if floors else "pool"}')
        lines.append(line)
    (OUT / 'READY.txt').write_text('\n'.join(lines) + '\n')
    print(f'{len(lines)} reduced effects in {OUT}', flush=True)


def plan_bytes(plans):
    """Stride 64: pool, count, then up to 31 (id, page) pairs per supplied floor."""
    out = bytearray()
    for plan in plans:
        pairs = sorted(plan['placed'].items(), key=lambda item: item[1])
        if len(pairs) > PLAN_SLOTS:
            raise ValueError(f'floor {plan["floor"]} pins {len(pairs)}')
        record = bytearray(STRIDE)
        record[0] = plan['pool'] & 0xff
        record[1] = len(pairs)
        for i, (sid, page) in enumerate(pairs):
            record[2 + i * 2] = sid
            record[3 + i * 2] = page
        for i in range(len(pairs), PLAN_SLOTS):
            record[2 + i * 2] = 0xff
            record[3 + i * 2] = 0xff
        out += record
    return bytes(out)


if __name__ == '__main__':
    rows, plans = reduced_bank()
    write_ab(rows, plans)
    fight = {}
    for row in rows:
        if row['name'] in ('NAZIFIRESND', 'ATKPISTOLSND', 'ATKMACHINEGUNSND',
                           'ATKGATLINGSND', 'HALTSND', 'GUTENTAGSND'):
            fight[row['name']] = row['id']
    for plan in plans:
        if plan['floor'] in (0, 4):
            have = {NAMES[s]: page for s, page in plan['placed'].items()}
            print('floor', plan['floor'], 'fight', {n: have.get(n, 'pool') for n in fight})
