"""Estimated cycles per label for one traced frame (nominal 65816 cycles, no wait states), from the instruction counts.

  python3 tools/demo_check.py 0 --name NAME --disk DISK --elf ELF --view 214 --trace-frame 892 --trace-scope frame
  python3 tools/paint_cycles.py NAME [TOP]            # whole frame, TOP labels (default 40)
  python3 tools/paint_cycles.py NAME 40 paint         # only the paint code (paintFrame .. paintListDone)
The estimate is 2.8 MHz nominal: about 10% below the stock timing with refresh and slow cycles. Use it to rank labels.
"""
import bisect, collections, json, re, struct, sys
from pathlib import Path


def cycles(ins):
    m = ins.split(); op = m[0]; arg = ins[len(op):].strip()
    if arg == '' or arg == 'a': base = 2
    elif arg.startswith('#'): base = 2 if op != 'pea' else 5
    elif arg.startswith('('):
        base = 5 if op == 'jmp' else 6 if op == 'pei' else 6 if ',y' in arg else 7 if ',x)' in arg else 5
    elif arg.startswith('['): base = 7
    elif re.match(r'^\$[0-9a-f]{6}', arg): base = 6
    elif re.match(r'^\$[0-9a-f]{3,4}', arg): base = 6 if (',x' in arg or ',y' in arg) else 4
    elif re.match(r'^\$[0-9a-f]{1,2}', arg): base = 4 if ',x' not in arg else 5
    else: base = 3
    if op in ('bra', 'bcc', 'bcs', 'beq', 'bne', 'bmi', 'bpl', 'bvs', 'bvc'): base = 3
    if op in ('pha', 'phx', 'phy', 'php'): base = 4
    if op in ('pla', 'plx', 'ply', 'plb', 'plp'): base = 5
    if op in ('rtl', 'rts'): base = 6
    if op in ('jsr', 'jmp') and not arg.startswith('('): base = 4 if op == 'jmp' else 6
    if op in ('xba', 'sep', 'rep'): base = 3
    if op in ('tsc', 'tcs'): base = 2
    return base


def main():
    name = sys.argv[1]; top = int(sys.argv[2]) if len(sys.argv) > 2 else 40; only = sys.argv[3] if len(sys.argv) > 3 else ''
    D = Path(__file__).resolve().parents[1] / 'build/tests' / name
    raw = (D / 'profile.elf').read_bytes(); so = struct.unpack_from('<I', raw, 32)[0]; ss, sn = struct.unpack_from('<HH', raw, 46)
    secs = [struct.unpack_from('<10I', raw, so + i * ss) for i in range(sn)]; syms = []
    for sec in secs:
        if sec[1] != 2: continue
        strings = secs[sec[6]]
        for i in range(sec[4], sec[4] + sec[5], 16):
            n, v, size, info, other, idx = struct.unpack_from('<IIIBBH', raw, i)
            if n and idx:
                start = strings[4] + n; syms.append((v, raw[start:raw.index(b'\0', start)].decode()))
    syms.sort(); addrs = [s[0] for s in syms]; d = {n: v for v, n in syms}
    lo, hi = (d['paintFrame'], d['paintListDone']) if only == 'paint' else (0, 1 << 24)
    tot = collections.Counter(); ins = collections.Counter()
    for k, v in json.loads((D / 'instruction-counts.json').read_text()).items():
        a = int(k, 16)
        if not lo <= a < hi: continue
        name_ = syms[bisect.bisect_right(addrs, a) - 1][1]
        tot[name_] += cycles(v['instruction']) * v['count']; ins[name_] += v['count']
    print('%s: %.1f ms at 2.8 MHz nominal' % (name, sum(tot.values()) / 2.8e3))
    for n, c in tot.most_common(top): print('%-26s %8d cyc %6.2f ms %7d instr' % (n, c, c / 2.8e3, ins[n]))


if __name__ == '__main__':
    main()
