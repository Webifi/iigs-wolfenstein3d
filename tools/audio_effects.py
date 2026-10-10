"""Regenerate source effects with the bundled OPL2 renderer and fixed DOC rate."""
from array import array
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from audio_build_cache import inputs, stage, digest
from audio_package import write_toml
from dos_data import DosData
from effect_sources import source_effects, manifest

TOOLS = Path(__file__).resolve().parent
CHIP = 49716
FX = 140
PLAY_RATE = 26320 * 1096 / 4096


def script_for(fxs, tails, work):
    lines = []
    meta = {}
    for e in fxs:
        if e['pcm'] is not None or e['id'] not in tails:
            continue
        notes = e['notes']
        sounding = max(0, len(notes) - 1)
        acc = 0
        counts = []
        for _ in range(sounding):
            acc += CHIP
            step = acc // FX
            acc -= step * FX
            counts.append(step)
        tail = max(1, int(round(CHIP * tails[e['id']])))
        path = work / 'opl' / f'{e["id"]:02}.s16'
        lines.append('reset')
        lines.append(f'out {path}')
        lines.append('reg 1 32')
        lines.append('reg 8 0')
        lines.append('reg 189 0')
        patch = e['patch']
        for op, slot in enumerate((0, 3)):
            lines.append(f'reg {0x20 + slot} {patch[op]}')
            lines.append(f'reg {0x40 + slot} {patch[2 + op]}')
            lines.append(f'reg {0x60 + slot} {patch[4 + op]}')
            lines.append(f'reg {0x80 + slot} {patch[6 + op]}')
            lines.append(f'reg {0xE0 + slot} {patch[8 + op]}')
        lines.append('reg 192 0')
        block = ((e['block'] & 7) << 2) | 0x20
        for index, count in enumerate(counts):
            byte = notes[index]
            if byte == 0:
                lines.append('reg 176 0')
            else:
                lines.append(f'reg 160 {byte}')
                lines.append(f'reg 176 {block}')
            lines.append(f'gen {count}')
        lines.append('reg 176 0')
        lines.append(f'gen {tail}')
        meta[e['id']] = dict(scored=sum(counts), tail=tail, seconds=tail / CHIP)
    return '\n'.join(lines) + '\n', meta


def load_f32(path):
    raw = path.read_bytes()
    vals = array('f')
    vals.frombytes(raw[:len(raw) - len(raw) % 4])
    if sys.byteorder != 'little':
        vals.byteswap()
    return list(vals)


def trim_floor(samples, min_keep):
    if len(samples) <= min_keep:
        return samples
    peak = max((abs(s) for s in samples), default=0.0) or 1.0
    thresh = peak * (0.5 / 110.0)
    win = max(1, int(0.02 * PLAY_RATE))
    last = min_keep
    i = len(samples)
    while i > min_keep:
        start = max(0, i - win)
        seg = samples[start:i]
        rms = math.sqrt(sum(s * s for s in seg) / len(seg))
        if rms >= thresh:
            last = min(len(samples), i + win)
            break
        i -= max(1, win // 2)
    return samples[:max(min_keep, last)]


def quantize(samples):
    peak = max((abs(s) for s in samples), default=0.0)
    if peak < 1e-8:
        return bytes([128])
    gain = 110.0 / peak
    out = bytearray(len(samples))
    for i, s in enumerate(samples):
        v = int(round(128.0 + s * gain))
        if v < 1:
            v = 1
        elif v > 255:
            v = 255
        out[i] = v
    end = len(out)
    while end > 1 and out[end - 1] == 128:
        end -= 1
    return bytes(out[:end])


def regenerate(out, data, game, shared=None):
    """Render complete releases; native fitting happens in the standard build."""
    source = DosData(data, game, shared)
    effects = source_effects(source)
    cc = shutil.which(os.environ.get('CC', 'cc'))
    if cc is None:
        raise ValueError('The full audio build needs a C compiler (CC or cc) for OPL2 effects')
    dep = inputs([TOOLS/'opl', TOOLS/'opl/resample.c', Path(__file__),
                  TOOLS/'effect_sources.py', TOOLS/'dos_data.py', cc],
                 sources=[dict(id=e['id'], adlib=digest_bytes(e['adlib']),
                               digitized=digest_bytes(e['pcm']) if e['pcm'] is not None else None)
                          for e in effects])
    def render(folder):
        suffix = '.exe' if os.name == 'nt' else ''
        opl, resample = folder/('oplfx'+suffix), folder/('ym_resample'+suffix)
        subprocess.run([cc,'-O3',str(TOOLS/'opl/oplfx.c'),str(TOOLS/'opl/opl3.c'),
                        '-o',str(opl)],check=True)
        subprocess.run([cc,'-O3',str(TOOLS/'opl/resample.c'),'-o',str(resample),'-lm'],check=True)
        for name in ('opl','pcm','samples'):(folder/name).mkdir()
        rows=[]
        for e in effects:
            raw=e['adlib'];length=struct.unpack_from('<I',raw)[0]
            rows.append(dict(id=e['id'],name=e['name'],pcm=e['pcm'],patch=tuple(raw[6:17]),
                             block=raw[22]&7,notes=raw[23:23+length]))
        tails={e['id']:22.0 for e in rows if e['pcm'] is None}
        script, meta = script_for(rows,tails,Path('.'))
        (folder/'effects.script').write_text(script)
        subprocess.run([str(opl),'effects.script'],cwd=folder,check=True)
        saved=[]
        for e in rows:
            sid=e['id']
            if sid not in tails:continue
            src=folder/'opl'/f'{sid:02}.s16'; dst=folder/'pcm'/f'{sid:02}.f32'
            subprocess.run([str(resample),str(src),str(dst),f'{PLAY_RATE:.6f}'],
                           check=True,stdout=subprocess.DEVNULL)
            values=load_f32(dst)
            scored=max(1,round(meta[sid]['scored']/CHIP*PLAY_RATE))
            audible=trim_floor(values,scored)
            if len(audible)>=len(values)-8:
                raise ValueError('Effect release is still audible: '+e['name'])
            target=folder/'samples'/f'{sid:02}.u8';target.write_bytes(quantize(audible))
            saved.append(dict(id=sid,file=target.name,sha256=digest(target),
                              original_sha256=digest_bytes(effects[sid]['adlib'])))
        write_toml(folder/'samples/samples.toml',dict(format=1,samples=saved))
        manifest(source,folder/'samples')
        (folder/'effects.json').write_text(json.dumps(dict(format=1,
            source_rate=PLAY_RATE,release_seconds=22,full_release_verified=True,
            rendered=saved,digitized=[dict(id=e['id'],sha256=digest_bytes(e['pcm']))
                                     for e in effects if e['pcm'] is not None]),indent=2)+'\n')
        # Retain source PCM and receipts, not compiler products or chip scratch.
        for name in ('opl','pcm'):shutil.rmtree(folder/name)
        opl.unlink();resample.unlink()
    built,_ = stage(out,'source-effects',dep,render)
    manifest(source,built/'samples')
    return built/'samples'


def digest_bytes(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()
