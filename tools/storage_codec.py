"""Select lossless level units for estimated device read plus native decode time."""
import struct
from pathlib import Path
import b1
import lzsa1
import lz16
import hashlib
import functools
from game_profile import read_toml


@functools.lru_cache(maxsize=None)
def encoder_source(module):
    import native_host
    from source_identity import source_bytes
    host = Path(native_host.__file__)
    return source_bytes(module.__file__)+source_bytes(host)+source_bytes(host.with_name('host_kernels.c'))


class NoBankSafeEncoding(ValueError):
    """The caller must split this unit before writing its load records."""


def policy(root, medium='hd'):
    doc=read_toml(Path(root)/'profiles/storage/stock.toml')
    if medium not in ('hd','floppy','b1','raw','lzsa1'):
        raise ValueError('Unknown storage policy: '+medium)
    values=dict(doc['decode'], **doc['floppy' if medium=='floppy' else 'hd'], **doc['budget'], **doc['encode'])
    if any(not isinstance(v,int) or v<=0 for v in values.values()):
        raise ValueError('Storage cycle estimates must be positive integers')
    if not 1<=values['retain_load_gain_percent']<=100:
        raise ValueError('Retained load gain must be 1..100 percent')
    if values['max_store_mib'] > 58:
        raise ValueError('Level store budget exceeds the two-volume allocation (58 MiB)')
    return medium, values


def candidates(data, cache, settings, force_raw=False, b1_allowed=True):
    medium,c=settings;n=len(data);head=struct.pack('<H',n&65535)
    choices=[]
    def add(name,payload,decode_cycles):
        blocks=(len(payload)+511)//512
        if len(payload)<=65536:
            choices.append(dict(codec=name,payload=payload,blocks=blocks,
                                estimated_cycles=blocks*c['block_cycles']+decode_cycles))
    if force_raw or n%512==0:add('raw',data,0)
    if force_raw:return choices
    if b1_allowed:
        packed=b1.compress(data,cache);stats={}
        if b1.decode(packed,n,stats)!=data:raise ValueError('B1 round trip')
        cost=n*c['copy_byte_cycles']+sum(stats[k]*c['b1_'+label+'_cycles'] for k,label in
            [('bits','bit'),('gamma','gamma'),('refills','refill'),('literals','literal'),
             ('matches','match'),('new_offsets','new_offset')])
        add('b1',head+packed,cost)
    import shared_cache
    def encode_lzsa():
        try:
            return lzsa1.compress(data)
        except lzsa1.BlockTooLarge:
            return b''
    if shared_cache.folder():
        packed = shared_cache.codec('lzsa1', encoder_source(lzsa1), data, encode_lzsa) or None
    else:
        folder=Path(cache).parent/'lzsa1cache';folder.mkdir(exist_ok=True)
        path=folder/(hashlib.sha256(encoder_source(lzsa1)+data).hexdigest()+'.lzsa1')
        if not path.exists():shared_cache.atomic(path, encode_lzsa())
        packed=path.read_bytes() or None
    if packed is not None:
        stats={}
        if lzsa1.decode(packed,n,stats)!=data:raise ValueError('LZSA1 round trip')
        add('lzsa1',head+packed,n*c['copy_byte_cycles']+stats['commands']*c['lzsa_command_cycles']+
            stats['extensions']*c['lzsa_extension_cycles'])
    chain=c['lz16_search_chain'];minimum=c['lz16_minimum_match']
    identity=encoder_source(lz16)+struct.pack('<HH',chain,minimum)
    if shared_cache.folder():
        packed=shared_cache.codec('lz16', identity, data,
                                  lambda: lz16.compress(data,chain=chain,minimum=minimum)[0])
    else:
        folder=Path(cache).parent/'lz16cache';folder.mkdir(exist_ok=True)
        path=folder/(hashlib.sha256(identity+data).hexdigest()+'.lz16')
        if not path.exists():
            packed,_=lz16.compress(data,chain=chain,minimum=minimum)
            shared_cache.atomic(path,packed)
        packed=path.read_bytes()
    stats={}
    if lz16.decode(packed,n,stats)!=data:raise ValueError('LZ16 cached unit differs')
    add('lz16',head+b'\0'+packed,n*c['copy_byte_cycles']+stats['commands']*c['lz16_command_cycles'])
    # Exact-length literal blocks handle raw tails without writing disk padding
    # into the next live allocation. They use the same LZSA1 decoder.
    if medium=='raw' and not any(x['codec']=='raw' for x in choices):
        payload=lzsa1.encode_tokens(data,[(0,n,0,0)])
        add('literal',head+payload,n*c['copy_byte_cycles']+c['lzsa_command_cycles'])
    if not choices:raise NoBankSafeEncoding('No bank-safe encoding fits the staging bank')
    return choices


def choose(choices, medium):
    if medium in ('b1','raw','lzsa1'):
        preferred=[x for x in choices if x['codec']==medium or medium=='raw' and x['codec']=='literal']
        if preferred:return min(preferred,key=lambda x:x['estimated_cycles'])
    return min(choices,key=lambda x:(x['estimated_cycles'],x['blocks']))


def decode(payload, size, codec):
    if codec=='raw':return bytes(payload[:size])
    n=struct.unpack_from('<H',payload)[0] or 65536
    if n!=size:raise ValueError('Packed unit output size differs')
    if codec=='b1':return b1.decode(payload[2:],size)
    if codec=='plan':
        if payload[2]!=1:raise ValueError('Invalid shared-plan marker')
        return lz16.decode(payload[3:],size)
    if codec=='lz16':
        if payload[2]!=0:raise ValueError('Invalid fixed-command marker')
        return lz16.decode(payload[3:],size)
    if codec in ('lzsa1','literal'):return lzsa1.decode(payload[2:],size)
    if codec=='hlz':
        import hlz
        return hlz.decode(payload,size)
    raise ValueError('Unknown level codec: '+codec)


def decode_sparse(payload, size, initial):
    """Decode retained spans; zero-offset commands preserve shared-art holes."""
    if len(initial)!=size or (struct.unpack_from('<H',payload)[0] or 65536)!=size or payload[2]!=2:
        raise ValueError('Invalid sparse output or marker')
    out=bytearray(initial);written=bytearray(size);at=3;pos=0
    while pos<size:
        if at>=len(payload):raise ValueError('Truncated sparse command')
        command=payload[at];at+=1;n=command&127
        if not n:
            if at+2>len(payload):raise ValueError('Truncated sparse length')
            n=struct.unpack_from('<H',payload,at)[0];at+=2
        if not n or pos+n>size:raise ValueError('Sparse output overrun')
        if command&128:
            if at+n>len(payload):raise ValueError('Truncated sparse literal')
            out[pos:pos+n]=payload[at:at+n];written[pos:pos+n]=b'\1'*n;at+=n
        else:
            if at+2>len(payload):raise ValueError('Truncated sparse displacement')
            offset=struct.unpack_from('<H',payload,at)[0];at+=2
            if offset:
                distance=65536-offset
                for i in range(pos,pos+n):
                    source=i-distance
                    if source<0 or not written[source]:raise ValueError('Sparse match reads an unwritten hole')
                    out[i]=out[source];written[i]=1
        pos+=n
    return bytes(out)
