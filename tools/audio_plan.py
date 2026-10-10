"""Exact host arithmetic for note envelopes; unsupported models use Python."""
import ctypes
import functools
import hashlib
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import math

ORDERED_SUM = sum([1e16,1.,-1e16])==0.


@functools.lru_cache(maxsize=1)
def library():
    if os.environ.get('WOLF_HOST_NATIVE','1')=='0':return None
    source=Path(__file__).with_suffix('.c')
    compiler=shlex.split(os.environ.get('CC',shutil.which('cc') or ''))
    if not compiler:return None
    flags=['-O3','-std=c99','-fPIC','-ffp-contract=off','-fno-fast-math','-fno-builtin-pow','-shared']
    key=hashlib.sha256(source.read_bytes()+repr((compiler,flags,sys.platform,platform.machine())).encode()).hexdigest()
    from shared_cache import folder as shared_folder,locked
    shared=shared_folder();folder=shared/'v1/host' if shared else source.parent.parent/'build/host'
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(key+('.dylib' if sys.platform=='darwin' else '.so'))
    with locked(folder/(key+'.lock')):
        if not path.is_file():
            temporary=folder/(key+'.'+str(os.getpid())+'.tmp')
            try:
                subprocess.run(compiler+flags+[str(source),'-o',str(temporary),'-lm'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                os.replace(temporary,path)
            except (OSError,subprocess.CalledProcessError):
                temporary.unlink(missing_ok=True)
                return None
    path.read_bytes()
    return ctypes.CDLL(str(path))


def note_levels(song,n,end,base,both,sp,off,baked,done,tail,tic):
    import mussc
    z=n.z
    if (not ORDERED_SUM or not library() or getattr(z,'frame_native',False) or
            (mussc.MOTION and any(L.mod_lfo_volume for L in n.layers)) or
            getattr(n,'capture_response_curve',None) or
            mussc.wolf_calibration.get('measured_envelopes',{}).get(f'ch{n.ch+1:02}') or
            song.name=='D_E1M5'):
        return None
    def layers(values,main,weights=None):
        return [(L.atten-main.atten,L.delay,L.attack,L.hold,L.sustain,L.decay,
                 weights[i] if weights else 1.) for i,L in enumerate(values)]
    model=layers(n.layers or [n.r],n.r)
    mixed=bool(getattr(z,'mix',None) and getattr(z,'mix_pow',None))
    mixing=layers([L for L,w in z.mix],z.mix_main,z.mix_pow) if mixed else model
    vols=[]
    for t,cv in n.vols:
        dv=mussc.channel_attenuation(song.name,n.preset,cv) if cv>0 else math.nan
        if cv>0 and getattr(z,'capture_context',False):
            dv-=mussc.channel_attenuation(song.name,n.preset,n.capture_volume)
        vols.append((t,dv))
    envelope=getattr(z,'capture_envelope',())
    release=getattr(z,'capture_release_curve',()) or ()
    switch=song.switch_at.get(id(n),end+1)
    params=(n.on,end,n.stop,-1 if done is None else done,off,both,sp,base,
            z.kind=='attack',getattr(z,'nat',0.),getattr(z,'nat_len',0.),getattr(z,'attack',0.),
            n.r.release,baked,tail,switch,getattr(z,'loop_gain',z.gain)-z.gain,
            bool(envelope),getattr(z,'capture_envelope_baked_release',False),getattr(z,'capture_modeled',False),
            (n.preset==(0,48) and not getattr(z,'ensemble_attack_baked',False)) or getattr(z,'noise_attack',False),
            z.mix_M if mixed else 1.,tic,getattr(n,"capture_release",False))
    D=ctypes.c_double;P=ctypes.POINTER(D);N=ctypes.c_size_t
    lib=library();fn=lib.song_levels
    fn.argtypes=[P,P,N,P,N,P,N,P,N,P,N,P];fn.restype=None
    array=lambda xs:(D*len(xs))(*xs)
    out=(D*(2*(end-n.on+1)))()
    fn(array(params),array([x for row in mixing for x in row]),len(mixing),
       array([x for row in model for x in row]),len(model),
       array([x for row in vols for x in row]),len(vols),array(envelope),len(envelope),array(release),len(release),out)
    return [None if math.isnan(out[i]) else 'done' if math.isinf(out[i]) else (out[i],out[i+1])
            for i in range(0,len(out),2)]


def accelerate(source):
    """Keep the generated reference loop for models the kernel does not cover."""
    first=source.index('            for t in range(n.on, end + 1):')
    last=source.index('            tracks[v].append',first)
    loop=source[first:last]
    return (source[:first]+'            native = wolf_note_levels(self,n,end,base,both,sp,off,baked,done,TAIL_DB,TIC)\n'
            +'            if native is None:\n'+''.join('    '+line+'\n' for line in loop.splitlines())
            +'            else:qs = native\n'+source[last:])


def filtered_harmonics(f0, count, notes, weights, layer, time):
    import cmath
    import mussc
    if not ORDERED_SUM or not library():return None
    try:
        product=ctypes.pythonapi._Py_c_prod
        quotient=ctypes.pythonapi._Py_c_quot
        absolute=ctypes.pythonapi._Py_c_abs
    except AttributeError:return None
    D=ctypes.c_double;P=ctypes.POINTER(D);N=ctypes.c_size_t
    fn=library().song_filter
    fn.argtypes=[P,N,D,D,D,P,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];fn.restype=None
    columns=[];computed={}
    for n in notes:
        hz=mussc.fc_hz_of(layer,n.vel,time)
        if hz is None:
            columns.append([1.]*count);continue
        key=(n.sp,hz)
        if key not in computed:
            q_cb=layer.g.get('initialFilterQ',0);rate=44100.
            q_db=max(0.,min(96.,q_cb/10.))-3.01;q=10.**(q_db/20.)
            gain=1./math.sqrt(q);cut=min(.45*rate,max(5.,hz))
            w=2.*math.pi*cut/rate;alpha=math.sin(w)/(2.*q);a0=1.+alpha
            b1=(1.-math.cos(w))/a0*gain;a1=-2.*math.cos(w)/a0;a2=(1.-alpha)/a0
            zs=[cmath.exp(-2j*math.pi*(h*f0*n.sp)/rate) for h in range(1,count+1)]
            data=(D*(2*count))(*(v for z in zs for v in (z.real,z.imag)));out=(D*count)()
            fn(data,count,b1,a1,a2,out,*[ctypes.cast(f,ctypes.c_void_p) for f in (product,quotient,absolute)])
            computed[key]=[out[h-1] if h*f0*n.sp<.5*rate else 0. for h in range(1,count+1)]
        columns.append(computed[key])
    total=float(sum(weights))
    return [sum((w*column[h] for w,column in zip(weights,columns)),0.)/total for h in range(count)]


def synthesize(amplitudes, phases, count, cycles, length):
    if not library():return None
    D=ctypes.c_double;P=ctypes.POINTER(D);N=ctypes.c_size_t
    fn=library().song_synthesize
    fn.argtypes=[P,P,N,D,N,P];fn.restype=None
    out=(D*length)()
    fn((D*len(amplitudes))(*amplitudes),(D*len(phases))(*phases),count,cycles,length,out)
    return list(out)
