"""Compare captured SHR pictures on both runs' twenty slowest frames."""
import argparse
import json
import struct
import zlib
from pathlib import Path


def rgb(data):
    result = bytearray()
    for y in range(200):
        palette = 32256 + (data[32000+y] & 15)*32
        colors = [struct.unpack_from('<H', data, palette+2*c)[0] for c in range(16)]
        for packed in data[y*160:(y+1)*160]:
            for c in (packed >> 4, packed & 15):
                word = colors[c]
                result.extend(((word >> 8 & 15)*17, (word >> 4 & 15)*17, (word & 15)*17))
    return bytes(result)


def png(path, pixels, width=960):
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data)&0xffffffff)
    rows = b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(200))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>2I5B', width, 200, 8, 2, 0, 0, 0))+chunk(b'IDAT', zlib.compress(rows))+chunk(b'IEND', b''))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('before', help='build/tests case name prefix')
    ap.add_argument('after', help='build/tests case name prefix')
    ap.add_argument('out', type=Path)
    ap.add_argument('--views', type=int, nargs='+', default=[214, 320])
    ap.add_argument('--demos', type=int, nargs='+', default=[0, 1, 2, 3])
    ap.add_argument('--include-geometry-changes', action='store_true',
                    help='also show every frame whose indexed pixels or SCBs differ')
    ap.add_argument('--explanation', default='Magenta marks pixels whose displayed RGB value differs.')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cases = []
    html = ['<!doctype html><meta charset="utf-8"><title>Slow-frame picture comparison</title>',
            '<style>body{background:#222;color:#eee;font:16px sans-serif}img{image-rendering:pixelated;max-width:100%}a{color:#9cf}</style>',
            '<h1>Old / new / difference</h1><p>'+args.explanation+'</p>',
            '<p>Each case includes the union of both runs’ twenty slowest frames. Magenta shows changed displayed pixels.</p>']
    for view in args.views:
        for demo in args.demos:
            folders = [Path('build/tests')/f'{name}-{view}-{demo}' for name in (args.before, args.after)]
            measures = [json.loads((f/'measure.json').read_text()) for f in folders]
            frames = sorted({r['frame'] for m in measures for r in sorted(m['frame_times'], key=lambda r:r['ns'], reverse=True)[:20]})
            captures = [(f/'frames.shr').read_bytes() for f in folders]
            assert len(captures[0]) == len(captures[1]) == measures[0]['frames']*32768
            if args.include_geometry_changes:
                frames = sorted(set(frames) | {i//32768+1 for i in range(0,len(captures[0]),32768)
                                               if captures[0][i:i+32200] != captures[1][i:i+32200]})
            changed_frames = sum(captures[0][i:i+32768] != captures[1][i:i+32768] for i in range(0,len(captures[0]),32768))
            case = dict(view=view, demo=demo, changed_frames=changed_frames, frames=measures[0]['frames'],
                        before_ms=measures[0]['worst20_mean_ms'], after_ms=measures[1]['worst20_mean_ms'],
                        before_mean_ms=measures[0]['mean_ms'], after_mean_ms=measures[1]['mean_ms'], samples=[])
            html.append(f'<h2>{view}, demo {demo}: {case["before_ms"]:.3f} → {case["after_ms"]:.3f} ms</h2>')
            for n in frames:
                parts = [rgb(c[(n-1)*32768:n*32768]) for c in captures]
                changed = [parts[0][i:i+3] != parts[1][i:i+3] for i in range(0,192000,3)]
                parts.append(b''.join(b'\xff\x00\xff' if c else b'\0\0\0' for c in changed))
                name = f'v{view}-d{demo}-f{n}.png'
                pixels = b''.join(b''.join(p[y*960:(y+1)*960] for p in parts) for y in range(200))
                png(args.out/name, pixels)
                times = [next(r['ns']/1e6 for r in m['frame_times'] if r['frame']==n) for m in measures]
                case['samples'].append(dict(frame=n, changed_pixels=sum(changed), before_ms=times[0], after_ms=times[1], image=name))
                html.append(f'<p>Frame {n}; {sum(changed)} changed pixels; {times[0]:.3f} → {times[1]:.3f} ms</p><img loading="lazy" src="{name}">')
            cases.append(case)
    (args.out/'index.html').write_text('\n'.join(html)+'\n')
    (args.out/'summary.json').write_text(json.dumps(cases, indent=2)+'\n')
    for c in cases:
        worst = max(c['samples'],key=lambda r:r['changed_pixels'])
        print(c['view'], c['demo'], f'{c["before_ms"]-c["after_ms"]:.3f} ms gain;', c['changed_frames'], 'changed frames;', worst)


if __name__ == '__main__':
    main()
