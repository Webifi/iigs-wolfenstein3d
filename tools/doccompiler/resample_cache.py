"""Bounded, bit-exact reuse for repeated build-time waveform fitting."""
from array import array
from functools import lru_cache
from collections import OrderedDict
import hashlib
import math
import threading


@lru_cache(maxsize=128)
def coefficients(n, rate_in, rate_out, taps, periodic):
    ratio=rate_out/rate_in;cut=min(1.,ratio)*.9
    count=round(n*ratio);half=math.ceil(taps/min(1.,ratio))
    offsets=array('I',[0]);indices=array('I');weights=array('d')
    for j in range(count):
        t=j/ratio;i0=math.floor(t)
        for i in range(i0-half+1,i0+half+1):
            d=t-i
            if not periodic and (i<0 or i>=n):continue
            arg=d*cut
            s=1. if arg==0 else math.sin(math.pi*arg)/(math.pi*arg)
            u=(d+half)/(2*half)
            if u<0 or u>1:continue
            win=.42-.5*math.cos(2*math.pi*u)+.08*math.cos(4*math.pi*u)
            indices.append(i%n if periodic else i);weights.append(cut*s*win)
        offsets.append(len(indices))
    return offsets,indices,weights


def reduced(values, rate_in, rate_out, taps, periodic):
    from musdsp import _uncached_resample
    try:
        import native_host
    except ImportError:
        native_host = None
    if native_host is not None and native_host.library():
        from audio_numeric import resample as weighted
        result=weighted(values,rate_in,rate_out,taps,periodic,buffer=True)
        if result is not None:return result
        return native_host.resample(values, rate_in, rate_out, taps, periodic)
    ratio=rate_out/rate_in;count=round(len(values)*ratio)
    if count*2*math.ceil(taps/min(1.,ratio))>250000 or not values:
        return _uncached_resample(values,rate_in,rate_out,taps,periodic)
    offsets,indices,weights=coefficients(len(values),rate_in,rate_out,taps,periodic)
    result=[]
    for j in range(count):
        acc=0.
        # Keep the original accumulation order, including at wrapped edges.
        for i in range(offsets[j],offsets[j+1]):acc+=values[indices[i]]*weights[i]
        result.append(acc)
    return result


_results=OrderedDict()
_result_bytes=0
_lock=threading.Lock()


def resample(values, rate_in, rate_out, taps, periodic):
    """Reuse identical source work within a conversion, bounded to 128 MiB."""
    global _result_bytes
    data=array('d',values)
    key=(hashlib.sha256(data).digest(),len(data),rate_in,rate_out,taps,periodic)
    with _lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key].tolist()
    result=reduced(data,rate_in,rate_out,taps,periodic)
    if not isinstance(result,array):result=array('d',result)
    size=len(result)*result.itemsize
    if size<=128*1024*1024:
        with _lock:
            previous=_results.pop(key,None)
            if previous is not None:_result_bytes-=len(previous)*previous.itemsize
            while _results and _result_bytes+size>128*1024*1024:
                _,old=_results.popitem(last=False)
                _result_bytes-=len(old)*old.itemsize
            _results[key]=result;_result_bytes+=size
    # Callers may normalize the returned waveform in place.
    return result.tolist()
