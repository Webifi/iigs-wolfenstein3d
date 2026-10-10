"""The unrolled parts of src/iigs/hlz.inc: the eight per-bit-offset copies of the decode
loop with their dispatch tables (block "loop"), and the eight copies of the code-length
reader with theirs (block "header"). Each block sits in hlz.inc between two marker lines.

The bit stream is read backward: [HLZ_BP] gives the byte before the current one
in its low half and the current byte in its high half; bit offset k (0 = top bit)
of the current byte is bit 15-k of that word.

Usage: python3 tools/gen_hlz_copies.py --check src/iigs/hlz.inc   (exit 1 when a block differs)
       python3 tools/gen_hlz_copies.py --update src/iigs/hlz.inc  (rewrite both blocks)
       python3 tools/gen_hlz_copies.py loop|header                (print one block)
"""
I = ' ' * 14


def lab(name, text=''):
    pad = max(1, 14 - len(name) - 1)
    return name + ':' + (' ' * pad + text if text else '')


def shift9(k):
    """9-bit window * 2 = (word >> (6 - k)) & $3FE."""
    if k == 7:
        return [I + 'asl a']
    return [I + 'lsr a'] * (6 - k)


def shift7(k):
    """7-bit window * 2 = (word >> (8 - k)) & $FE."""
    if k <= 3:
        return [I + 'asl a'] * k + [I + 'xba']
    return [I + 'lsr a'] * (8 - k)


def entry(prefix, m):
    k, dec = m & 7, m >> 3
    return f'.word0 ({prefix}{k}{["", "a", "b"][dec]})'


def words(label, items, per=4):
    out = []
    for i in range(0, len(items), per):
        head = lab(label, '.word ') if i == 0 else I + '.word '
        out.append(head + ', '.join(items[i:i + per]))
    return out


def loop():
    out = [';;; ---------------------------------------------------------- decode loop',
           ';;; Copy k reads the next 9 bits from bit k of the current byte. Entry hlzLk:',
           ';;; no DEC, hlzLka: one DEC, hlzLkb: two DEC of HLZ_BP first.']
    for k in range(8):
        out.append(lab(f'hlzL{k}b', 'dec dp:HLZ_BP'))
        out.append(lab(f'hlzL{k}a', 'dec dp:HLZ_BP'))
        out.append(lab(f'hlzL{k}', 'lda [HLZ_BP]'))
        out += shift9(k)
        out.append(I + 'and ##0x03fe')
        out.append(I + 'tax')
        out.append(lab(f'hlzLT{k}', 'lda long:0x000000,x       ; the literal/length table'))
        out.append(I + 'sta abs:0,y                ; a literal (after a code: junk)')
        out.append(I + 'iny')
        out.append(I + 'xba')
        out.append(I + 'and ##0x00ff')
        out.append(I + 'tax')
        out.append(I + f'jmp (abs:.word0 (hlzAdvL+{2 * k}),x)')
    out += [';;; A new match (its length code is the junk byte at Y-1): copy k reads the',
            ';;; offset code from bit k.']
    for k in range(8):
        out.append(lab(f'hlzM{k}b', 'dec dp:HLZ_BP'))
        out.append(lab(f'hlzM{k}a', 'dec dp:HLZ_BP'))
        out.append(lab(f'hlzM{k}', 'lda [HLZ_BP]'))
        out += shift9(k)
        out.append(I + 'and ##0x03fe')
        out.append(I + 'tax')
        out.append(lab(f'hlzDT{k}', 'lda long:0x000000,x       ; the offset table'))
        out.append(I + 'jsr abs:.word0 (hlzNew)')
        out.append(I + f'jmp (abs:.word0 (hlzAdvL+{2 * k}),x)')
    out.append(';;; A repeat match (the previous offset), then the literal copy k.')
    for k in range(8):
        out.append(lab(f'hlzR{k}b', 'dec dp:HLZ_BP'))
        out.append(lab(f'hlzR{k}a', 'dec dp:HLZ_BP'))
        out.append(lab(f'hlzR{k}', 'jsr abs:.word0 (hlzRep)'))
        out.append(I + f'jmp abs:.word0 (hlzL{k})')
    out += [';;; Word k + n: the copy for bit offset k + n (with its DECs) after a code of',
            ';;; n bits; +16 a new match, +32 the end, +48 a repeat match.']
    items = [entry('hlzL', m) for m in range(17)]
    items += [entry('hlzM', m) for m in range(1, 17)]
    items += ['.word0 (hlzEnd)'] * 16
    items += [entry('hlzR', m) for m in range(1, 17)]
    assert len(items) == 65
    out += words('hlzAdvL', items)
    out.append(';;; The 24-bit table operands that the setup patches (8 literal, 8 offset).')
    out += words('hlzSites', [f'.word0 (hlzLT{k})' for k in range(8)] + [f'.word0 (hlzDT{k})' for k in range(8)])
    return out


def header():
    out = [';;; The code lengths: copy k reads the next code-length code (7 bits from bit',
           ';;; k) and writes a length 0-9 as a word (its junk byte is the next length).',
           ';;; Y = lengths written; DBR = this bank.']
    for k in range(8):
        out.append(lab(f'hH{k}b', 'dec dp:HLZ_BP'))
        out.append(lab(f'hH{k}a', 'dec dp:HLZ_BP'))
        out.append(lab(f'hH{k}', 'cpy ##HLZ_LENGTHS'))
        out.append(I + f'bcs hHDone{k}')
        out.append(I + 'lda [HLZ_BP]')
        out += shift7(k)
        out.append(I + 'and ##0x00fe')
        out.append(I + 'tax')
        out.append(I + 'lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8')
        out.append(I + 'sta [HLZ_DST],y')
        out.append(I + 'iny')
        out.append(I + 'xba')
        out.append(I + 'and ##0x00ff')
        out.append(I + 'tax')
        out.append(I + f'jmp (abs:.word0 (hAdvH+{2 * k}),x)')
        out.append(lab(f'hHDone{k}', f'lda ##{k}'))
        out.append(I + 'jmp abs:.word0 (hHeaderDone)')
    out.append(';;; A run symbol (10-12): its extra bits follow at bit k.')
    for k in range(8):
        out.append(lab(f'hS{k}b', 'dec dp:HLZ_BP'))
        out.append(lab(f'hS{k}a', 'dec dp:HLZ_BP'))
        out.append(lab(f'hS{k}', f'lda ##{k}'))
        out.append(I + 'jmp abs:.word0 (hRun)')
    out += [';;; Word k + n: the header copy for bit offset k + n after a code of n bits;',
            ';;; +16 a run symbol.']
    items = [entry('hH', m) for m in range(15)]
    items += ['.word0 (hH0)'] * 2  # (unused: 1 <= k + n <= 14)
    items += [entry('hS', m) for m in range(1, 15)]
    assert len(items) == 31
    out += words('hAdvH', items)
    return out


def marker(name, start):
    return (f';;; >>> {name}: generated by tools/gen_hlz_copies.py, do not edit by hand' if start
            else f';;; <<< {name}: end of the generated block')


def blocks(text):
    """text with both blocks generated again; ValueError when a marker is missing."""
    for name, make in (('loop', loop), ('header', header)):
        begin, end = marker(name, True), marker(name, False)
        if text.count(begin) != 1 or text.count(end) != 1:
            raise ValueError(f'hlz.inc: the {name} markers are missing')
        a = text.index(begin) + len(begin) + 1
        b = text.index(end)
        text = text[:a] + '\n'.join(make()) + '\n' + text[b:]
    return text


if __name__ == '__main__':
    import sys
    from pathlib import Path
    if sys.argv[1:2] in (['--check'], ['--update']):
        path = Path(sys.argv[2])
        old = path.read_text()
        new = blocks(old)
        if sys.argv[1] == '--update':
            if new != old:
                path.write_text(new)
        elif new != old:
            sys.exit(f'{path}: a generated block differs from tools/gen_hlz_copies.py')
    else:
        print('\n'.join(loop() if sys.argv[1:] == ['loop'] else header()))
