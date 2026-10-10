"""Pure-Python LZSA1 blocks with an externally supplied output length.

Uses the published stream-block grammar (the final command is literals only):
https://github.com/emmanuel-marty/lzsa/blob/master/BlockFormat_LZSA1.md
Each independent block fits one 65816 bank. No dictionary or native host tool
is needed. This encoder favors long matches and inexpensive decode commands.
"""
import struct


class BlockTooLarge(ValueError):
    """A literal run cannot be represented by a standard LZSA1 block."""


def _length(n, base, short, long):
    if n > 65535:
        raise BlockTooLarge('LZSA1 length exceeds 65535; store raw or split the unit')
    if n < base:
        return b''
    if n < 256:
        return bytes((n-base,))
    if n < 512:
        return bytes((short, n-256))
    return bytes((long,))+struct.pack('<H', n & 65535)


def encode_tokens(data, tokens):
    out = bytearray()
    for start, literals, length, distance in tokens:
        out.append((128 if distance > 256 else 0) | (min(literals, 7)<<4) | min(max(length-3, 0), 15))
        out.extend(_length(literals, 7, 250, 249))
        out.extend(data[start:start+literals])
        if not length:
            continue
        out.append((-distance) & 255)
        if distance > 256:
            out.append(((-distance) >> 8) & 255)
        out.extend(_length(length, 18, 239, 238))
    return bytes(out)


def compress(data, chain=32):
    data=bytes(data)
    if not 1 <= len(data) <= 65536:
        raise ValueError('LZSA1 block must contain 1..65536 bytes')
    import native_host
    tokens = native_host.greedy_parse(data,chain,3,True) if native_host.library() and chain>=0 else _tokens_python(data,chain)
    packed=encode_tokens(data,tokens)
    if decode(packed,len(data))!=data:raise ValueError('LZSA1 round trip')
    return packed


def _tokens_python(data, chain):
    heads={};prev=[-1]*len(data);tokens=[];anchor=i=0
    def insert(at):
        if at+2 >= len(data): return
        key=data[at:at+3];prev[at]=heads.get(key,-1);heads[key]=at
    while i+3 < len(data):
        j=heads.get(data[i:i+3],-1);best=0;offset=0;left=chain
        while j>=0 and i-j<=65535 and left:
            left-=1
            limit=len(data)-i-1
            if best < limit and data[j+best]==data[i+best]:
                n=0
                while n<limit and data[j+n]==data[i+n]: n+=1
                if n>best: best=n;offset=i-j
                if best==limit:break
            j=prev[j]
        if best>=3:
            tokens.append((anchor,i-anchor,best,offset))
            for at in range(i,i+best):insert(at)
            i+=best;anchor=i
        else:
            insert(i);i+=1
    tokens.append((anchor,len(data)-anchor,0,0))
    return tokens


def decode(src, size, stats=None):
    src=memoryview(src);at=0;out=bytearray();commands=0;extensions=0
    def byte():
        nonlocal at
        if at>=len(src):raise ValueError('Truncated LZSA1 block')
        n=src[at];at+=1;return n
    def length(n, base, short, long):
        nonlocal extensions
        if n<base:return n
        extensions+=1;x=byte()
        if x==short:return 256+byte()
        if x==long:
            value=byte() | byte()<<8
            if not value:raise ValueError('Zero extended LZSA1 length')
            return value
        if x>short:raise ValueError('Invalid LZSA1 length')
        return base+x
    while len(out)<size:
        token=byte();commands+=1
        n=length((token>>4)&7,7,250,249)
        if len(out)+n>size or at+n>len(src):raise ValueError('LZSA1 literal overrun')
        out.extend(src[at:at+n]);at+=n
        if len(out)==size:break
        lo=byte();hi=byte() if token&128 else 255
        distance=65536-(lo | hi<<8)
        n=length((token&15)+3,18,239,238)
        if distance>len(out) or len(out)+n>size:raise ValueError('LZSA1 match overrun')
        while n:
            take=min(n,distance);out.extend(out[-distance:len(out)-distance+take]);n-=take
    if stats is not None:stats.update(commands=commands,extensions=extensions,consumed=at)
    return bytes(out)
