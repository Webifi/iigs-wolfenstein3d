"""HLZ: lossless LZ77 with canonical Huffman codes for the floppy store.

A unit decodes into one bank (at most 64 KiB). The 65816 decoder is
src/iigs/hlz.inc; this file is the encoder and the reference decoder.

Payload (the store keeps it as one block-padded unit):
  +0  u16  output length (0 = 65536), the loader's packed-unit convention
  +2  u8   3, the HLZ marker (0, 1 and 2 are LZ16, plan and sparse; a valid
           LZSA1 stream never starts with a token below 16)
  +3  u8   output byte 0, u8 output byte 1 (the decoder writes them again at
           the end: its 16-bit literal stores may wrap at a bank end)
  +5  u16  offset of the byte stream from the payload start
  +7  bit stream, stored backward: its first byte is the last one before the
        byte stream, and the decoder reads toward +7. Each byte gives its bits
        top bit first, every field is sent top bit first:
        header: 4 bits HCLEN-4, HCLEN x 3-bit lengths of the code-length code
        in CL_ORDER, then the code lengths of the NLL literal/length and the
        ND offset symbols, run-length coded with that code (deflate style:
        0-9 lengths, 10 = previous length 3-6 times (2 bits), 11 = 3-10 zeros
        (3 bits), 12 = 11-138 zeros (7 bits)); canonical codes, first bit =
        top bit; then the symbols. Every code is at most 9 bits (TABLE_BITS),
        so one lookup of the next 9 bits decodes it, and the codes of one length
        fill one run of the lookup table.
  byte stream: the raw bytes of offsets above 16 and of long lengths (a
  match's offset byte comes before its length bytes).

Literal/length symbols (NLL = 326):
  0-255 literal; 256 end; 257-288 match of length 3-34; 289: length 35 + byte;
  290: length = u16; 291-323 repeat match (the previous offset) of length
  2-34; 324: repeat length 35 + byte; 325: repeat length = u16.
Offset symbols (ND = 272), after a new match length:
  0-15 offset 1-16; 16-271: offset (symbol-16)*256 + byte (at least 17).
The previous offset starts at 1. Matches copy forward and may overlap.
"""
import collections
import functools
import hashlib
from pathlib import Path
import struct

MARKER = 3
TABLE_BITS = 9
NL = 32                      # direct match lengths 3..34
NLL = 326
ND = 272
END = 256
MATCH = 257                  # + length - 3
MATCH_BYTE = MATCH + NL      # 289
MATCH_WORD = MATCH_BYTE + 1  # 290
REP = MATCH_WORD + 1         # 291: + length - 2
REP_BYTE = REP + NL + 1      # 324
REP_WORD = REP_BYTE + 1      # 325
DIRECT = 16                  # offsets 1..16 are symbols 0..15
CL_ORDER = (10, 11, 12, 0, 9, 8, 7, 6, 5, 4, 3, 2, 1)
MAX_LENGTH = 65535


@functools.lru_cache(maxsize=1)
def cache_identity():
    from source_identity import source_bytes
    folder = Path(__file__).parent
    return hashlib.sha256(b''.join(source_bytes(folder/name) for name in
                                  ('hlz.py', 'native_host.py', 'host_kernels.c'))).digest()


class Error(ValueError):
    pass


# ---------------------------------------------------------------- Huffman codes

def code_lengths(freqs, limit):
    """Length-limited Huffman code lengths (package-merge). freqs: list of counts.
    One used symbol gets length 1."""
    used = [s for s, f in enumerate(freqs) if f]
    out = [0] * len(freqs)
    if not used:
        return out
    if len(used) == 1:
        out[used[0]] = 1
        return out
    if len(used) > (1 << limit):
        raise Error('too many symbols for the code length limit')
    leaves = sorted((freqs[s], s) for s in used)
    # Each item: (weight, list of symbols); package-merge over limit levels.
    original = [(w, (s,)) for w, s in leaves]
    current = list(original)
    for _ in range(limit - 1):
        packages = [(current[i][0] + current[i + 1][0], current[i][1] + current[i + 1][1])
                    for i in range(0, len(current) - 1, 2)]
        merged = []
        a = b = 0
        while a < len(original) or b < len(packages):
            if b >= len(packages) or (a < len(original) and original[a][0] <= packages[b][0]):
                merged.append(original[a]); a += 1
            else:
                merged.append(packages[b]); b += 1
        current = merged
    for _, symbols in current[:2 * len(used) - 2]:
        for s in symbols:
            out[s] += 1
    return out


def canonical(lengths):
    """Canonical codes, first bit = most significant (deflate order)."""
    maxlen = max(lengths) if lengths else 0
    count = [0] * (maxlen + 2)
    for n in lengths:
        if n:
            count[n] += 1
    code = 0
    nxt = [0] * (maxlen + 2)
    for n in range(1, maxlen + 1):
        code = (code + count[n - 1]) << 1
        nxt[n] = code
    codes = [0] * len(lengths)
    for s, n in enumerate(lengths):
        if n:
            codes[s] = nxt[n]
            nxt[n] += 1
    return codes


# ------------------------------------------------------------------ bit output

class Bits:
    """Fields top bit first; finish() returns the bytes backward (the stored order)."""
    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value, n):
        self.acc = (self.acc << n) | (value & ((1 << n) - 1))
        self.n += n
        while self.n >= 8:
            self.n -= 8
            self.out.append((self.acc >> self.n) & 255)
        self.acc &= (1 << self.n) - 1

    put_code = put

    def finish(self):
        if self.n:
            self.out.append((self.acc << (8 - self.n)) & 255)
            self.acc = 0
            self.n = 0
        return bytes(reversed(self.out))


# -------------------------------------------------------------- match search

def _common(data, i, j, limit):
    """Length of the common prefix of data[i:] and data[j:] (j < i), at most limit."""
    if data[i:i + limit] == data[j:j + limit]:
        return limit
    lo, hi = 0, limit
    n = 8
    while n < hi:
        if data[i:i + n] == data[j:j + n]:
            lo = n
            n <<= 1
        else:
            hi = n
            break
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        if data[i:i + mid] == data[j:j + mid]:
            lo = mid
        else:
            hi = mid
    return lo


def find_matches(data, chain=48, nice=96):
    """Per position: [(length, offset)...] with growing length, nearest offset first."""
    n = len(data)
    head = {}
    prev = [-1] * n
    found = [None] * n
    for i in range(n - 2):
        key = data[i:i + 3]
        j = head.get(key, -1)
        prev[i] = j
        head[key] = i
        if j < 0:
            continue
        limit = min(n - i, MAX_LENGTH)
        best = 2
        cands = None
        left = chain
        while j >= 0 and left:
            left -= 1
            if best < limit and data[j + best] == data[i + best]:
                length = _common(data, i, j, limit)
                if length > best:
                    best = length
                    if cands is None:
                        cands = []
                    cands.append((length, i - j))
                    if length >= nice or length == limit:
                        break
            j = prev[j]
        found[i] = cands
    return found


# ------------------------------------------------------------ token costs

def _length_symbol(length, rep):
    """(symbol, raw bytes) of a match length."""
    if rep:
        if length < 35:
            return REP + length - 2, 0
        if length < 35 + 256:
            return REP_BYTE, 1
        return REP_WORD, 2
    if length < 35:
        return MATCH + length - 3, 0
    if length < 35 + 256:
        return MATCH_BYTE, 1
    return MATCH_WORD, 2


def _offset_symbol(offset):
    if offset <= DIRECT:
        return offset - 1, 0
    return DIRECT + (offset >> 8), 1


# ------------------------------------------------------------ optimal parse

def _parse(data, found, lit_cost, off_cost, nice):
    """Shortest path over positions with the given symbol costs (bits).
    Tokens: int literal, or (length, offset, rep)."""
    n = len(data)
    inf = float('inf')
    cost = [inf] * (n + 1)
    back = [None] * (n + 1)
    reps = [1] * (n + 1)
    cost[0] = 0.0
    # length symbol costs for every length, new and repeat
    new_len = [0.0] * 35
    for length in range(3, 35):
        new_len[length] = lit_cost[MATCH + length - 3]
    rep_len = [0.0] * 35
    for length in range(2, 35):
        rep_len[length] = lit_cost[REP + length - 2]
    byte_new = lit_cost[MATCH_BYTE] + 8
    word_new = lit_cost[MATCH_WORD] + 16
    byte_rep = lit_cost[REP_BYTE] + 8
    word_rep = lit_cost[REP_WORD] + 16
    off_direct = off_cost[:DIRECT]
    off_hi = off_cost[DIRECT:]
    i = 0
    while i < n:
        c = cost[i]
        if c == inf:
            i += 1
            continue
        r = reps[i]
        nxt = c + lit_cost[data[i]]
        if nxt < cost[i + 1]:
            cost[i + 1] = nxt
            back[i + 1] = None
            reps[i + 1] = r
        # repeat match
        replen = 0
        if r <= i and data[i] == data[i - r]:
            replen = _common(data, i, i - r, min(n - i, MAX_LENGTH))
            if replen >= 2:
                if replen >= nice:
                    lengths = (replen,)
                else:
                    lengths = range(2, replen + 1)
                for length in lengths:
                    if length < 35:
                        lc = rep_len[length]
                    elif length < 291:
                        lc = byte_rep
                    else:
                        lc = word_rep
                    nxt = c + lc
                    if nxt < cost[i + length]:
                        cost[i + length] = nxt
                        back[i + length] = (i, length, r, True)
                        reps[i + length] = r
        cands = found[i] if i < len(found) else None
        longest = replen
        if cands:
            lo = 3
            for length, offset in cands:
                if offset == r:
                    lo = length + 1
                    continue
                if offset <= DIRECT:
                    oc = off_direct[offset - 1]
                else:
                    oc = off_hi[offset >> 8] + 8
                base = c + oc
                if length >= nice:
                    lengths = (length,)
                else:
                    lengths = range(lo, length + 1)
                for ln in lengths:
                    if ln < 35:
                        lc = new_len[ln]
                    elif ln < 291:
                        lc = byte_new
                    else:
                        lc = word_new
                    nxt = base + lc
                    if nxt < cost[i + ln]:
                        cost[i + ln] = nxt
                        back[i + ln] = (i, ln, offset, False)
                        reps[i + ln] = offset
                lo = length + 1
                if length > longest:
                    longest = length
        if longest >= nice:
            # A long match: no other path starts inside it.
            i += longest
            continue
        i += 1
    tokens = []
    i = n
    while i > 0:
        b = back[i]
        if b is None:
            i -= 1
            tokens.append(data[i])
        else:
            start, length, offset, rep = b
            tokens.append((length, offset, rep))
            i = start
    tokens.reverse()
    return tokens


def _symbols(tokens):
    lit = [0] * NLL
    off = [0] * ND
    raw = 0
    for t in tokens:
        if isinstance(t, int):
            lit[t] += 1
            continue
        length, offset, rep = t
        s, e = _length_symbol(length, rep)
        lit[s] += 1
        raw += e
        if not rep:
            s, e = _offset_symbol(offset)
            off[s] += 1
            raw += e
    lit[END] += 1
    return lit, off, raw


def _check_reps(tokens):
    """The parse marks repeat matches against the path's own previous offset."""
    prev = 1
    for t in tokens:
        if isinstance(t, int):
            continue
        length, offset, rep = t
        if rep and offset != prev:
            raise Error('repeat match with a different offset')
        prev = offset


# ------------------------------------------------------------------- header

def _rle(lengths):
    out = []
    i = 0
    n = len(lengths)
    while i < n:
        value = lengths[i]
        j = i
        while j < n and lengths[j] == value:
            j += 1
        run = j - i
        if value == 0:
            while run >= 11:
                r = min(run, 138)
                out.append((12, 7, r - 11))
                run -= r
            if run >= 3:
                out.append((11, 3, run - 3))
                run = 0
            out.extend([(0, 0, 0)] * run)
        else:
            out.append((value, 0, 0))
            run -= 1
            while run >= 3:
                r = min(run, 6)
                out.append((10, 2, r - 3))
                run -= r
            out.extend([(value, 0, 0)] * run)
        i = j
    return out


def _write_header(bits, lengths):
    runs = _rle(lengths)
    freq = [0] * 13
    for s, _, _ in runs:
        freq[s] += 1
    cl = code_lengths(freq, 7)
    count = 13
    while count > 4 and cl[CL_ORDER[count - 1]] == 0:
        count -= 1
    bits.put(count - 4, 4)
    for k in range(count):
        bits.put(cl[CL_ORDER[k]], 3)
    codes = canonical(cl)
    for s, e, v in runs:
        bits.put_code(codes[s], cl[s])
        if e:
            bits.put(v, e)


def encode_tokens(data, tokens):
    _check_reps(tokens)
    lit, off, _ = _symbols(tokens)
    ll = code_lengths(lit, TABLE_BITS)
    dl = code_lengths(off, TABLE_BITS)
    lcode = canonical(ll)
    dcode = canonical(dl)
    bits = Bits()
    _write_header(bits, ll + dl)
    raw = bytearray()
    for t in tokens:
        if isinstance(t, int):
            bits.put_code(lcode[t], ll[t])
            continue
        length, offset, rep = t
        s, e = _length_symbol(length, rep)
        bits.put_code(lcode[s], ll[s])
        if not rep:
            # the offset's byte comes before the length's bytes (the decoder's order)
            d, e = _offset_symbol(offset)
            bits.put_code(dcode[d], dl[d])
            if e:
                raw.append(offset & 255)
        if s in (MATCH_BYTE, REP_BYTE):
            raw.append(length - 35)
        elif s in (MATCH_WORD, REP_WORD):
            raw.extend(struct.pack('<H', length))
    bits.put_code(lcode[END], ll[END])
    stream = bits.finish()
    size = len(data)
    head = struct.pack('<HBBBH', size & 0xffff, MARKER, data[0], data[1] if size > 1 else 0, 7 + len(stream))
    return head + stream + bytes(raw)


def compress(data, passes=3, chain=48, nice=96):
    """The smallest of `passes` cost-refined parses. Raises Error for units the
    format does not take (fewer than 2 bytes, more than 65536)."""
    data = bytes(data)
    if not 2 <= len(data) <= 65536:
        raise Error('HLZ unit must be 2..65536 bytes')
    import native_host
    native = native_host.HLZMatches(data, chain, nice) if native_host.library() and chain >= 0 else None
    try:
        return _compress(data, passes, chain, nice, native)
    finally:
        if native is not None:
            native.close()


def _compress(data, passes, chain, nice, native):
    found = None if native is not None else find_matches(data, chain, nice)
    lit_cost = [8.0] * 256 + [9.0] + [6.0] * (NLL - 257)
    off_cost = [5.0] * DIRECT + [7.0] * (ND - DIRECT)
    best = None
    for _ in range(passes):
        tokens = native.parse(lit_cost, off_cost, nice) if native is not None else _parse(data, found, lit_cost, off_cost, nice)
        payload = encode_tokens(data, tokens)
        if best is None or len(payload) < len(best):
            best = payload
        lit, off, _ = _symbols(tokens)
        ll = code_lengths(lit, TABLE_BITS)
        dl = code_lengths(off, TABLE_BITS)
        # unused symbols get a high price so a later pass may still try them
        lit_cost = [float(n) if n else 11.0 for n in ll]
        off_cost = [float(n) if n else 11.0 for n in dl]
    if decode(best, len(data)) != data:
        raise Error('HLZ round trip failed')
    return best


def cycles(stats):
    """Estimated 65816 decode cycles of a unit from decode() stats (nominal cycles,
    fitted to tools/check_hlz.py runs of src/iigs/hlz.inc on the store units)."""
    return (SETUP_CYCLES + LITERAL_CYCLES * stats.get('literals', 0) + MATCH_CYCLES * stats.get('matches', 0)
            + FAR_CYCLES * stats.get('far', 0) + REPEAT_CYCLES * stats.get('reps', 0)
            + 7 * stats.get('match_bytes', 0))


SETUP_CYCLES = 120000
LITERAL_CYCLES = 50
MATCH_CYCLES = 165
FAR_CYCLES = 20
REPEAT_CYCLES = 115


# ------------------------------------------------------------ reference decoder

class _Reader:
    """The bit stream of src[start:end], stored backward, read top bit first."""
    def __init__(self, src, start, end):
        self.src = bytes(reversed(bytes(src[start:end])))
        self.at = 0         # byte
        self.k = 0          # bit within the byte, 0 = the top bit

    def bit(self):
        if self.at >= len(self.src):
            raise Error('truncated HLZ bit stream')
        b = (self.src[self.at] >> (7 - self.k)) & 1
        self.k += 1
        if self.k == 8:
            self.k = 0
            self.at += 1
        return b

    def bits(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v

    def window(self):
        """The next TABLE_BITS bits as a number, first bit on top (zeros past the end)."""
        w = 0
        for i in range(3):
            w = (w << 8) | (self.src[self.at + i] if self.at + i < len(self.src) else 0)
        return (w >> (24 - self.k - TABLE_BITS)) & ((1 << TABLE_BITS) - 1)

    def skip(self, n):
        self.k += n
        self.at += self.k >> 3
        self.k &= 7


def _decode_cl(reader, cl):
    """Bit-by-bit canonical decode (first bit = most significant)."""
    count = [0] * 8
    for n in cl:
        count[n] += 1
    count[0] = 0
    order = sorted((n, s) for s, n in enumerate(cl) if n)
    symbols = [s for _, s in order]
    code = first = index = 0
    for n in range(1, 8):
        code |= reader.bit()
        c = count[n]
        if code - first < c:
            return symbols[index + code - first]
        index += c
        first = (first + c) << 1
        code <<= 1
    raise Error('invalid HLZ code-length code')


def read_lengths(reader):
    count = reader.bits(4) + 4
    if count > 13:
        raise Error('invalid HLZ header')
    cl = [0] * 13
    for k in range(count):
        cl[CL_ORDER[k]] = reader.bits(3)
    lengths = []
    while len(lengths) < NLL + ND:
        s = _decode_cl(reader, cl)
        if s < 10:
            lengths.append(s)
        elif s == 10:
            if not lengths:
                raise Error('HLZ repeat without a length')
            lengths.extend([lengths[-1]] * (3 + reader.bits(2)))
        elif s == 11:
            lengths.extend([0] * (3 + reader.bits(3)))
        else:
            lengths.extend([0] * (11 + reader.bits(7)))
    if len(lengths) != NLL + ND or max(lengths) > TABLE_BITS:
        raise Error('invalid HLZ code lengths')
    return lengths[:NLL], lengths[NLL:]


def table(lengths):
    """The decoder's lookup table: index = next TABLE_BITS bits -> (symbol, length).
    The codes of one length fill one run of entries, in symbol order."""
    codes = canonical(lengths)
    out = [None] * (1 << TABLE_BITS)
    for s, n in enumerate(lengths):
        if not n:
            continue
        first = codes[s] << (TABLE_BITS - n)
        for j in range(first, first + (1 << (TABLE_BITS - n))):
            out[j] = (s, n)
    return out


def decode(payload, size, stats=None):
    payload = memoryview(payload)
    if len(payload) < 7 or payload[2] != MARKER:
        raise Error('not an HLZ payload')
    if (struct.unpack_from('<H', payload)[0] or 65536) != size:
        raise Error('HLZ output size differs')
    raw_at = struct.unpack_from('<H', payload, 5)[0]
    reader = _Reader(payload, 7, raw_at)
    ll, dl = read_lengths(reader)
    lt, dt = table(ll), table(dl)
    out = bytearray()
    prev = 1
    counts = collections.Counter()

    def raw(n):
        nonlocal raw_at
        if raw_at + n > len(payload):
            raise Error('truncated HLZ byte stream')
        v = int.from_bytes(payload[raw_at:raw_at + n], 'little')
        raw_at += n
        return v
    counts['header_bits'] = reader.at * 8 + reader.k
    while True:
        e = lt[reader.window()]
        if e is None:
            raise Error('invalid HLZ code')
        s, n = e
        reader.skip(n)
        if s < 256:
            out.append(s)
            counts['literals'] += 1
            continue
        if s == END:
            break
        if s >= REP:
            offset = prev
            code = s - REP
            counts['reps'] += 1
        else:
            e = dt[reader.window()]
            if e is None:
                raise Error('invalid HLZ offset code')
            d, n = e
            reader.skip(n)
            if d < DIRECT:
                offset = d + 1
            else:
                offset = ((d - DIRECT) << 8) | raw(1)
                counts['far'] += 1
            code = s - MATCH + 1
            counts['matches'] += 1
        # code: the length - 2 (0-32), 33 = 35 + a byte, 34 = a word
        if code < 33:
            length = code + 2
        elif code == 33:
            length = 35 + raw(1)
        else:
            length = raw(2)
        if offset > len(out) or length < 2 or len(out) + length > size:
            raise Error('invalid HLZ match')
        counts['match_bytes'] += length
        for _ in range(length):
            out.append(out[-offset])
        prev = offset
    if len(out) != size:
        raise Error('HLZ output length differs')
    if out[0] != payload[3] or (size > 1 and out[1] != payload[4]):
        raise Error('HLZ first bytes differ')
    if stats is not None:
        stats.update(counts, consumed_bits=reader.at * 8 + reader.k, raw_end=raw_at)
    return bytes(out)
