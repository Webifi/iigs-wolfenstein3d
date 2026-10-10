"""Bank-safe live assets. Bank 1D loads raw last, after B1 staging is done."""
import memmap
import struct
from wolfdata import ROOT

WALL_RANGES=((memmap.WEAPON_RUNS,memmap.MENU_CACHE_0),(memmap.BOOT_STAGE,memmap.BOOT_STAGE_END),(memmap.DEMOS,memmap.ROWCODE),
             ((memmap.ART_MID+0x46000),memmap.BOOT_STAGE),((memmap.SCALE5+0xd000),memmap.WORD_PRODUCTS),((memmap.ART_BASE+0x4e000),(memmap.ART_BASE+0x50000)))

class Space:
    def __init__(self,ranges):self.ranges=[list(r) for r in ranges];self.index=0
    def allocate(self,size,correction=0):
        while self.index<len(self.ranges):
            start,end=self.ranges[self.index]
            if (start&65535)<correction:start=(start&~65535)+correction
            stop=min(end,(start&~65535)+65536)
            if start+size<=stop:
                self.ranges[self.index][0]=start+size;return start
            if stop<end:self.ranges[self.index][0]=stop
            else:self.index+=1
        raise ValueError('live assets exceed stock 2 MB allocation')


def segments(records,out,prefix):
    records=sorted(records);parts=[]
    for addr,data in records:
        if parts and parts[-1][0]+len(parts[-1][1])==addr:parts[-1][1].extend(data)
        else:parts.append([addr,bytearray(data)])
    names=[]
    for n,(addr,data) in enumerate(parts):
        name=prefix+'-'+str(n)+'.bin';(out/name).write_bytes(data);names.append(dict(file=name,address=addr,bytes=len(data)))
    return names
