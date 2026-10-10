"""Strict played-pitch rate floor for melodic SF2 tables. GPL-licensed build tool.

No kit, Synth Drum or Gunshot conversion changes. The captured-tone path is
selected separately; its original 64 kHz recording remains immutable.
"""
import inspect
from source_identity import function_source
import textwrap

ALL_L = True      # The DOC plays all N bytes of each power-of-two loop.


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(('loop patch: expected one occurrence', old, text.count(old)))
    return text.replace(old, new)


def install(mussc):
    if getattr(mussc, '_wolf_tone_safe', False):
        return
    mussc._wolf_tone_safe = True
    mussc.strict_tone = lambda z: not z.drum and z.notes[0].preset[1] not in (118, 127)
    source = textwrap.dedent(function_source(mussc.ScSong.build))
    needle = '    R_one = R_loop = R\n'
    assert needle in source
    # Preserve filtering/energy selection, but remove rate exceptions for tones.
    start = source.index('    if not z.drum and q.reff_min:')
    end = source.index('    if z.native:', start)
    old = source[start:end]
    source = source[:start] + old.replace('if not z.drum and q.reff_min:', 'if not strict_tone(z) and not z.drum and q.reff_min:', 1) + source[end:]
    needle = "    z.kind = 'oneshot'"
    addition = '''    if strict_tone(z):
        played_min = min(sp for n in z.notes for _, sp in n.freqs)
        floor = DOC_RATE * (513.0 / 512.0) / played_min
        R_one = max(R_one, floor)
        R_loop = max(R_loop, floor)
        z.required_rate = floor
'''
    assert source.count(needle) == 1
    source = source.replace(needle, addition + needle)
    if ALL_L:
        source = replace_once(source, 'while tone and lbytes - 1 < lsrc_est * R_loop / rate:', 'while tone and lbytes < lsrc_est * R_loop / rate:')
    exec(compile(source, 'Wolf strict melodic table rate', 'exec'), mussc.__dict__)
    mussc.ScSong.build = mussc.build

    source = textwrap.dedent(function_source(mussc.ScSong.build_looped))
    # Fit melodic periods whenever the resampled loop would exceed 4095
    # bytes, even if source duration is below the long-loop threshold.
    source = source.replace('(bool(z.mix) or lsrc > q.long_loop * rate)', '(bool(z.mix) or lsrc > q.long_loop * rate or (strict_tone(z) and lsrc*R/rate > 4095))')
    source = source.replace('if MORPH and synth and self.compact_tones:', 'if MORPH and synth and (self.compact_tones or (strict_tone(z) and lsrc*R/rate > 4095)):')
    source = source.replace('cap = max(rate * 1.01, R * 1.35)', 'cap = max(rate * 1.01, R * (2.05 if strict_tone(z) else 1.35))')
    source = source.replace('if z.native else (1, 2, 4, 8, 16)', 'if z.native or strict_tone(z) else (1, 2, 4, 8, 16)')
    source = source.replace('if Rp > cap or Rp * s_max > 3.2 * q.max_rate:',
                            'if Rp > cap or (not strict_tone(z) and Rp * s_max > 3.2 * q.max_rate):')
    source = source.replace('if Rp < R * 0.97:', 'if Rp < R * (1.0 if strict_tone(z) else 0.97):')
    source = source.replace('        _, m, c, Rp = best or below',
                            "        if strict_tone(z) and best is None:\n            raise ValueError(('no strict tone loop', z.name, R))\n        _, m, c, Rp = best or below")
    if ALL_L:
        # The DOC plays all N bytes of a table per cycle:
        # a loop is 256 m samples, the c source loops spread over exactly 256 m, no repeated sample.
        source = replace_once(source, 'Rp = (256.0 * m - 1) * rate / (c * lsrc)', 'Rp = (256.0 * m) * rate / (c * lsrc)')
        source = replace_once(source, 'L = 256 * m - 1', 'L = 256 * m')
        source = replace_once(source, 'L = q.noise_loop\n', 'L = q.noise_loop + 1\n')
        source = replace_once(source, 'lt.append(lt[0])', 'pass')
        source = replace_once(source, 'z.loop_len = L + 1', 'z.loop_len = L')
    exec(compile(source, 'Wolf whole-period strict melodic loops', 'exec'), mussc.__dict__)
    mussc.ScSong.build_looped = mussc.build_looped
    if ALL_L:
        # moving-waveform families and native frames follow the same period
        for name, pairs in (('native_frames', [('N=L+1', 'N=L')]),
                            ('add_morphs', [('loop.append(loop[0])', 'pass'),
                                            ('v.size = v.loop_len = L+1', 'v.size = v.loop_len = L'),
                                            ('v.table = bytes(L+1)', 'v.table = bytes(L)')])):
            text = textwrap.dedent(function_source(getattr(mussc.ScSong, name)))
            for a, b in pairs:
                text = replace_once(text, a, b)
            exec(compile(text, 'Wolf full N-byte loop ' + name, 'exec'), mussc.__dict__)
            setattr(mussc.ScSong, name, getattr(mussc, name))

    mussc.ScSong.exact_main = exact_main
    # Preserve the parent's period, rate, phase and table size in every
    # filtered dictionary state so filtering cannot defeat the rate floor.
    import mussmooth
    smooth = textwrap.dedent(function_source(mussmooth.install))
    smooth = smooth.replace('newrate=255*f0/cycles', 'cycles=nc; loop_size=%s; newrate=Rp' % ('L' if ALL_L else 'L+1'))
    smooth = smooth.replace('z.loop_len=256', 'z.loop_len=loop_size')
    smooth = smooth.replace('H=min(H,126//cycles)', 'H=min(H,(L//2-1)//cycles)')
    smooth = smooth.replace('bytes(256)', 'bytes(loop_size)')
    smooth = smooth.replace('1+budget-(255-owner.low)', '1+(budget-(255-owner.low))//(loop_size//256)')
    smooth = smooth.replace('i/255', 'i/L').replace('range(255)', 'range(L)')
    if ALL_L:
        smooth = replace_once(smooth, 'nc if L == 255 else 1', 'nc if L == 256 else 1')
        smooth = replace_once(smooth, 'return x+[x[0]]', 'return x')
    smooth = smooth.replace('i%255', 'i%L').replace('len(att)%255', 'len(att)%L')
    smooth = smooth.replace('v.size=v.loop_len=256', 'v.size=v.loop_len=loop_size')
    # No second resampling of the already corrected attack at an equal rate.
    smooth = smooth.replace('att=musdsp.resample(z.float_tab,Rp,newrate,taps=12)', 'att=list(z.float_tab)')
    exec(compile(smooth,'Wolf strict-rate filter families','exec'),mussmooth.__dict__)
    # One-shot tones need the same most-played-key attack correction.
    source=textwrap.dedent(function_source(mussc.ScSong.build_oneshot))
    source=source.replace('    self.finish(z, tab, None, R)', '    if strict_tone(z):\n        self.exact_main(z, tab, y, rate, R, max(0,len(tab)-fade))\n    self.finish(z, tab, None, R)')
    exec(compile(source,'Wolf exact one-shot tone attack','exec'),mussc.__dict__)
    mussc.ScSong.build_oneshot=mussc.build_oneshot


def exact_main(self, z, tab, x, rate, R, A, factor=1.):
    """Own output samples for the most common initial pitch, until it moves."""
    from collections import Counter
    import musdsp
    import mussc
    ns = [n for n in z.notes if n.half == 0]
    c = Counter(int(round(512 * R * n.freqs[0][1] / mussc.DOC_RATE)) for n in ns)
    if not c: return
    fc, count = c.most_common(1)[0]
    if fc < 512: return
    chosen = [n for n in ns if int(round(512 * R * n.freqs[0][1] / mussc.DOC_RATE)) == fc]
    # Bytes after the first actual frequency change cannot be exact for the
    # initial accumulator trajectory. Leave those normally resampled.
    seconds = min(((t-n.on)/140 for n in chosen for t,sp in n.freqs[1:]
                   if int(round(512 * R * sp / mussc.DOC_RATE)) != fc), default=1e9)
    N = min((A << 9)//fc, round(seconds*mussc.DOC_RATE))
    sp = fc*mussc.DOC_RATE/(512*R)
    source=x[:int(N*rate*sp/mussc.DOC_RATE)+64]
    if factor!=1.:source=[v*factor for v in source]
    y = musdsp.resample(source, rate, mussc.DOC_RATE/sp, taps=24)
    for i in range(min(N,len(y))):
        # The DOC adds frequency before fetching the waveform byte.
        p=((i+1)*fc)>>9
        if p < min(A,len(tab)): tab[p]=y[i]
    z.exact_fc_main=fc
    z.exact_attack_samples=min(N,len(y))
    z.exact_attack_keys=sorted({n.key for n in chosen})
