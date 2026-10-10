"""Cold song storage: load-time LZ expansion, unchanged ready-register hot stream."""
from collections import defaultdict, deque
from pathlib import Path
import argparse
import hashlib
import heapq
from collections import Counter
import json
import struct
import sys

def compress(data):
    try:
        import native_host
    except ImportError:
        native_host = None
    if native_host is not None and native_host.library():
        return native_host.audio_pack(data)
    return compress_python(data)


def compress_python(data):
    index=defaultdict(deque)
    result=bytearray();literal=bytearray();pos=0
    def flush():
        if literal:
            result.append(len(literal)-1);result.extend(literal);literal.clear()
    while pos<len(data):
        key=data[pos:pos+3];best=0;distance=0
        if len(key)==3:
            for old in reversed(index[key]):
                if pos-old>65535:break
                size=3;limit=min(130,len(data)-pos)
                while size<limit and data[old+size]==data[pos+size]:size+=1
                if size>best:best=size;distance=pos-old
                if size==limit:break
        used=best if best>=4 else 1
        if used>1:
            flush();result.extend(struct.pack('<BH',128+used-3,distance))
        else:
            literal.append(data[pos])
            if len(literal)==128:flush()
        for i in range(pos,pos+used):
            q=index[data[i:i+3]];q.append(i)
            while len(q)>64:q.popleft()
        pos+=used
    flush()
    return bytes(result)


def expand(packed, start, limit):
    memory=bytearray(65536)
    memory[start:start+len(packed)]=packed
    source=start;dest=0;gap=65536
    while dest<limit:
        token=memory[source];source+=1
        if token<128:
            length=token+1
            for _ in range(length):
                assert dest<source,('literal overwrites unread data',dest,source)
                memory[dest]=memory[source];dest+=1;source+=1
                gap=min(gap,source-dest)
        else:
            length=(token&127)+3
            distance=memory[source]|memory[source+1]<<8;source+=2
            assert 0<distance<=dest
            for _ in range(length):
                assert dest<source,('match overwrites unread data',dest,source)
                memory[dest]=memory[dest-distance];dest+=1
                gap=min(gap,source-dest)
        assert dest<=limit
    assert source==start+len(packed)
    return bytes(memory[:dest]),gap
