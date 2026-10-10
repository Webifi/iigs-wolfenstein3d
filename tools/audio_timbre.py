"""Match legal DOC loops to the played instrument's harmonic and noise energy.

All candidates use the same emulator capture. No substitute instrument or
oscillator waveform is synthesized. Matching is at the actual DOC read rate,
after eight-bit quantization, within the allocator's existing page allowance.
"""
import math
import copy
import array
import hashlib
from collections import defaultdict

from audio_fit import DOC_RATE,curve_value
from musdsp import resample
from audio_dsp import fft,correlation_peak


def measured_period(mono, rate, fundamental, start, end=None):
    """Measure multiple cycles so source sample holds cannot detune a loop."""
    nominal=rate/fundamental
    available=(len(mono) if end is None else min(len(mono),round(end*rate)))-start
    cycles=max(1,min(8,int(available/nominal)-3))
    low=max(2,round(nominal*cycles*.97))
    high=round(nominal*cycles*1.03)
    span=min(round(nominal*12),available-high-1)
    if span<max(8,round(nominal)):
        return nominal,0.
    lag,correlation=correlation_peak(mono[start:start+span+high+1],span,low,high)
    return lag/cycles,correlation


class BankAllocationError(ValueError):
    """The complete set of measured candidates cannot fit the page budget."""
    def __init__(self, minimum, budget):
        self.minimum, self.budget = minimum, budget
        super().__init__(f'measured instrument candidates need at least {minimum} pages; DOC page budget is {budget}')


def choose_bank(options, budget):
    """Minimize measured error across a bank under its page limit."""
    states={0:(0.,[])}
    for choices in options:
        following={}
        for used,(cost,selected) in states.items():
            for index,(pages,error) in enumerate(choices):
                total=used+pages
                if total>budget:
                    continue
                candidate=(cost+error,selected+[index])
                if total not in following or candidate[0]<following[total][0]:
                    following[total]=candidate
        states=following
    if not states:
        minimum=sum(min(p for p,_ in choices) for choices in options)
        raise BankAllocationError(minimum, budget)
    _,(_,selected)=min(states.items(),key=lambda row:(row[1][0],row[0]))
    return selected


def score_tone(zone, source, source_rate, cache=None):
    """Score every captured variant represented by this candidate table."""
    groups=defaultdict(list)
    for n in zone.notes:
        if n.half!=0:continue
        reference=getattr(n,'capture_reference',None)
        key=(reference[3] if reference else None,getattr(n,'capture_level_db',0.),
             tuple(getattr(n,'capture_response_curve',[])),getattr(n,'capture_response_hold',None))
        groups[key].append(n)
    rows=[]
    for (identity,gain,curve,held),notes in groups.items():
        part=copy.copy(zone);part.notes=notes
        reference=getattr(notes[0],'capture_reference',None)
        rate,values=reference[:2] if reference else (source_rate,source)
        result=score_variant(part,values,rate,cache,identity,gain,curve,
                             reference[2] if reference else None,held)
        rows.append(dict(notes=len(notes),source_capture=identity,**result))
    count=sum(r['notes'] for r in rows)
    return dict(distance=sum(r['notes']*r['distance'] for r in rows)/max(1,count),
                variants=rows,method='each original played variant against its final DOC representation',
                listening_accepted=False)


def score_variant(zone, source, source_rate, cache=None, identity=None, gain_db=0., curve=(),
                  source_hold=None, curve_hold=None):
    if cache is None:
        return _score_variant(zone,source,source_rate,cache,identity,gain_db,curve,source_hold,curve_hold)
    # Context merges retain the old played captures. Re-score only a changed
    # representation or note interval, including every envelope/gain input.
    key=('variant',identity or zone.capture['capture_sha256'],len(source),source_rate,
         zone.capture.get('loop',{}).get('bandwidth_hz'),zone.kind,zone.rate,getattr(zone,'attack',0.),
         bytes(zone.table),bytes(zone.ltable),max(map(abs,zone.float_tab),default=0.),
         max(map(abs,zone.float_lt),default=0.),hasattr(zone,'loop_gain'),zone.capture_root,
         tuple(getattr(zone,'capture_envelope',())),getattr(zone,'capture_envelope_baked_release',False),
         tuple(getattr(zone,'capture_release_curve',()) or ()),
         tuple((n.off,n.on,n.sp) for n in zone.notes if n.half==0),gain_db,tuple(curve),source_hold,curve_hold)
    if key not in cache:
        cache[key]=_score_variant(zone,source,source_rate,cache,identity,gain_db,curve,source_hold,curve_hold)
    # Window measurements are read-only; callers own the outer result record.
    return dict(cache[key])


def _score_variant(zone, source, source_rate, cache=None, identity=None, gain_db=0., curve=(),
                  source_hold=None, curve_hold=None):
    """Compare a quantized attack/body with its own played capture.

    Score the ages present in this part's notes. Phase differences are not
    instrument differences: compare harmonic/noise energy and the envelope.
    The score ranks representations of one source, not different instruments.
    """
    from capture_tone import envelope_db,note_db
    holds=[(len(source)/source_rate if zone.kind=='oneshot' or getattr(zone,'capture_envelope_baked_release',False) else
            (n.off-n.on)/140*n.sp) for n in zone.notes if n.half==0]
    end=(min(len(source)/source_rate,max(1.,source_hold+.25)) if source_hold is not None else
         min(len(source)/source_rate,max(holds,default=.25),1.))
    frames=max(1,round(end*DOC_RATE))
    cache={} if cache is None else cache
    key=(identity or zone.capture['capture_sha256'],source_rate,frames,zone.capture.get('loop',{}).get('bandwidth_hz'))
    if key not in cache:
        cache[key]=resample(source[:math.ceil(end*source_rate)+64],source_rate,DOC_RATE,taps=24)[:frames]
    reference=cache[key]
    peak=max(map(abs,zone.float_tab+zone.float_lt)) or 1.
    attack_peak=(max(map(abs,zone.float_tab)) or 1.) if hasattr(zone,'loop_gain') else peak
    loop_peak=(max(map(abs,zone.float_lt)) or 1.) if hasattr(zone,'loop_gain') else peak
    fc=round(zone.rate*512/DOC_RATE)
    attack_end=(round(max(1,round(zone.attack*140))/140*DOC_RATE)
                if zone.kind!='oneshot' else frames)
    from audio_numeric import decoded as native_decoded
    decoded=native_decoded(zone,frames,fc,attack_end,attack_peak,loop_peak,gain_db,curve,source_hold,curve_hold,DOC_RATE)
    if decoded is None:
        decoded=[]
        for i in range(frames):
            if zone.kind=='oneshot':
                at=((i+1)*fc)>>9
                value=(zone.table[at]-128)*attack_peak/127 if at<len(zone.table) else 0.
                gain=1.
            else:
                table=zone.table if i<attack_end else zone.ltable
                at=(((i+1)*fc)>>9)%len(table)
                value=(table[at]-128)*(attack_peak if i<attack_end else loop_peak)/127
                db=(note_db(zone,i/DOC_RATE,source_hold,1.,i>=attack_end) if source_hold is not None else
                    envelope_db(zone,i/DOC_RATE,force=True) if i>=attack_end else 0.)
                gain=10**(-db/20)
            age=i/DOC_RATE
            if curve_hold is not None and source_hold is not None and age>source_hold:
                age=curve_hold+age-source_hold
            correction=curve_value(curve,age) if curve else 0.
            decoded.append(value*gain*10**((gain_db-correction)/20))
    fundamental=440*2**((zone.capture_root-69)/12)
    rows=[]
    width=round(.04*DOC_RATE)
    power_key=('reference-power',key)
    if power_key not in cache:cache[power_key]=sum(v*v for v in reference)/max(1,len(reference))
    global_power=cache[power_key]
    windows=[(start,min(frames,start+width),1.) for start in range(0,frames,width)]
    # Short attacks can define the instrument even when the body lasts much
    # longer. Measure their shape at several onset scales as well as the body.
    windows += [(0,min(frames,round(seconds*DOC_RATE)),1/3) for seconds in (.005,.01,.02)]
    from audio_numeric import spectra as batch_spectra,window_powers
    intervals=[(a,b) for a,b,_ in windows]
    ref_power=window_powers(reference,intervals)
    got_power=window_powers(decoded,intervals)
    selected=[]
    for index,(start,stop,importance) in enumerate(windows):
        age=start/DOC_RATE
        weight=len(holds) if source_hold is not None else sum(h>age for h in holds)
        power=(ref_power[index] if ref_power is not None else
               sum(v*v for v in reference[start:stop])/max(1,len(reference[start:stop])))
        candidate_power=(got_power[index] if got_power is not None else
                         sum(v*v for v in decoded[start:stop])/max(1,len(decoded[start:stop])))
        if weight and max(power,candidate_power)>=global_power*.001:
            selected.append((start,stop,importance,age,weight,power,candidate_power))
    missing=[(a,b) for a,b,*_ in selected if ('spectrum',key,a,b,fundamental) not in cache]
    if missing:
        measured=batch_spectra(reference,missing,DOC_RATE,fundamental)
        for i,(a,b) in enumerate(missing):
            cache['spectrum',key,a,b,fundamental]=(measured[i] if measured is not None else spectrum(reference[a:b],DOC_RATE,fundamental))
    measured=(batch_spectra(decoded,[(a,b) for a,b,*_ in selected],DOC_RATE,fundamental) if selected else [])
    for index,(start,stop,importance,age,weight,power,candidate_power) in enumerate(selected):
        spectral_key=('spectrum',key,start,stop,fundamental)
        metrics=difference(cache[spectral_key],measured[index] if measured is not None else spectrum(decoded[start:stop],DOC_RATE,fundamental))
        level=10*math.log10(max(1e-20,candidate_power)/max(1e-20,power))
        rows.append(dict(age_seconds=age,weight=weight*importance,level_db=level,**metrics))
    error=sum(row['weight']*(row['distance']+abs(row['level_db'])) for row in rows)/max(1,sum(row['weight'] for row in rows))
    return dict(distance=error,windows=rows,method='captured attack and body at the DOC read rate',listening_accepted=False)


def spectrum(values, rate, fundamental):
    from audio_numeric import spectra
    measured=spectra(values[:2048],[(0,min(2048,len(values)))],rate,fundamental)
    if measured is not None:return measured[0]
    size = 2048
    from audio_numeric import power as native_power
    power=native_power(values,size,size-1)
    if power is None:
        values = (list(values)+[0.]*size)[:size]
        bins = fft([v*(.5-.5*math.cos(2*math.pi*i/(size-1))) for i,v in enumerate(values)])
        power = [abs(v)**2 for v in bins[:size//2]]
    else:power=power[:size//2]
    total = sum(power[1:]) or 1e-30
    def energy(lo, hi):
        return sum(power[max(1,math.ceil(lo*size/rate)):min(size//2,math.ceil(hi*size/rate))])/total
    # Third-octave bands retain unpitched breath/noise as well as harmonics.
    edges = [40*2**(i/3) for i in range(26)]
    bands = [energy(a,b) for a,b in zip(edges,edges[1:])]
    harmonics = [math.sqrt(energy((h-.45)*fundamental,(h+.45)*fundamental))
                 for h in range(1,min(40,int(rate/2/fundamental))) ]
    norm = math.sqrt(sum(v*v for v in harmonics)) or 1.
    return bands,[v/norm for v in harmonics]


def difference(reference, candidate):
    ref, rh = reference
    got, gh = candidate
    errors = [10*math.log10(max(1e-12,b)/max(1e-12,a)) for a,b in zip(ref,got)]
    # Added energy matters too. Testing only the reference's occupied bands
    # rewards loops with the right harmonics but audible aliasing between them.
    threshold=max(ref)*.0003
    audible = [e for a,b,e in zip(ref,got,errors) if max(a,b) >= threshold]
    band_rms = math.sqrt(sum(e*e for e in audible)/max(1,len(audible)))
    cosine = min(1.,max(0.,sum(a*b for a,b in zip(rh,gh))))
    return dict(distance=band_rms+20*math.sqrt(max(0.,2*(1-cosine))),
                band_rms_db=band_rms, harmonic_cosine=cosine, band_error_db=errors)


def allocation(rate, size, attack, slowest, fastest):
    cross = min(size//2,max(8,round(.004*rate)))
    margin = math.ceil(rate*fastest/140*1.12)+32
    count = 1 << math.ceil(math.log2(max(256,round(attack*slowest*rate)+cross+margin)))
    return count+size


def match_body(mono, sr, key, bend, slowest, fastest, holds, attack, baseline,
               requested_rate=None, source_hold=None, cache=None):
    """Offer captured bodies of different sizes to the complete-bank allocator.

    Short notes and long notes contribute the body ages they actually play.
    Velocity variants must have the same root and capture hold before calling.
    The returned distance ranks candidates; it is not a listening verdict.
    """
    start, period, size, copies, rate = baseline
    cache={} if cache is None else cache
    source_key=hashlib.sha256(array.array('d',mono)).digest()
    floor = DOC_RATE*(513/512)/slowest
    budget = max(allocation(rate,size,attack,slowest,fastest),
                 allocation(floor,8192,attack,slowest,fastest))
    fundamental = 440*2**((key+bend-69)/12)
    nominal = sr/fundamental
    held = sorted(h for h in holds if h > attack*slowest+.02)
    body_end=min(len(mono)/sr,source_hold if source_hold is not None else len(mono)/sr)
    end = min(body_end-.01,max(held,default=.25),1.)
    first = min(.025,end)
    ages = sorted(set([first+(end-first)*i/3 for i in range(4)]+[start/sr]))
    ages = [a for a in ages if .01 <= a <= end]
    if not ages:
        return baseline, None
    references = []
    for age in ages:
        count = sum(h > age for h in held)
        if not count:
            continue
        at = max(0,round((age-.02)*sr))
        ref_key=('body-reference',source_key,sr,at,round(.10*sr),fundamental)
        if ref_key not in cache:
            values=resample(mono[at:at+round(.10*sr)],sr,DOC_RATE,taps=24)
            cache[ref_key]=spectrum(values,DOC_RATE,fundamental)
        references.append((count,cache[ref_key]))
    if not references:
        return baseline, None
    weight = sum(w for w,_ in references)
    reference = tuple([sum(w*s[k][i] for w,s in references)/weight
                       for i in range(len(references[0][1][k]))] for k in (0,1))
    norm = math.sqrt(sum(v*v for v in reference[1])) or 1.
    reference = reference[0],[v/norm for v in reference[1]]
    choices = {baseline}
    for age in ages:
        at = round(age*sr)
        period_key=('body-period',source_key,sr,fundamental,at,body_end)
        if period_key not in cache:cache[period_key]=measured_period(mono,sr,fundamental,at,body_end)
        period,_=cache[period_key]
        for size in (256,512,1024,2048,4096,8192):
            # Include long natural segments instead of restricting all bodies
            # to 32 cycles. Bound the rate choices; do not enumerate every
            # possible cycle count for every velocity and attack length.
            counts={1}
            for target in ([requested_rate] if requested_rate else [floor,floor*1.5,floor*2]):
                center=size*sr/(period*target)
                counts.update((max(1,math.floor(center)),max(1,math.ceil(center))))
            for copies in sorted(counts):
                source_count=round(period*copies)
                rate = size*sr/source_count
                if not floor <= rate <= 4*floor:
                    continue
                if requested_rate and abs(rate-requested_rate)/requested_rate >= .03:
                    continue
                if allocation(rate,size,attack,slowest,fastest) <= budget and at+source_count <= round(body_end*sr):
                    choices.add((at,period,size,copies,rate))
    peak = max(map(abs,mono[:max(1,round(attack*slowest*sr))]),default=1.)
    def measure(choice):
        at,period,size,copies,rate=choice
        # Note durations change reference weights and page allowances, while
        # an unchanged quantized waveform keeps its measured spectrum.
        candidate_key=('body-candidate',source_key,sr,at,round(period*copies),size,rate,peak,fundamental)
        if candidate_key in cache:
            metrics=difference(reference,cache[candidate_key])
            choice=(at,period,size,copies,rate)
            return (metrics['distance'],allocation(rate,size,attack,slowest,fastest),choice,metrics)
        loop = resample(mono[at:at+round(period*copies)],sr,rate,taps=24,periodic=True)[:size]
        if len(loop) != size:
            return None
        scale = max(peak,max(map(abs,loop))) or 1.
        dc = sum(loop)/len(loop)
        if abs(dc)*127/scale > .5:
            loop = [v-dc for v in loop]
        frequency = round(rate*512/DOC_RATE)
        from audio_numeric import quantized_loop
        decoded=quantized_loop(loop,scale,frequency,2048)
        if decoded is None:
            encoded=[max(-127,min(127,round(v*127/scale))) for v in loop]
            decoded=[encoded[((i+1)*frequency>>9)%size] for i in range(2048)]
        shape=spectrum(decoded,DOC_RATE,fundamental)
        cache[candidate_key]=shape
        metrics = difference(reference,shape)
        choice = (at,period,size,copies,rate)
        return (metrics['distance'],allocation(rate,size,attack,slowest,fastest),choice,metrics)
    from audio_workers import map_fits
    import os
    ordered=sorted(choices)
    jobs=int(os.environ.get('WOLF_AUDIO_WORKERS','1')) if os.environ.get('WOLF_AUDIO_POOL') else 1
    width=max(1,math.ceil(len(ordered)/jobs))
    chunks=[ordered[i:i+width] for i in range(0,len(ordered),width)]
    groups=map_fits(lambda chunk:[measure(choice) for choice in chunk],chunks)
    ranked=[row for group in groups for row in group if row is not None]
    chosen = min(ranked,key=lambda r:(r[0],r[1],r[2]))
    prior = next(row for row in ranked if row[2] == baseline)
    allocations={}
    for row in ranked:
        if row[1] not in allocations or (row[0],row[2])<(allocations[row[1]][0],allocations[row[1]][2]):
            allocations[row[1]]=row
    report = dict(method='played instrument: third-octave and harmonic comparison at the DOC rate',
                  candidates=len(ranked), allocation_limit=budget, selected_allocation=chosen[1],
                  previous=prior[3],selected=chosen[3],reference_body_ages_seconds=ages,
                  alternatives=[dict(bytes=size,choice=row[2],metrics=row[3]) for size,row in sorted(allocations.items())],
                  listening_accepted=False)
    return chosen[2], report
