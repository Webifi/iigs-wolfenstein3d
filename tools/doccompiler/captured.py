"""Song-local wet SC-55 table substitutions; all work happens at build time."""
import array
import copy
import json
import math
from pathlib import Path
import wave


def install(owner, specs):
    import musdsp
    if any(s.get('mel') for s in specs):
        raise ValueError('use ordinary captured-tone settings in portable recipes')
    for spec in specs:
        zlist = [z for z in owner.zones if z.notes and
                 any(n.ch == spec['channel']-1 and n.key == spec['key'] for n in z.notes)]
        if len(zlist) != 1:
            raise ValueError(('capture zone is ambiguous', spec, len(zlist)))
        z = zlist[0]
        # Strict melodic trial: rebuild from the immutable wet recording.
        # This first fit retains each capture's original time span; the ordered
        # fit report exposes any page pressure rather than hiding a slow rate.
        import mussc
        original_spec = spec
        if getattr(owner, 'capture_loops', False) and mussc.strict_tone(z):
            import capture_tone
            capture_tone.install(owner,z,spec)
            continue
        if getattr(mussc, '_wolf_tone_safe', False) and mussc.strict_tone(z):
            spec = dict(spec)
            speeds = [2**((n.key-spec['key']+b)/12) for n in z.notes for _,b in n.bends]
            wanted = mussc.DOC_RATE * (513/512) / min(speeds)
            if wanted > spec['rate']:
                scale = wanted/spec['rate']
                def power2(x):
                    return 1 << math.ceil(math.log2(max(256,x)))
                spec['bytes'] = power2(spec['bytes']*scale)
                if spec.get('loop_bytes'):
                    spec['loop_bytes'] = power2(spec['loop_bytes']*scale)
                spec['rate'] = wanted
            z.required_rate = wanted
        path = Path(spec['wav'])
        meta = json.loads(path.with_suffix('.json').read_text())
        with wave.open(str(path)) as f:
            assert f.getnchannels() == 2 and f.getsampwidth() == 2
            source_rate = f.getframerate()
            values = array.array('h', f.readframes(f.getnframes()))
        lead = round(meta['lead'] * source_rate)
        dc = sum(values[:lead*2]) / (lead*2)
        if abs(dc-512) > 2:
            raise ValueError(('unexpected capture DC', dc))
        mono = [(a+b)/2-dc for a,b in zip(values[::2], values[1::2])][lead:]
        rate = spec['rate']
        count = spec['bytes'] - (0 if spec.get('loop_bytes') else 1)
        source = musdsp.resample(mono, source_rate, rate, taps=24)
        tab = source[:count]
        tab += [0.] * (count-len(tab))
        # Keep the prior early attack energy as a starting amplitude, then
        # measure and calibrate the whole part against its independent solo.
        # This does not claim that the prior sample's envelope is authoritative.
        window = .05
        old = z.float_tab[:max(1, round(z.rate*z.s_mid*window))]
        new = tab[:max(1, round(rate*window))]
        factor = math.sqrt((sum(x*x for x in old)/len(old)) / max(1e-20, sum(x*x for x in new)/len(new)))
        factor *= 10 ** (spec.get('gain_db', 0)/20)
        tab = [x*factor for x in tab]
        loop = None
        if spec.get('loop_bytes'):
            length = spec['loop_bytes']
            assert length & (length-1) == 0 and count & (count-1) == 0
            # A captured steady segment; the start of the loop is joined to
            # its following repetition, then the attack joins that same phase.
            cross = min(length//4, max(16,round(.008*rate)))
            margin = math.ceil(rate * max(2**((n.key-spec['key'])/12) for n in z.notes) / 140) + 32
            attack = count - cross - margin
            if attack < 32:raise ValueError('captured attack needs a larger table')
            start = max(attack,round(spec.get('loop_start',.2)*rate))
            assert len(source) >= start+length+cross
            cyc = [x*factor for x in source[start:start+length+cross]]
            for i in range(cross):
                w=(i+.5)/cross
                cyc[i]=cyc[i]*w+cyc[length+i]*(1-w)
            phase=max(range(length),key=lambda ph:sum(tab[attack+i]*cyc[(ph+i)%length] for i in range(0,cross,2)))
            for i in range(cross):
                w=(i+.5)/cross
                tab[attack+i]=tab[attack+i]*(1-w)+cyc[(phase+i)%length]*w
            for i in range(attack+cross,count):tab[i]=cyc[(phase+i-attack)%length]
            loop=[cyc[(i+phase-attack)%length] for i in range(length)]
            z.capture_held=True
            z.attack=(attack+cross)/rate
            z.late_tics=max(1,int(margin/(rate*max(2**((n.key-spec['key'])/12) for n in z.notes))*140)-1)
        else:
            fade = min(len(tab), round(.02*rate))
            for i in range(fade):
                tab[-fade+i] *= (fade-i-1)/fade
        for n in owner.notes:
            if n.z is not z:
                continue
            speed = 2 ** ((n.key-spec['key'])/12) if n.ch != 9 else 1.
            # The captured waveform already contains the SC-55 pitch envelope
            # and native vibrato. Only score pitch bends remain as DOC changes.
            n.freqs = [(t, speed*2**(bend/12)) for t,bend in n.bends]
            n.sp = speed
            if spec.get('release_baked'):
                # Use only when the captured release represents these source
                # notes (or SC-55 renders prove note-off is immaterial).
                n.r=copy.copy(n.r)
                n.r.release=2.0
            if spec.get('release_seconds'):
                n.r=copy.copy(n.r)
                n.r.release=spec['release_seconds']
                n.capture_release=True
        z.kind = 'attack' if loop else 'oneshot'
        z.loop_len = len(loop) if loop else 0
        z.nat = z.nat_len = 0.
        z.morph_basis = None
        z.baked_timpani = True
        z.fine_static = spec.get('fine_static',True)
        z.s_mid = 1.
        z.s_min = min(n.sp for n in z.notes)
        z.s_max = max(n.sp for n in z.notes)
        owner.finish(z, tab, loop, rate)
        z.capture = dict(spec, original_spec=original_spec, capture_sha256=meta['wav_sha256'], dc=dc, amplitude_factor=factor)
        # Protect source-held time; allow the captured ringing to occupy idle
        # release space, never the next note's held interval.
        for v in range(24):
            ns = sorted((n for n in owner.notes if n.voice==v), key=lambda n:n.on)
            for i,n in enumerate(ns):
                if n.z is z:
                    cap = ns[i+1].on if i+1<len(ns) else owner.length
                    tail = n.off + math.ceil(n.r.release*.6*140) if loop else n.on+math.ceil(z.dur/n.sp*140)
                    n.stop = max(n.stop, min(cap, tail))
    owner.layout()
