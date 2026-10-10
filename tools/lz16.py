"""Lossless bank-sized LZ blocks with byte counts and 16-bit back references.

A command is one byte. Bits 0..6 hold its length; zero is followed by a
little-endian 16-bit length. Bit 7 selects literal bytes. Otherwise a signed
little-endian 16-bit backward displacement follows. Matches copy forward,
including overlap. The enclosing load record supplies the exact output size.

Lengths are split at 32767 bytes. A full 64 KiB output is allowed; the media
packer rejects encoded inputs that cannot fit its existing staging bank.
There is no palette conversion, lossy quantization, or runtime dictionary.
"""
import struct

def compress(data, chain=64, minimum=6, step=1):
    data=bytes(data)
    if not 1<=len(data)<=65536:raise ValueError('LZ16 input must be 1..65536 bytes')
    if not 1<=chain<=1024 or not 3<=minimum<=32 or step!=1:
        raise ValueError('Invalid LZ16 search settings')
    import native_host
    if native_host.library():
        commands=[]
        for start,literals,length,offset in native_host.greedy_parse(data,chain,minimum,False):
            if literals:commands.append((start,literals,0))
            if length:commands.append((start+literals,length,offset))
    else:
        commands=_commands_python(data,chain,minimum,step)
    out=bytearray();stats=dict(commands=0,literals=0,matches=0)
    for at,n,offset in commands:
        while n:
            size=min(n,32767);stats['commands']+=1
            out.append((size if size<128 else 0) | (128 if not offset else 0))
            if size>=128:out.extend(struct.pack('<H',size))
            if offset:out.extend(struct.pack('<H',(-offset)&65535));stats['matches']+=size
            else:out.extend(data[at:at+size]);stats['literals']+=size
            n-=size;at+=size
    if decode(out,len(data))!=data:raise ValueError('LZ16 round trip failed')
    return bytes(out),stats

def _commands_python(data, chain, minimum, step):
    heads={};prev=[-1]*len(data);commands=[];anchor=i=0
    def insert(at):
        if at+minimum>len(data):return
        key=data[at:at+minimum];prev[at]=heads.get(key,-1);heads[key]=at
    while i+minimum<=len(data):
        j=heads.get(data[i:i+minimum],-1);best=offset=0;left=chain
        while j>=0 and left:
            left-=1;limit=min(32767,len(data)-i)
            if best<limit and data[j+best]==data[i+best]:
                n=minimum
                while n<limit and data[j+n]==data[i+n]:n+=1
                if n>best:best=n;offset=i-j
                if best==limit:break
            j=prev[j]
        if best>=minimum:
            if i>anchor:commands.append((anchor,i-anchor,0))
            commands.append((i,best,offset))
            for at in range(i,i+best,step):insert(at)
            i+=best;anchor=i
        else:insert(i);i+=step
    if anchor<len(data):commands.append((anchor,len(data)-anchor,0))
    return commands


def decode(src,size,stats=None):
    if not 1<=size<=65536:raise ValueError('LZ16 output must be 1..65536 bytes')
    src=memoryview(src);out=bytearray();at=0;counts=dict(commands=0,literals=0,matches=0)
    def require(n):
        if at+n>len(src):raise ValueError('Truncated LZ16 block')
    while len(out)<size:
        require(1)
        cmd=src[at];at+=1;n=cmd&127
        if not n:
            require(2);n=struct.unpack_from('<H',src,at)[0];at+=2
        if not n or len(out)+n>size:raise ValueError('LZ16 output overrun')
        counts['commands']+=1
        if cmd&128:
            require(n);out.extend(src[at:at+n]);at+=n;counts['literals']+=n
        else:
            require(2)
            offset=65536-struct.unpack_from('<H',src,at)[0];at+=2
            if offset>len(out):raise ValueError('LZ16 match before output')
            counts['matches']+=n
            while n:
                k=min(n,offset);out.extend(out[-offset:len(out)-offset+k]);n-=k
    if stats is not None:stats.update(counts,consumed=at)
    return bytes(out)
