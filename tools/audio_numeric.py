"""Scalar DSP reductions with the interpreter's ordered floating-point sums."""
import array
import ctypes
import functools
import math
import threading
from collections import OrderedDict
from audio_plan import library

D=ctypes.c_double
P=ctypes.POINTER(D)
N=ctypes.c_size_t
ORDERED_SUM = sum([1e16,1.,-1e16])==0.


def doubles(values):
    return values if isinstance(values,array.array) and values.typecode=='d' else array.array('d',values)


def pointer(values):
    return (D*len(values)).from_buffer(values)


def rms(values):
    if not ORDERED_SUM or not library():return None
    data=doubles(values);fn=library().song_sumsq
    fn.argtypes=[P,N];fn.restype=D
    return math.sqrt(fn(pointer(data),len(data))/max(1,len(data)))


@functools.lru_cache(maxsize=16)
def window(size,denominator):
    return doubles(.5-.5*math.cos(2*math.pi*i/denominator) for i in range(size))


def power(values,size,denominator):
    from audio_dsp import _numpy
    if _numpy is None or not library():return None
    try:absolute=ctypes.pythonapi._Py_c_abs
    except AttributeError:return None
    src=doubles(values[:size]);win=window(size,denominator);buf=doubles([0.])*size
    fn=library().song_window;fn.argtypes=[P,N,P,N,P];fn.restype=None
    fn(pointer(src),len(src),pointer(win),size,pointer(buf))
    bins=_numpy.fft.fft(_numpy.frombuffer(buf,dtype=_numpy.float64))
    out=doubles([0.])*(size//2+1)
    fn=library().song_power;fn.argtypes=[P,N,P,ctypes.c_void_p];fn.restype=None
    fn(bins.ctypes.data_as(P),len(out),pointer(out),ctypes.cast(absolute,ctypes.c_void_p))
    return out.tolist()


def corrected(values,gain,curve,rate):
    if not library():return None
    data=doubles(values);cv=doubles(curve);out=doubles([0.])*len(data)
    fn=library().song_correct;fn.argtypes=[P,N,D,P,N,D,P];fn.restype=None
    fn(pointer(data),len(data),gain,pointer(cv),len(cv),rate,pointer(out))
    return out.tolist()


def decoded(zone,frames,fc,attack_end,attack_peak,loop_peak,gain_db,curve,source_hold,curve_hold,rate):
    if not library():return None
    params=doubles((frames,fc,attack_end,attack_peak,loop_peak,gain_db,
        math.nan if source_hold is None else source_hold,math.nan if curve_hold is None else curve_hold,
        rate,zone.kind=='oneshot',getattr(zone,'capture_envelope_baked_release',False),getattr(zone,'attack',0.)))
    env=doubles(getattr(zone,'capture_envelope',()));rel=doubles(getattr(zone,'capture_release_curve',()) or ());cv=doubles(curve)
    out=doubles([0.])*frames
    fn=library().song_decode
    fn.argtypes=[P,ctypes.c_char_p,N,ctypes.c_char_p,N,P,N,P,N,P,N,P];fn.restype=None
    fn(pointer(params),bytes(zone.table),len(zone.table),bytes(zone.ltable),len(zone.ltable),pointer(env),len(env),pointer(rel),len(rel),pointer(cv),len(cv),pointer(out))
    return out.tolist()


def spectra(values,intervals,rate,fundamental):
    """Batch independent windows; FFT and scalar feature reductions are unchanged."""
    from audio_dsp import _numpy
    if _numpy is None or not ORDERED_SUM or not library():return None
    try:absolute=ctypes.pythonapi._Py_c_abs
    except AttributeError:return None
    size=2048;data=doubles(values);win=window(size,size-1)
    spans=array.array('q',(v for pair in intervals for v in pair))
    rows=doubles([0.])*(len(intervals)*size)
    I=ctypes.POINTER(ctypes.c_longlong)
    fn=library().song_windows;fn.argtypes=[P,N,I,N,P,N,P];fn.restype=None
    fn(pointer(data),len(data),(ctypes.c_longlong*len(spans)).from_buffer(spans),len(intervals),pointer(win),size,pointer(rows))
    bins=_numpy.fft.fft(_numpy.frombuffer(rows,dtype=_numpy.float64).reshape((-1,size)),axis=-1)
    edges=[40*2**(i/3) for i in range(26)]
    frequencies=list(zip(edges,edges[1:]))+[((h-.45)*fundamental,(h+.45)*fundamental)
        for h in range(1,min(40,int(rate/2/fundamental)))]
    bounds=array.array('q',(v for lo,hi in frequencies for v in
        (max(1,math.ceil(lo*size/rate)),min(size//2,math.ceil(hi*size/rate)))))
    out=doubles([0.])*(len(intervals)*len(frequencies))
    fn=library().song_features;fn.argtypes=[P,N,N,I,N,N,P,ctypes.c_void_p];fn.restype=None
    fn(bins.ctypes.data_as(P),len(intervals),size,(ctypes.c_longlong*len(bounds)).from_buffer(bounds),25,len(frequencies),pointer(out),ctypes.cast(absolute,ctypes.c_void_p))
    n=len(frequencies)
    return [(out[i*n:i*n+25].tolist(),out[i*n+25:(i+1)*n].tolist()) for i in range(len(intervals))]


def window_powers(values,intervals):
    if not ORDERED_SUM or not library():return None
    data=doubles(values);spans=array.array('q',(v for pair in intervals for v in pair));out=doubles([0.])*len(intervals)
    I=ctypes.POINTER(ctypes.c_longlong)
    fn=library().song_window_powers;fn.argtypes=[P,N,I,N,P];fn.restype=None
    fn(pointer(data),len(data),(ctypes.c_longlong*len(spans)).from_buffer(spans),len(intervals),pointer(out))
    return out.tolist()


def band_energy(values,rate,bands):
    from audio_dsp import _numpy
    if _numpy is None or not ORDERED_SUM or not library():return None
    try:absolute=ctypes.pythonapi._Py_c_abs
    except AttributeError:return None
    size=1024;data=doubles(values);win=window(size,size-1)
    starts=sorted(set(list(range(0,max(1,len(values)-size+1),max(size//2,len(values)//64)))+
                      [max(0,len(values)-size)]))
    spans=array.array('q',(v for a in starts for v in (a,a+size)))
    rows=doubles([0.])*(len(starts)*size);I=ctypes.POINTER(ctypes.c_longlong)
    fn=library().song_windows;fn.argtypes=[P,N,I,N,P,N,P];fn.restype=None
    fn(pointer(data),len(data),(ctypes.c_longlong*len(spans)).from_buffer(spans),len(starts),pointer(win),size,pointer(rows))
    bins=_numpy.fft.fft(_numpy.frombuffer(rows,dtype=_numpy.float64).reshape((-1,size)),axis=-1)
    bounds=array.array('q',(v for lo,hi in bands for v in
        (max(1,math.ceil(lo*size/rate)),min(size//2,math.ceil(hi*size/rate)))))
    out=doubles([0.])*len(bands)
    fn=library().song_band_energy;fn.argtypes=[P,N,N,I,N,P,ctypes.c_void_p];fn.restype=None
    fn(bins.ctypes.data_as(P),len(starts),size,(ctypes.c_longlong*len(bounds)).from_buffer(bounds),len(bands),pointer(out),ctypes.cast(absolute,ctypes.c_void_p))
    return out.tolist()


_weights=OrderedDict()
_weight_bytes=0
_weight_lock=threading.Lock()


def resample_weights(ratio,half,count):
    """Reuse coefficient prefixes across source lengths and edge policies."""
    global _weight_bytes
    key=ratio,half
    with _weight_lock:
        previous=_weights.get(key)
        if previous is not None and len(previous[0])>=count*2*half:
            _weights.move_to_end(key)
            return previous
        width=2*half
        start=len(previous[0])//width if previous is not None else 0
        weights=array.array('d',previous[0]) if previous is not None else doubles(())
        indices=array.array('i',previous[1]) if previous is not None else array.array('i')
        weights.extend(doubles([0.])*((count-start)*width))
        indices.extend(array.array('i',[0])*((count-start)*width))
        fn=library().song_resample_weights
        fn.argtypes=[D,D,ctypes.c_int,N,N,D,P,ctypes.POINTER(ctypes.c_int)];fn.restype=None
        fn(ratio,min(1.,ratio)*.9,half,start,count,math.pi,pointer(weights),(ctypes.c_int*len(indices)).from_buffer(indices))
        result=weights,indices
        size=sum(len(a)*a.itemsize for a in result)
        if previous is not None:
            del _weights[key]
            _weight_bytes-=sum(len(a)*a.itemsize for a in previous)
        while _weights and _weight_bytes+size>128*1024*1024:
            _,old=_weights.popitem(last=False)
            _weight_bytes-=sum(len(a)*a.itemsize for a in old)
        _weights[key]=result;_weight_bytes+=size
        return result


def resample(values,rate_in,rate_out,taps,periodic,buffer=False):
    ratio=rate_out/rate_in;count=round(len(values)*ratio);half=math.ceil(taps/min(1.,ratio))
    if not library() or not values:return None
    data=doubles(values);out=doubles([0.])*count
    if count*2*half>1048576:
        import native_host
        native_host.library().audio_resample(pointer(data),len(data),ratio,min(1.,ratio)*.9,
            half,count,periodic,math.pi,pointer(out))
        return out if buffer else out.tolist()
    weights,indices=resample_weights(ratio,half,count)
    fn=library().song_resample_apply
    fn.argtypes=[P,N,ctypes.c_int,P,ctypes.POINTER(ctypes.c_int),N,N,P];fn.restype=None
    fn(pointer(data),len(data),periodic,pointer(weights),(ctypes.c_int*len(indices)).from_buffer(indices),count,2*half,pointer(out))
    return out if buffer else out.tolist()


def prefix_energy(values):
    if not ORDERED_SUM or not library():return None
    data=doubles(values);out=doubles([0.])*(len(data)+1)
    fn=library().song_prefix;fn.argtypes=[P,N,P];fn.restype=None
    fn(pointer(data),len(data),pointer(out))
    return out


def quantize(values,peak):
    if not library():return None
    data=doubles(values);out=(ctypes.c_ubyte*len(data))()
    fn=library().song_quantize;fn.argtypes=[P,N,D,ctypes.POINTER(ctypes.c_ubyte)];fn.restype=None
    fn(pointer(data),len(data),peak,out)
    return bytes(out)


def quantized_loop(values,peak,frequency,count):
    table=quantize(values,peak)
    if table is None:return None
    out=doubles([0.])*count
    fn=library().song_loop_playback;fn.argtypes=[ctypes.c_char_p,N,N,N,P];fn.restype=None
    fn(table,len(table),frequency,count,pointer(out))
    return out.tolist()


def quantized_values(values,peak):
    table=quantize(values,peak)
    if table is None:return None
    out=doubles([0.])*len(table)
    fn=library().song_quantized_values;fn.argtypes=[ctypes.c_char_p,N,D,P];fn.restype=None
    fn(table,len(table),peak,pointer(out))
    return out.tolist()


def sample_playback(table,peak,actual,rate,count):
    if not library():return None
    out=doubles([0.])*count
    fn=library().song_sample_playback;fn.argtypes=[ctypes.c_char_p,N,D,D,D,N,P];fn.restype=None
    fn(table,len(table),peak,actual,rate,count,pointer(out))
    return out.tolist()
