"""Compile music commands into contiguous DOC-register batches at build time.

Each oscillator's ordered writes remain exactly the same. Only writes to
different oscillators may exchange order within their existing score wake.
Volume operands remain exponent indices into the master volume table.
"""
from collections import defaultdict,deque,Counter
import struct
import unit2


def batches(writes):
    queues=defaultdict(deque)
    for i,(reg,val) in enumerate(writes):
        assert 4<=reg&31<28
        queues[reg&31].append((i,reg,val))
    out=[]
    while any(queues.values()):
        fronts={q[0][1]:q[0] for q in queues.values() if q}
        choices=[]
        for reg in fronts:
            count=1
            while reg+count in fronts and (reg+count)&224==reg&224:count+=1
            choices.append((-count,fronts[reg][0],reg))
        negative,_,start=min(choices);count=-negative
        values=[]
        for reg in range(start,start+count):
            _,got,val=queues[reg&31].popleft();assert got==reg
            values.append(val)
        out.append((start,values))
    # Independent per-oscillator sequence equality catches illegal reordering.
    old=defaultdict(list);new=defaultdict(list)
    for reg,val in writes:old[reg&31].append((reg,val))
    for reg,values in out:
        for i,val in enumerate(values):new[(reg+i)&31].append((reg+i,val))
    assert old==new
    return out


def compile(data,timeline,fast_pairs=False):
    player=unit2.Player(data,symbolic=True)
    source_times={pos:t for t,pos in timeline}
    stream=bytearray();new_times=[];count=values=0;records=[];ranges=Counter()
    while True:
        pos=player.y
        wait=data[unit2.STREAM+pos]
        _,writes=player.wake()
        grouped=batches([(r,v) for r,v in writes if r&31<28])
        assert len(grouped)<256
        records.append((pos,wait,grouped))
        ranges.update((r,len(v)) for r,v in grouped)
        count+=len(grouped);values+=sum(len(v) for _,v in grouped)
        if player.y==0:break
    descriptors=[key for key,_ in ranges.most_common(255)]
    indices={key:i for i,key in enumerate(descriptors)}
    for pos,wait,grouped in records:
        if pos in source_times:new_times.append((source_times[pos],len(stream)))
        stream.extend((wait,len(grouped)))
        for reg,vals in grouped:
            if fast_pairs and len(vals)==2:
                stream.extend((reg,*vals))
            else:
                if fast_pairs:stream.append(224)
                index=indices.get((reg,len(vals)),255);stream.append(index)
                if index==255:stream.extend((reg,len(vals)))
                stream.extend(vals)
    stream.append(0xe0)
    waveoff=struct.unpack_from('<H',data,8)[0]
    head=bytearray(data[:unit2.STREAM]);head[21]|=3 if fast_pairs else 1
    head[0x100:0x300]=bytes(512)
    for i,(r,n) in enumerate(descriptors):head[0x100+i]=r;head[0x200+i]=n
    if unit2.STREAM+len(stream)>65535:raise ValueError('batch command head exceeds one bank')
    struct.pack_into('<HH',head,6,len(stream),unit2.STREAM+len(stream))
    result=bytes(head+stream+data[waveoff:])
    # Check scaled output separately, across a full loop.
    a,b=unit2.Player(data),unit2.Player(result)
    while True:
        na,wa=a.wake();nb,wb=b.wake();assert na==nb
        for osc in range(32):
            assert [(r,v) for r,v in wa if r&31==osc]==[(r,v) for r,v in wb if r&31==osc]
        if a.y==0:assert b.y==0;break
    return result,new_times,dict(batches=count,register_values=values,values_per_batch=values/count,
                                descriptors=len(descriptors),range_kinds=len(ranges),fast_pairs=fast_pairs)
