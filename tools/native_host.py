"""Optional C arithmetic for source builds, with the Python implementations as fallback.

The library is built inside this build's empty output tree. Its filename binds
the source, compiler command and host platform. No converted assets are stored.
"""
import ctypes
import functools
import hashlib
import math
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

D = ctypes.c_double
P = ctypes.POINTER(D)
N = ctypes.c_size_t
SOURCE = Path(__file__).resolve().with_name('host_kernels.c')

@functools.lru_cache(maxsize=1)
def library():
    if os.environ.get('WOLF_HOST_NATIVE', '1') == '0':
        return None
    source = SOURCE
    compiler = shlex.split(os.environ.get('CC', shutil.which('cc') or ''))
    if not compiler:
        return None
    flags = ['-O3', '-std=c99', '-fPIC', '-ffp-contract=off', '-fno-fast-math', '-fno-builtin-pow', '-shared']
    key = hashlib.sha256(source.read_bytes() + repr((compiler, flags, sys.platform, platform.machine())).encode()).hexdigest()
    from shared_cache import folder as shared_folder, locked
    shared = shared_folder()
    folder = shared/'v1/host' if shared else source.parent.parent/'build/host'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(key + ('.dylib' if sys.platform == 'darwin' else '.so'))
    with locked(folder/(key+'.lock')):
        if not path.is_file():
            temporary = folder/(key + '.' + str(os.getpid()) + '.tmp')
            try:
                subprocess.run(compiler + flags + [str(source), '-o', str(temporary), '-lm'],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                os.replace(temporary, path)
            except (OSError, subprocess.CalledProcessError):
                temporary.unlink(missing_ok=True)
                return None
    path.read_bytes()  # The verifying step tracer records the loaded library's bytes.
    lib = ctypes.CDLL(str(path))
    lib.color_best.argtypes = [P, N, P, N, N, D, D, D, P]
    lib.color_best.restype = None
    lib.color_costs.argtypes = [P, N, P, N, D, D, D, P]
    lib.color_costs.restype = None
    lib.color_min.argtypes = [P, N, ctypes.POINTER(P), N, N, P]
    lib.color_min.restype = None
    lib.color_bounds.argtypes = [P, N, P, N, D, D, P]
    lib.color_bounds.restype = None
    lib.color_min_bounded.argtypes = [P, N, ctypes.POINTER(P), N, N, D, D, D, P, P]
    lib.color_min_bounded.restype = None
    lib.color_pick.argtypes = [P, P, N, D, D]
    lib.color_pick.restype = N
    lib.sight_rows.argtypes = [ctypes.POINTER(ctypes.c_int), N, ctypes.POINTER(ctypes.c_int), N,
                              ctypes.POINTER(ctypes.c_ubyte)]
    lib.sight_rows.restype = ctypes.c_int
    lib.hlz_find.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.hlz_find.restype = ctypes.c_void_p
    lib.hlz_free.argtypes = [ctypes.c_void_p]
    lib.hlz_free.restype = None
    lib.hlz_parse.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, P, P,
                             ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    lib.hlz_parse.restype = ctypes.c_int
    lib.audio_resample.argtypes = [P, N, D, D, ctypes.c_int, N, ctypes.c_int, D, P]
    lib.audio_resample.restype = None
    lib.dos_huffman.argtypes = [ctypes.c_char_p, N, ctypes.POINTER(ctypes.c_uint16),
                               ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte)]
    lib.dos_huffman.restype = ctypes.c_int
    lib.b1_parse.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                            ctypes.POINTER(ctypes.c_int)]
    lib.b1_parse.restype = ctypes.c_int
    lib.nearest3.argtypes = [P, N, P, N, ctypes.c_int, D, P, ctypes.POINTER(ctypes.c_int), P]
    lib.nearest3.restype = None
    lib.color_score.argtypes = [P, N, P, P]
    lib.color_score.restype = D
    lib.greedy_parse.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    lib.greedy_parse.restype = ctypes.c_int
    lib.harmonic_sums.argtypes = [P, N, P, N, P, ctypes.c_void_p]
    lib.harmonic_sums.restype = None
    lib.audio_pack.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte)]
    lib.audio_pack.restype = ctypes.c_int
    lib.audio_correlation.argtypes = [P, N, P, N, P]
    lib.audio_correlation.restype = None
    lib.audio_fft.argtypes = [P, N, P, ctypes.c_void_p, ctypes.c_int]
    lib.audio_fft.restype = None
    lib.effect_filter.argtypes = [P, N, P, N, D, D, ctypes.c_int, P]
    lib.effect_filter.restype = None
    U8 = ctypes.POINTER(ctypes.c_ubyte)
    I = ctypes.POINTER(ctypes.c_int)
    C = ctypes.c_int
    lib.shr_perfect.argtypes = [P, P, U8, U8, C, C, P, P, U8, P, D, D, D, I]
    lib.shr_perfect.restype = None
    lib.shr_dither.argtypes = [P, P, P, U8, U8, P, C, C, P, P, P, U8, D, D, C, D, D, I, I, P, P]
    lib.shr_dither.restype = None
    return lib

def targets(rows, solid):
    values = [v for (lab, weight, lam), flag in zip(rows, solid)
              for v in (*lab, math.hypot(lab[1],lab[2]), weight, lam, flag)]
    return (D * len(values))(*values)

def mixes(rows):
    values = [v for lab, noise in rows for v in (*lab, math.hypot(lab[1],lab[2]), noise)]
    return (D * len(values))(*values)

def best(prepared, rows, solids, metric):
    count = len(prepared)//7
    result = (D * count)()
    values = mixes(rows + solids)
    library().color_best(prepared, count, values, len(rows), len(solids),
                         metric.ekc, metric.ekh, metric.d0, result)
    return list(result)

def best_reusing(prepared, rows, solids, metric, cache, base=None):
    count = len(prepared)//7
    all_rows = rows + solids
    bounded = metric.d0 >= 0 and all(prepared[7*i+5] >= 0 for i in range(count))
    width = count+5 if bounded else count
    missing = list(dict.fromkeys(row for row in all_rows if row not in cache))
    if missing:
        output = (D * (width*len(missing)))()
        if bounded:
            library().color_bounds(prepared, count, mixes(missing), len(missing),
                                   metric.ekc, metric.d0, output)
        else:
            library().color_costs(prepared, count, mixes(missing), len(missing),
                                  metric.ekc, metric.ekh, metric.d0, output)
        for i, row in enumerate(missing):
            cache[row] = ctypes.cast((D * width).from_buffer(output, i*width*ctypes.sizeof(D)), P)
    vectors = (P * len(all_rows))(*(cache[row] for row in all_rows))
    result = (D * count)()
    if bounded:
        library().color_min_bounded(prepared,count,vectors,len(rows),len(solids),
                                   metric.ekc,metric.ekh,metric.d0,base,result)
    else:
        library().color_min(prepared,count,vectors,len(rows),len(solids),result)
    return result

def score_reusing(prepared, rows, solids, metric, cache, base):
    costs=best_reusing(prepared,rows,solids,metric,cache,base)
    return library().color_score(prepared,len(prepared)//7,costs,base)

def pick(prepared, count, lab, lam, metric):
    target = (D * 7)(*lab, math.hypot(lab[1],lab[2]), 0, lam, 0)
    return library().color_pick(target, prepared, count, metric.ekc, metric.ekh)

def blocked_rows(cells, bars):
    points = (ctypes.c_int * (2 * len(cells)))(*(v for point in cells for v in point))
    walls = (ctypes.c_int * (4 * len(bars)))(*(v for bar in bars for v in bar))
    stride = (len(cells) + 8)//8
    out = (ctypes.c_ubyte * ((len(cells)+1) * stride))()
    if library().sight_rows(points, len(cells), walls, len(bars), out):
        raise MemoryError('sight proof workspace')
    raw = bytes(out)
    return [raw[i:i+stride] for i in range(0,len(raw),stride)]

class HLZMatches:
    def __init__(self, data, chain, nice):
        self.lib = library()
        self.data = data
        self.pointer = self.lib.hlz_find(data, len(data), chain, nice)
        if not self.pointer:
            raise MemoryError('HLZ match workspace')

    def close(self):
        if self.pointer:
            self.lib.hlz_free(self.pointer)
            self.pointer = None

    def parse(self, lit, off, nice):
        output = (ctypes.c_int * (3 * len(self.data)))()
        count = self.lib.hlz_parse(self.data, len(self.data), self.pointer,
                                  (D * len(lit))(*lit), (D * len(off))(*off), nice, output)
        if count < 0:
            raise MemoryError('HLZ parse workspace')
        return [(output[3*i], output[3*i+1], bool(output[3*i+2]))
                if output[3*i] else output[3*i+1] for i in range(count-1,-1,-1)]

def resample(values, rate_in, rate_out, taps, periodic):
    ratio = rate_out/rate_in
    cut = min(1.0, ratio)*0.9
    count = round(len(values)*ratio)
    half = math.ceil(taps/min(1.0, ratio))
    output = (D * count)()
    library().audio_resample((D * len(values))(*values), len(values), ratio, cut,
                             half, count, periodic, math.pi, output)
    return list(output)

def huffman(stream, table, size):
    output = (ctypes.c_ubyte * (size if size is not None else 1048576))()
    length = library().dos_huffman(stream, len(stream), (ctypes.c_uint16 * 512)(*table),
                                   -1 if size is None else size, output)
    if length < 0:
        raise ValueError({-1:'truncated Huffman stream', -2:'Huffman node outside dictionary',
                          -3:'Huffman output exceeds asset limits'}[length])
    return ctypes.string_at(output, length)

@functools.lru_cache(maxsize=1)
def b1_choices():
    values=[]
    for length in range(257):
        row=list({length,2,3,4,8,16,32,64})
        values.extend([len(row)] + row + [0]*(8-len(row)))
    return (ctypes.c_int * len(values))(*values)

def b1_parse(data):
    output=(ctypes.c_int * (4*len(data)))()
    count=library().b1_parse(data,len(data),b1_choices(),output)
    if count<0:
        raise MemoryError('B1 parse workspace')
    return [('M',output[4*i+1],output[4*i+2],bool(output[4*i+3])) if output[4*i]
            else ('L',output[4*i+1],output[4*i+2]) for i in range(count-1,-1,-1)]

def nearest3(points, centers, rgb, biases=None, chroma=1.0):
    prepared=(D * (3*len(points)))(*(v for p in points for v in p))
    choices=(D * (3*len(centers)))(*(v for p in centers for v in p))
    result=(ctypes.c_int * len(points))()
    costs=(D * len(points))()
    bias = (D * len(biases))(*biases) if biases is not None else None
    library().nearest3(prepared,len(points),choices,len(centers),rgb,chroma,bias,result,costs)
    return list(result),list(costs)

def greedy_parse(data, chain, minimum, leave_last):
    output=(ctypes.c_int * (4*(len(data)+1)))()
    count=library().greedy_parse(data,len(data),chain,minimum,leave_last,output)
    if count<0:
        raise MemoryError('LZ match workspace')
    return [tuple(output[4*i:4*i+4]) for i in range(count)]

def harmonic_sums(samples, rotations):
    try:
        product = ctypes.pythonapi._Py_c_prod
    except AttributeError:
        return None
    data=(D * len(samples))(*samples)
    rots=(D * (2*len(rotations)))(*(v for z in rotations for v in (z.real,z.imag)))
    output=(D * (2*len(rotations)))()
    library().harmonic_sums(data,len(samples),rots,len(rotations),output,
                           ctypes.cast(product,ctypes.c_void_p))
    return [complex(output[2*i],output[2*i+1]) for i in range(len(rotations))]

def audio_pack(data):
    output=(ctypes.c_ubyte * (len(data)+(len(data)+127)//128))()
    length=library().audio_pack(data,len(data),output)
    if length<0:
        raise MemoryError('song LZ workspace')
    return bytes(output[:length])

def audio_correlation(segment, loop):
    a=(D * len(segment))(*segment)
    b=(D * len(loop))(*loop)
    output=(D * len(loop))()
    library().audio_correlation(a,len(segment),b,len(loop),output)
    return output

def fft(values, twiddles, twiddle_first=False):
    if not values or len(values)&(len(values)-1):
        return None
    try:
        product = ctypes.pythonapi._Py_c_prod
    except AttributeError:
        return None
    values = list(map(complex, values))
    data=(D * (2*len(values)))(*(v for z in values for v in (z.real,z.imag)))
    tw=(D * (2*len(twiddles)))(*(v for z in twiddles for v in (z.real,z.imag)))
    library().audio_fft(data,len(values),tw,ctypes.cast(product,ctypes.c_void_p),twiddle_first)
    return [complex(data[2*i],data[2*i+1]) for i in range(len(values))]

def effect_filter(samples, kernel, count, step, half, grid):
    x=(D * len(samples))(*samples)
    k=(D * len(kernel))(*kernel)
    y=(D * count)()
    library().effect_filter(x,len(samples),k,count,step,half,grid,y)
    return list(y)

if __name__ == '__main__':
    print('Host arithmetic: ' + ('native' if library() else 'Python'))
