"""Cached sinc kernels for long reference previews (host-side audio only)."""
from functools import lru_cache
import math

try:
    import numpy as _numpy
except ImportError:
    _numpy = None

PHASES=4096


@lru_cache(maxsize=2)
def kernels(ratio,taps):
    cut=min(1.,ratio)*.9
    half=math.ceil(taps/min(1.,ratio))
    offsets=range(-half+1,half+1)
    rows=[]
    for phase in range(PHASES):
        row=[]
        for offset in offsets:
            d=phase/PHASES-offset
            arg=d*cut
            sinc=1. if not arg else math.sin(math.pi*arg)/(math.pi*arg)
            u=(d+half)/(2*half)
            win=.42-.5*math.cos(2*math.pi*u)+.08*math.cos(4*math.pi*u)
            row.append(cut*sinc*win if 0<=u<=1 else 0.)
        rows.append(row)
    return half,rows


def resample(values,rate_in,rate_out,taps=24):
    """Same Blackman-windowed filter as musdsp, with 1/4096-sample phases."""
    ratio=rate_out/rate_in
    half,rows=kernels(ratio,taps)
    count=len(values)
    if _numpy is not None and count:
        samples=_numpy.asarray(values,dtype=float)
        weights=_numpy.asarray(rows,dtype=float)
        offsets=_numpy.arange(-half+1,half+1)
        result=[]
        # Bound temporary storage while retaining the portable path's exact
        # sample positions, phase table and zero padding at both boundaries.
        for begin in range(0,round(count*ratio),4096):
            positions=_numpy.rint(_numpy.arange(begin,min(begin+4096,round(count*ratio)))/ratio*PHASES).astype(_numpy.int64)
            centers,phases=_numpy.divmod(positions,PHASES)
            indices=centers[:,None]+offsets
            valid=(indices>=0)&(indices<count)
            window=samples[_numpy.clip(indices,0,count-1)]*valid
            result.extend(_numpy.sum(window*weights[phases],axis=1).tolist())
        return result
    result=[]
    for j in range(round(count*ratio)):
        position=round(j/ratio*PHASES)
        center,phase=divmod(position,PHASES)
        start=center-half+1
        row=rows[phase]
        lo=max(0,-start);hi=min(len(row),count-start)
        result.append(sum(values[start+i]*row[i] for i in range(lo,hi)))
    return result
