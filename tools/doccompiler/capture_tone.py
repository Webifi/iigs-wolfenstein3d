"""Wet melodic capture: own-output attack and whole-period DOC loop.

GPL-licensed build-time capture conversion; no runtime dependencies.
Drums, Synth Drum and Gunshot never enter this path.
"""
import array,copy,json,math,wave,sys
from pathlib import Path
from collections import Counter


def energy_window(rate, period, modeled=False):
    if modeled:
        return round(max(round(.01*rate),2*period))
    return round(max(2,math.ceil(.01*rate/period))*period)


from functools import lru_cache
import io


@lru_cache(maxsize=64)
def capture_pcm(data, lead_seconds, quiet_seconds):
    with wave.open(io.BytesIO(data)) as f:
        assert f.getnchannels()==2 and f.getsampwidth()==2
        sr=f.getframerate();a=array.array('h',f.readframes(f.getnframes()))
    if sys.byteorder!='little':a.byteswap()
    lead=round(lead_seconds*sr);quiet=min(lead,round(quiet_seconds*sr))
    dc=sum(a[(lead-quiet)*2:lead*2])/(quiet*2)
    return sr,[(l+r)/2-dc for l,r in zip(a[::2],a[1::2])][lead:],dc


@lru_cache(maxsize=64)
def capture_signal(data, lead, quiet, seconds, bandwidth):
    """Read-only source samples and their derived measurements for one fit."""
    import musdsp
    sr,mono,dc=capture_pcm(data,lead,quiet)
    if seconds:mono=mono[:round(seconds*sr)]
    if bandwidth and bandwidth*2.2<sr:
        band=bandwidth*2.2
        mono=musdsp.resample(musdsp.resample(mono,sr,band),band,sr)
    return sr,mono,dc,{}


def source_period(mono,sr,fundamental,at,end,features):
    from audio_timbre import measured_period
    key=('period',fundamental,at,end)
    if key not in features:features[key]=measured_period(mono,sr,fundamental,at,end)
    return features[key]


def install(owner,z,spec):
    import mussc,musdsp
    path=Path(spec['wav']);meta=json.loads(path.with_suffix('.json').read_text())
    sr,mono,dc,features=capture_signal(path.read_bytes(),meta['lead'],
        meta.get('quiet_lead_seconds',meta['lead']),spec.get('source_seconds'),spec.get('bandwidth_hz'))
    for n in z.notes:
        n.sp=2**((n.key-spec['key'])/12)
        n.freqs=[(t,n.sp*2**((b-spec.get('bend_semitones',0))/12)) for t,b in n.bends]
        n.r=copy.copy(n.r)
        if spec.get('release_baked'): n.r.release=2.
        if spec.get('release_seconds'):
            n.r.release=spec['release_seconds'];n.capture_release=True
    smin=min(sp for n in z.notes for _,sp in n.freqs)
    smax=max(sp for n in z.notes for _,sp in n.freqs)
    floor=mussc.DOC_RATE*(513/512)/smin
    # Measure the source period around the sustained body, close to the
    # capture's known pitch. Phase correlation avoids a fractional-period seam.
    fundamental=440*2**((spec['key']+spec.get('bend_semitones',0)-69)/12)
    nominal=sr/fundamental
    at=round(spec.get('loop_start',.16)*sr)
    modeled=not spec.get('measured_amplitude',False)
    legacy_loop=modeled and getattr(owner,'loop_layout','full')=='repeated-endpoint'
    if legacy_loop:
        span=round(nominal*12)
        segment=mono[at:at+span+round(nominal*1.04)]
        def correlate(p):
            x,y=segment[:span],segment[p:p+span]
            return sum(a*b for a,b in zip(x,y))/math.sqrt(max(1e-20,sum(a*a for a in x)*sum(b*b for b in y)))
        period=max(range(max(8,round(nominal*.97)),round(nominal*1.03)+1),key=correlate)
        correlation=correlate(period)
    else:
        period,correlation=source_period(mono,sr,fundamental,at,meta.get('hold_seconds'),features)
    # Keep several actual captured cycles, not a sine or a synthesized carrier.
    # Smallest legal table with >= 1 whole period and the required rate.
    choices=[]
    for size in (256,512,1024,2048):
        L=size-1 if legacy_loop else size
        for copies in range(1,33):
            R=L*sr/round(period*copies)
            if floor <= R <= 2*floor and (not spec.get('requested_rate') or abs(R-spec['requested_rate'])/spec['requested_rate']<.03):
                choices.append((size+owner.q.attack*smin*R,size,copies,R))
    if not choices:raise ValueError(('no captured whole-period loop',spec['key'],floor,period))
    _,size,copies,R=min(choices)
    match = None
    if spec.get('measured_amplitude'):
        from audio_timbre import match_body
        holds = tuple((len(mono)/sr if spec.get('release_baked') else (n.off-n.on)/140*n.sp)
                      for n in z.notes if n.half == 0)
        key = (meta['wav_sha256'],spec['key'],spec.get('bend_semitones',0),smin,smax,
               holds,owner.q.attack,at,period,size,copies,R,spec.get('requested_rate'),meta.get('hold_seconds'))
        cache = getattr(getattr(owner,'capture_factory',None),'timbre_cache',{})
        if key not in cache:
            cache[key] = match_body(mono,sr,spec['key'],spec.get('bend_semitones',0),
                                   smin,smax,holds,owner.q.attack,(at,period,size,copies,R),
                                   spec.get('requested_rate'),meta.get('hold_seconds'),
                                   getattr(getattr(owner,'capture_factory',None),'scoring_cache',None))
        (at,period,size,copies,R), match = cache[key]
        if spec.get('allocation_bytes') is not None and match:
            option=next((a for a in match['alternatives'] if a['bytes']==spec['allocation_bytes']),None)
            if option is None:raise ValueError('requested captured loop allocation is unavailable')
            at,period,size,copies,R=option['choice']
            match=dict(match,selected_allocation=option['bytes'],selected=option['metrics'])
        _,correlation=source_period(mono,sr,fundamental,at,meta.get('hold_seconds'),features)
    L=size-1 if legacy_loop else size
    body=mono[at:at+round(period*copies)]
    loop=musdsp.resample(body,sr,R,taps=24,periodic=True)[:L]
    assert len(loop)==L
    # Captured sources retain their measured level. Explicit legacy fallback
    # captures may use a separately calibrated SoundFont amplitude anchor.
    if spec.get('measured_amplitude'):
        factor=1/32768
    else:
        old=z.float_tab[:max(1,round(z.rate*z.s_mid*.05))]
        new=mono[:round(sr*.05)]
        factor=math.sqrt((sum(v*v for v in old)/len(old))/max(1e-20,sum(v*v for v in new)/len(new)))
    factor*=10**(spec.get('gain_db',0)/20)
    loop=[v*factor for v in loop]
    attack_seconds=owner.q.attack*smin
    if spec.get('played_hold_seconds'):
        attack_seconds=min(attack_seconds,max(.01,spec['played_hold_seconds']-2*period/sr))
    A=round(attack_seconds*R)
    X=min(L//2,max(8,round(.004*R)))
    margin=math.ceil(R*smax/140*1.12)+32
    count=1<<math.ceil(math.log2(max(256,A+X+margin)))
    # Use already allocated attack bytes for
    # more of the real captured envelope, retaining the complete worst-pitch
    # switch margin and crossfade. No rate, loop size or table count changes.
    if spec.get('use_spare_attack'):
        A=max(A,min(count-X-margin,round(len(mono)*R/sr)-X-margin))
    if spec.get('maximum_bytes') and count>spec['maximum_bytes']:
        raise ValueError('captured melodic attack exceeds its pinned max_bytes')
    # The remaining bytes carry loop continuation; the switch can still be late.
    source=musdsp.resample(mono[:math.ceil((A+X+64)*sr/R)],sr,R,taps=24)
    tab=[v*factor for v in source[:A+X]]
    phase=musdsp.loop_phase(tab[A:A+X],loop)
    window=energy_window(sr,period,modeled)
    from audio_numeric import prefix_energy
    if 'prefix' not in features:
        prefix=prefix_energy(mono)
        if prefix is None:
            prefix=[0.]
            for v in mono:prefix.append(prefix[-1]+v*v)
        features['prefix']=prefix
    prefix=features['prefix']
    ref=sum(v*v for v in body)/len(body)
    def body_gain(index):
        if modeled:return 1.
        center=round(index/R*sr)
        lo=max(0,center-window//2);hi=min(len(mono),lo+window)
        p=(prefix[hi]-prefix[min(lo,len(mono))])/max(1,hi-lo)
        return math.sqrt(max(0.,p)/max(1e-10,ref))
    owner.exact_main(z,tab,mono,sr,R,A,factor=factor)
    for i in range(X):
        w=(i+.5)/X;tab[A+i]=tab[A+i]*(1-w)+loop[(phase+i)%L]*w*body_gain(A+i)
    # The scheduler switches on an exact music tick. Until that tick, the
    # attack table must continue the captured envelope instead of jumping to
    # a full-level body in the fractional tick after the crossfade.
    tab=tab[:A+X]+[loop[(phase+i-A)%L]*body_gain(i) for i in range(A+X,count)]
    lt=[loop[(i+phase-A)%L] for i in range(L)]
    if legacy_loop:lt.append(lt[0])
    z.kind='attack';z.loop_len=size;z.attack=(A+X)/R
    z.late_tics=max(1,int((count-A-X)/(R*smax*1.12)*140)-1)
    z.capture_held=True;z.baked_timpani=True;z.fine_static=spec.get('fine_static',False)
    z.morph_basis=None;z.s_mid=1.;z.s_min=smin;z.s_max=smax
    z.nat=z.nat_len=0.;z.required_rate=floor
    # Whole-period energy windows of at least 10ms and two fundamental
    # periods avoid measuring waveform phase as amplitude modulation.
    held=meta.get('hold',None)
    # capture.py stores the hold in the context metadata; use explicit spec
    # duration when present and otherwise the renderer MIDI metadata below.
    held=float(meta.get('hold_seconds',meta.get('hold',1.)))
    end=len(mono)/sr if spec.get('release_baked') else min(held,len(mono)/sr)
    envelope=[]
    for t in range(math.ceil(end*100)+1):
        k=min(len(mono)-1,round(t*.01*sr));lo=max(0,k-window//2);hi=min(len(mono),lo+window)
        p=(prefix[hi]-prefix[lo])/max(1,hi-lo)
        envelope.append(-10*math.log10(max(1e-10,p)/max(1e-10,ref)))
    z.capture_release_curve=[]
    release_ref=max(1e-10,sum(v*v for v in mono[max(0,round(held*sr)-window):round(held*sr)])/window)
    for t in range(max(1,math.ceil((len(mono)/sr-held)*100)+1)):
        lo=min(len(mono),round((held+t*.01)*sr));hi=min(len(mono),lo+window)
        p=(prefix[hi]-prefix[lo])/max(1,hi-lo)
        z.capture_release_curve.append(-10*math.log10(max(1e-10,p)/release_ref))
    if z.capture_release_curve:z.capture_release_curve[0]=0.
    z.capture_envelope=envelope
    z.capture_envelope_baked_release=bool(spec.get('release_baked'))
    z.capture_modeled=not spec.get('measured_amplitude',False)
    owner.finish(z,tab,lt,R)
    z.capture=dict(spec,rate=R,bytes=count,loop_bytes=size,capture_sha256=meta['wav_sha256'],dc=dc,
        amplitude_factor=factor,period_source_samples=period,period_correlation=correlation,
        period_copies=copies,loop_source_start=at/sr,strict_loop=True,envelope=envelope,attack_seconds=z.attack,
        instrument_match=match,switch_margin_bytes=margin)
    for v in sorted({n.voice for n in owner.notes if n.z is z and 0 <= n.voice < 24}):
        notes=sorted((n for n in owner.notes if n.voice==v),key=lambda n:n.on)
        for i,n in enumerate(notes):
            if n.z is z:
                cap=notes[i+1].on if i+1<len(notes) else owner.length
                tail=n.on+math.ceil(end/n.sp*140) if spec.get('release_baked') else n.off+math.ceil(n.r.release*(.6 if z.capture_modeled else 1.)*140)
                n.stop=max(n.stop,min(cap,tail))
    if spec.get('release_baked'):
        # Natural recorded decay remains finite; do not turn the tail into an
        # indefinitely sustained oscillator even if its score note is held.
        for n in z.notes:
            n.capture_end=n.on+math.ceil(end/n.sp*140)


def envelope_db(z,seconds,force=False):
    t=max(0.,seconds)
    if t<=z.attack and not force:return 0.
    position=min(len(z.capture_envelope)-1,t*100)
    i=int(position);j=min(i+1,len(z.capture_envelope)-1)
    v=z.capture_envelope[i]*(j-position)+z.capture_envelope[j]*(position-i) if j>i else z.capture_envelope[i]
    return v


def interpolate(curve, seconds):
    position=max(0.,min(len(curve)-1,seconds*100))
    i=int(position);j=min(i+1,len(curve)-1)
    return curve[i]+(curve[j]-curve[i])*(position-i)


def note_db(z, seconds, held, speed, loop_started=None):
    if z.capture_envelope_baked_release:
        return (0. if loop_started is False else
                envelope_db(z,seconds*speed,force=loop_started is True))
    db=0. if loop_started is False else envelope_db(z,min(seconds,held)*speed,force=loop_started is True)
    if seconds>held and getattr(z,'capture_release_curve',None):
        db+=interpolate(z.capture_release_curve,(seconds-held)*speed)
    return db
