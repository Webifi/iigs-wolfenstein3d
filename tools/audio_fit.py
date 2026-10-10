"""Measure compact sample candidates against the rendered instrument output."""
import math
import array
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent/'doccompiler'))
from musdsp import resample, rms
from audio_dsp import fft

DOC_RATE = 894886/34
BANDS = ((40,120), (120,400), (400,2000), (2000,5000), (5000,10000))
_QUALITY_EDGES = [40*2**(i/3) for i in range(27)]
QUALITY_BANDS = tuple(zip(_QUALITY_EDGES,_QUALITY_EDGES[1:]))


_band_cache = {}


def comparable_sources(main, other):
    """Compare real-time envelopes after normalizing recorded pitches."""
    rate, ref = main.measured_source
    sr, values = other.measured_source
    if rate == sr:
        return rate, ref, values
    outputs=[]
    for zone in (main,other):
        source_rate,source=zone.measured_source
        key=(source_rate,id(source),len(source))
        if getattr(zone,'comparison_source_key',None)!=key:
            zone.comparison_source=resample(source,source_rate,DOC_RATE,taps=24)
            zone.comparison_source_key=key
        outputs.append(zone.comparison_source)
    return DOC_RATE,*outputs


def band_energy(samples, rate, detailed=False):
    # Comparing many velocities reuses the same captures. Retain spectra,
    # not recordings, and include every sample bit in the cache identity.
    key = (hashlib.sha256(array.array('d', samples).tobytes()).digest(), rate)
    if key not in _band_cache:
        if len(_band_cache) >= 512:
            del _band_cache[next(iter(_band_cache))]
        _band_cache[key] = _band_energy(samples, rate)
    values = _band_cache[key]
    return values[len(BANDS):] if detailed else values[:len(BANDS)]


def _band_energy(samples, rate):
    from audio_numeric import band_energy as native_band_energy
    result=native_band_energy(samples,rate,BANDS+QUALITY_BANDS)
    if result is not None:return result
    size = 1024
    window = [.5-.5*math.cos(2*math.pi*i/(size-1)) for i in range(size)]
    bands = BANDS+QUALITY_BANDS
    result = [0.]*len(bands)
    # Include the onset and tail, as well as the steady body. Sampling at most
    # 64 windows bounds work on long recordings without dropping the attack.
    starts = list(range(0, max(1,len(samples)-size+1), max(size//2,len(samples)//64)))
    starts += [max(0,len(samples)-size)]
    for start in sorted(set(starts)):
        part = samples[start:start+size]
        part += [0.]*(size-len(part))
        spectrum = fft([v*w for v,w in zip(part,window)])
        for b,(lo,hi) in enumerate(bands):
            result[b] += sum(abs(spectrum[i])**2 for i in range(max(1,math.ceil(lo*size/rate)),min(size//2,math.ceil(hi*size/rate))))
    return [v/max(1,len(set(starts))) for v in result]


def compare(reference, candidate, rate=DOC_RATE, noise_floor=0.):
    ref, got = band_energy(reference,rate), band_energy(candidate,rate)
    reference_rms=rms(reference)
    scale = reference_rms/max(1e-15,rms(candidate))
    errors = [10*math.log10(max(1e-20,b*scale*scale)/max(1e-20,a)) for a,b in zip(ref,got)]
    threshold=max(ref,default=0)*.0003
    audible = [abs(e) for a,b,e in zip(ref,got,errors) if max(a,b*scale*scale) > threshold]
    first = max(1,round(.015*rate))
    attack = 20*math.log10(max(1e-15,rms(candidate[:first])*scale)/max(1e-15,rms(reference[:first])))
    envelope = []
    envelope_power_error = []
    starts=list(range(0,len(reference),max(1,round(.02*rate))))
    spans=[(start,start+round(.02*rate)) for start in starts]
    from audio_numeric import window_powers
    ref_power=window_powers(reference,spans);got_power=window_powers(candidate,spans)
    for i,start in enumerate(starts):
        a=math.sqrt(ref_power[i]) if ref_power is not None else rms(reference[start:start+round(.02*rate)])
        b=(math.sqrt(got_power[i]) if got_power is not None else rms(candidate[start:start+round(.02*rate)]))*scale
        if a > max(reference_rms*.03,noise_floor):
            envelope.append(abs(20*math.log10(max(1e-15,b)/a)))
            envelope_power_error.append(((b-a)**2,a*a))
    worst = max(audible+[abs(attack)]+envelope+[0.])
    # A large dB ratio in an almost empty band must not outweigh lost body
    # harmonics. Keep the strict ratios as diagnostics, but rank imperfect
    # fits by absolute band-amplitude and envelope error at matched loudness.
    detailed_ref = band_energy(reference,rate,detailed=True)
    detailed_got = band_energy(candidate,rate,detailed=True)
    detailed_errors = [10*math.log10(max(1e-20,b*scale*scale)/max(1e-20,a))
                       for a,b in zip(detailed_ref,detailed_got)]
    detailed_threshold=max(detailed_ref,default=0)*.0003
    detailed_audible = [abs(e) for a,b,e in zip(detailed_ref,detailed_got,detailed_errors)
                        if max(a,b*scale*scale)>detailed_threshold]
    worst = max([worst]+detailed_audible)
    total = max(1e-30,sum(detailed_ref))
    band_loss = math.sqrt(sum((math.sqrt(max(0,b))*scale-math.sqrt(max(0,a)))**2
                              for a,b in zip(detailed_ref,detailed_got))/total)
    envelope_loss = math.sqrt(sum(e for e,_ in envelope_power_error)/
                              max(1e-30,sum(p for _,p in envelope_power_error)))
    quality_loss = band_loss+.25*envelope_loss+.25*abs(10**(attack/20)-1)
    return dict(band_error_db=errors, attack_15ms_db=attack,
                envelope_worst_db=max(envelope,default=0), equal_gain=scale,
                worst_db=worst, within_half_db=worst<=.5, quality_loss=quality_loss,
                third_octave_error_db=detailed_errors)


def curve_value(curve, seconds):
    position = max(0.,min(len(curve)-1,seconds*100))
    i = int(position)
    j = min(i+1,len(curve)-1)
    return curve[i]+(curve[j]-curve[i])*(position-i)


def aligned_releases(template, response, rate, holds, window_seconds=.02):
    """Compare the common held interval, followed by each actual release.

    Do not treat one recording's released tail as the other's held sound.
    Match the player's release anchor: each release starts at the level the
    instrument had at the common note-off. Otherwise natural held decay is
    corrected twice, once here and once by the player's release envelope.
    """
    a,b=(max(0,round(t*rate)) for t in holds)
    common=min(a,b)
    width=max(1,round(window_seconds*rate))
    def shortened(values, held):
        at_common=rms(values[max(0,common-width):common])
        at_release=rms(values[max(0,held-width):held])
        gain=at_common/max(1e-15,at_release)
        return values[:common]+[v*gain for v in values[held:]]
    return shortened(template,a),shortened(response,b)


def comparison_holds(main, other):
    if (getattr(main,'capture_baked_articulation',False) or
            getattr(other,'capture_baked_articulation',False) or
            not hasattr(main,'capture_input') or not hasattr(other,'capture_input')):
        return None
    if main.drum or main.notes[0].preset[1] in (118,127):
        return None
    return main.capture_input[4],other.capture_input[4]


def match_response(template, response, rate, noise_floor=2/32768, allow_approximation=False, holds=None, fundamental=None):
    """Share a timbre only if its measured gain/envelope reproduces the response.

    A fixed spectral tolerance separates an instrument change from an amplitude
    change. The latter is carried by volume registers, never quieter sample bytes.
    Check the corrected response again; RAM pressure cannot loosen either check.
    """
    window_seconds=(max(2,math.ceil(.02*fundamental))/fundamental if fundamental else .02)
    if holds is not None:
        first,second=aligned_releases(template,response,rate,holds,window_seconds)
        result=match_response(first,second,rate,noise_floor,allow_approximation,fundamental=fundamental)
        curve=result.get('curve_db',[])
        if curve:
            common=min(holds)
            result['curve_db']=[curve_value(curve, min(i*.01,common) if i*.01<=holds[0]
                                            else common+i*.01-holds[0])
                                for i in range(math.ceil(len(template)/rate*100)+1)]
        result['aligned_note_off_seconds']=list(holds)
        return result
    count = max(len(template),len(response))
    template = template+[0.]*(count-len(template))
    response = response+[0.]*(count-len(response))
    before = compare(response,template,rate,noise_floor=noise_floor)
    bands = band_energy(response,rate)
    threshold=max(bands)*.0003
    audible = [abs(e) for a,e in zip(bands,before['band_error_db']) if a > threshold]
    first = max(1,round(.015*rate))
    attack_ref = band_energy(response[:first],rate)
    attack_got = band_energy(template[:first],rate)
    scale = sum(attack_ref)/max(1e-30,sum(attack_got))
    attack_errors = [10*math.log10(max(1e-30,b*scale)/max(1e-30,a)) for a,b in zip(attack_ref,attack_got)]
    threshold=max(attack_ref)*.0003
    audible += [abs(e) for a,e in zip(attack_ref,attack_errors) if a > threshold]
    before['attack_band_error_db'] = attack_errors
    timbre_matches = max(audible,default=0.) <= .5
    if not timbre_matches and not allow_approximation:
        return dict(compatible=False,before=before,reason='different measured attack/body timbre')
    gain = before['equal_gain']
    if timbre_matches and before['within_half_db']:
        return dict(compatible=True,gain_db=20*math.log10(max(1e-15,gain)),curve_db=[],
                    before=before,after=before)
    from audio_numeric import prefix_energy
    prefixes = []
    for values in (template,response):
        prefix=prefix_energy(values)
        if prefix is None:
            prefix=[0.]
            for v in values:prefix.append(prefix[-1]+v*v)
        prefixes.append(prefix)
    width = max(1,round(window_seconds*rate))
    threshold = max(rms(response)*.02,noise_floor)
    curve = []
    for i in range(math.ceil(count/rate*100)+1):
        center = round(i*.01*rate)
        lo = max(0,center-width//2)
        hi = min(count,lo+width)
        a,b = [math.sqrt(max(0.,p[hi]-p[min(lo,count)])/max(1,hi-lo)) for p in prefixes]
        # Below the measurable tail, carry the last correction instead of
        # fitting the renderer's idle/quantization noise.
        if a*gain > threshold and b > threshold:
            curve.append(20*math.log10(a*gain/b))
        else:
            curve.append(curve[-1] if curve else 0.)
    from audio_numeric import corrected as native_corrected
    corrected=native_corrected(template,gain,curve,rate)
    if corrected is None:
        corrected = [v*gain*10**(-curve_value(curve,i/rate)/20) for i,v in enumerate(template)]
    after = compare(response,corrected,rate,noise_floor=noise_floor)
    return dict(compatible=timbre_matches and after['within_half_db'],gain_db=20*math.log10(max(1e-15,gain)),
                curve_db=curve,before=before,after=after)


def sample_candidates(source, source_rate, max_bytes=4096, rate=None, auto_fit=True, minimum_rate=2000, resolution='effect'):
    """Measure legal complete-duration samples for local or bank-wide fitting."""
    reference = resample(source,source_rate,DOC_RATE,taps=24)
    if resolution not in ('music','effect'):
        raise ValueError('unknown DOC resolution policy')
    anchor_peak=max(map(abs,reference),default=0) or 1.
    from audio_numeric import quantized_values,quantize
    anchor=quantized_values(reference,anchor_peak)
    if anchor is None:anchor=[max(-127,min(127,round(v*127/anchor_peak)))*anchor_peak/127 for v in reference]
    anchor_metrics=compare(reference,anchor)
    rates = [rate] if rate is not None else [64000,48000,32000,DOC_RATE,24000,20000,16000,12000,10000,8000,6000,4000,3000,2000]
    if rate is None and auto_fit and resolution=='music':
        # A legal boundary rate may fit a page size which the fixed ladder
        # misses. Quantize upward so the resulting DOC rate respects it too.
        rates.append(math.ceil(minimum_rate*512/DOC_RATE)*DOC_RATE/512)
    if not auto_fit and rate is None:
        rates = [DOC_RATE]
    candidates = []
    seen = set()
    for requested in rates:
        if requested < minimum_rate:
            continue
        size = 256
        while size-1 < len(source)/source_rate*requested:
            size *= 2
        if resolution=='music' and size>max_bytes:
            continue
        # The rendered release can outlast its last representable 8-bit
        # sample. Quantize before deciding that the complete sound overflows.
        # Only trailing midpoint bytes may be removed; they decode to zero.
        quantization_size = min(size,max_bytes)
        # Music sets resolution equal to the size code (shift 9). Effects
        # retain the native player's resolution 7 (shift 16 - size code).
        divisor=512 if resolution=='music' else 65536/(quantization_size/256)
        fc = round(requested*divisor/DOC_RATE)
        if not 0<fc<65536:
            continue
        actual = DOC_RATE*fc/divisor
        table = resample(source,source_rate,actual,taps=24)
        peak = max(map(abs,table),default=0) or 1
        quantized=quantize(table,peak)
        if quantized is None:quantized=bytes(max(1,min(255,128+round(v*127/peak))) for v in table)
        trimmed = (quantized.rstrip(b'\x80') or b'\x80') if resolution=='effect' else quantized
        size = 1 << math.ceil(math.log2(max(256,len(trimmed)+1)))
        if size>quantization_size:
            continue
        if resolution=='effect':
            fc = round(fc*quantization_size/size)
        if not 0<fc<65536 or (size,fc) in seen:
            continue
        seen.add((size,fc))
        encoded = trimmed+b'\0'
        # DOC advances its phase before reading, plays all N table bytes, and
        # holds each addressed byte until the next sample service.
        from audio_numeric import sample_playback
        decoded=sample_playback(encoded,peak,actual,DOC_RATE,len(reference))
        if decoded is None:
            decoded=[]
            for i in range(len(reference)):
                at=math.floor((i+1)*actual/DOC_RATE)
                decoded.append((encoded[at]-128)*peak/127 if at<len(encoded)-1 else 0.)
        metrics = compare(anchor,decoded)
        metrics['full_rate_anchor']=anchor_metrics
        metrics['valid_anchor']=anchor_metrics['within_half_db']
        metrics['within_half_db'] &= metrics['valid_anchor']
        candidates.append(dict(rate=actual, requested_rate=requested, fc=fc, bytes=len(encoded),
                               table_bytes=size, peak=peak, pcm=encoded, metrics=metrics,
                               read_step=actual/DOC_RATE,
                               removed_silent_samples=len(quantized)-len(trimmed),
                               step_one_table_bytes=1<<math.ceil(math.log2(max(256,len(source)/source_rate*DOC_RATE+1)))))
    if not candidates:
        raise ValueError('complete sample duration cannot fit the page budget at the permitted rates')
    return candidates


def choose_sample(candidates):
    """Prefer fewer pages within tolerance, otherwise the least measured error."""
    passed = [c for c in candidates if c['metrics']['within_half_db']]
    return min(passed,key=lambda c:(c['table_bytes'],c['metrics']['worst_db'],c['bytes'])) if passed else min(candidates,key=lambda c:(c['metrics'].get('quality_loss',c['metrics']['worst_db']),c['table_bytes']))


def fit(source, source_rate, max_bytes=4096, rate=None, auto_fit=True, minimum_rate=2000, resolution='effect'):
    """Fit one sample without cutting its duration; return measured alternatives."""
    candidates = sample_candidates(source,source_rate,max_bytes,rate,auto_fit,minimum_rate,resolution)
    chosen = choose_sample(candidates)
    report = [{k:v for k,v in c.items() if k!='pcm'} for c in candidates]
    return chosen,report
