"""DOC register-stream preview and comparisons with the emulator's solo tracks."""
import array
from collections import defaultdict
import json
import math
from pathlib import Path
import hashlib
import struct
import sys

from audio_fit import BANDS, DOC_RATE, band_energy


def write_model_wav(path, rate, channels):
    """Keep the model's fixed scale, including sums above PCM full scale."""
    if not channels or len({len(c) for c in channels}) != 1:
        raise ValueError('mismatched model WAV channels')
    values = array.array('f', (v for frame in zip(*channels) for v in frame))
    if not all(math.isfinite(v) for v in values):
        raise ValueError('non-finite model output')
    if sys.byteorder != 'little':
        values.byteswap()
    payload = values.tobytes()
    count = len(channels)
    rate = round(rate)
    # IEEE float avoids both clipping and a song-dependent preview gain.
    header = struct.pack('<4sI4s4sIHHIIHH4sII4sI',
        b'RIFF', 48+len(payload), b'WAVE', b'fmt ', 16, 3, count,
        rate, rate*count*4, count*4, 32, b'fact', 4, len(channels[0]),
        b'data', len(payload))
    Path(path).write_bytes(header+payload)


def raw_levels(channels):
    """Measure stored amplitudes without fitting or adjusting either side."""
    values = (v for channel in channels for v in channel)
    power = peak = 0.
    count = over = 0
    for value in values:
        power += value*value
        peak = max(peak, abs(value))
        count += 1
        over += abs(value) > 1.
    rms = math.sqrt(power/max(1, count))
    return dict(peak=peak, rms=rms, peak_dbfs=20*math.log10(peak) if peak else None,
                rms_dbfs=20*math.log10(rms) if rms else None,
                samples_above_full_scale=over, samples=count)


def render_parts(folder, info):
    """Render source-timed register writes; this is not a native IRQ benchmark."""
    import audio_preview_native as native
    fast = native.library() is not None
    wave_ram = bytearray(65536)
    payload = (folder/'waves.bin').read_bytes()
    base = info['doc_base']
    wave_ram[base:base+len(payload)] = payload
    events = defaultdict(list)
    tags = set()
    for line in (folder/'stereo.txt').read_text().splitlines():
        kind,tick,a,b = line.split()
        events[round(int(tick)*DOC_RATE/700)].append((kind,int(a),int(b)))
        if kind=='T':
            tags.add(int(b))
    frames = math.ceil(info['seconds']*DOC_RATE)
    result = {tag:[array.array('f',[0.])*frames,array.array('f',[0.])*frames] for tag in tags}
    oscillators = [dict(fc=0,volume=0,page=0,size=256,resolution=0,control=1,phase=0,tag=0) for _ in range(32)]
    previous = 0
    for end in sorted(set(events)|{frames}):
        end = min(end,frames)
        for osc in oscillators[4:28]:
            if osc['control']&1 or osc['tag'] not in result:
                continue
            shift = 9 + osc['resolution'] - (osc['size'].bit_length()-9)
            size,phase = osc['size'],osc['phase']
            period = size<<shift
            table = osc['page'] & ~(size-1)
            channel = 0 if osc['control']&16 else 1
            output = result[osc['tag']][channel]
            gain = osc['volume']/(255*127)
            if fast:
                osc['phase'] = native.part(wave_ram, output, previous, end, osc, shift, table, gain)
                continue
            for i in range(previous,end):
                phase += osc['fc']
                at = (phase>>shift)&(size-1)
                byte = wave_ram[table+at]
                if not byte or phase>=period and osc['control']&6:
                    osc['control'] |= 1
                    phase = 0
                    break
                if phase>=period:
                    phase %= period
                output[i] += (byte-128)*gain
            osc['phase'] = phase
        for kind,a,b in events.get(end,[]):
            if kind=='T':
                oscillators[a]['tag'] = b
                continue
            o = oscillators[a&31]
            group = a&0xe0
            if group==0:o['fc']=(o['fc']&0xff00)|b
            elif group==0x20:o['fc']=(o['fc']&255)|(b<<8)
            elif group==0x40:o['volume']=b
            elif group==0x80:o['page']=b*256
            elif group==0xa0:
                if b&3==3:o['phase']=0
                o['control']=b
            elif group==0xc0:
                o['size']=256<<((b>>3)&7)
                o['resolution']=b&7
        previous = end
        if end==frames:
            break
    return result


def compare_solos(folder, info, write_diagnostics=False, source_levels=False):
    from audio_compile import wav_read
    from audio_fit import compare
    from musdsp import rms
    from audio_resample import resample
    from audio_levels import source_level_policy, source_level_error
    level_policy=source_level_policy() if source_levels else None
    full_reference = folder/'reference/full.wav'
    _, full_ref = wav_read(full_reference)
    # Earlier builds used listening-looking names for gain-adjusted previews.
    # Retain them as legacy diagnostics so rebuilding cannot leave them beside
    # new reports looking like current native recordings.
    legacy = [p for p in folder.glob('doc-channel-*.wav')]
    if (folder/'doc-full.wav').exists():
        legacy.append(folder/'doc-full.wav')
    if legacy:
        archive = folder/'model-diagnostics/legacy'
        archive.mkdir(parents=True, exist_ok=True)
        old_report = folder/'solo-comparison.json'
        if old_report.exists():
            data = old_report.read_bytes()
            (archive/('report-'+hashlib.sha256(data).hexdigest()+'.json')).write_bytes(data)
        for path in legacy:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.rename(archive/(path.stem+'-'+digest+'.wav'))
    parts = render_parts(folder,info)
    channels = defaultdict(list)
    for tag,pair in parts.items():
        channels[10 if tag>=128 else tag].append(pair)
    count=math.ceil(info['seconds']*DOC_RATE)
    mixed=[[0.]*count,[0.]*count]
    rows=[]
    notes=json.loads((folder/'notes.json').read_text())
    # All model WAVs retain the same oscillator scale across parts and songs.
    # This is a diagnostic model, not the native game's output-device scale.
    for channel,pairs in sorted(channels.items()):
        reference = folder/'reference'/f'channel-{channel:02}.wav'
        if not reference.is_file():
            raise ValueError('missing Roland instrument-track reference: '+str(reference))
        rate,ref = wav_read(reference)
        reference_levels = raw_levels(ref)
        centered=[]
        original=[]
        for side in ref:
            # Use only the renderer's initial idle interval, before its first
            # note reaches the output. Individual capture receipts retain DC.
            dc=sum(side[:64])/max(1,min(64,len(side)))
            values=[v-dc for v in side[:round(info['seconds']*rate)]]
            original.append(values)
            values=resample(values,rate,DOC_RATE,taps=24)
            centered.append((values+[0.]*count)[:count])
        ref=centered
        got = [[sum(pair[side][i] for pair in pairs) for i in range(count)] for side in range(2)]
        for side in range(2):
            for i,v in enumerate(got[side]):mixed[side][i]+=v
        ref_mono = [(a+b)*.5 for a,b in zip(*ref)]
        got_mono = [(a+b)*.5 for a,b in zip(*got)]
        original_mono_rms=rms([(a+b)*.5 for a,b in zip(*original)])
        metrics=compare(ref_mono,got_mono)
        gain=-20*math.log10(max(1e-15,metrics['equal_gain']))
        def stereo_balance(pair):
            return 20*math.log10(max(1e-15,rms(pair[0]))/max(1e-15,rms(pair[1])))
        attacks=[]
        reference_rms=rms(ref_mono)
        width=round(.015*DOC_RATE)
        for note in notes:
            if note['ch']+1!=channel:continue
            start=round(note['tic']/140*DOC_RATE)
            a=rms(ref_mono[start:start+width])
            b=rms(got_mono[start:start+width])*metrics['equal_gain']
            if a>reference_rms*.03:
                attacks.append(20*math.log10(max(1e-15,b)/a))
        if write_diagnostics:
            write_model_wav(folder/f'doc-model-raw-channel-{channel:02}.wav', DOC_RATE, got)
        rows.append(dict(channel=channel,metrics=metrics,relative_level_db=gain,
                         original_mono_rms=original_mono_rms,model_mono_rms=rms(got_mono),
                         attack_15ms_worst_db=max(map(abs,attacks),default=0),
                         stereo_balance_error_db=stereo_balance(got)-stereo_balance(ref),
                         reference_pan=round(127*2/math.pi*math.atan2(rms(ref[1]),rms(ref[0]))),
                         preview_gain=1.,
                         raw_levels=dict(roland=reference_levels, doc_model=raw_levels(got))))
    if rows:
        common = sorted(r['relative_level_db'] for r in rows)[len(rows)//2]
        for row in rows:
            if source_levels:
                # Resampling can remove substantial cymbal energy. Measure
                # source level before that bandwidth reduction; the resampled
                # copy belongs only to the spectral/envelope diagnostics.
                absolute_ratio=20*math.log10(max(1e-15,row['model_mono_rms'])/max(1e-15,row['original_mono_rms']))
                row['source_level_error_db']=source_level_error(absolute_ratio,level_policy)
                row['level_correction_db']=-row['source_level_error_db']
            else:
                row['level_correction_db']=common-row['relative_level_db']
            row['needs_audition']=True
    diagnostic = folder/'doc-model-raw-full.wav'
    if write_diagnostics:
        write_model_wav(diagnostic, DOC_RATE, mixed)
    report = dict(model='DOC full N-byte tables at source event times',
                  native_timing_verified=False,bands_hz=BANDS,parts=rows,listening_accepted=False,
                  output=dict(format='IEEE float32', gain=1., normalized=False, limited=False,
                              diagnostic_wavs_written=write_diagnostics,
                              scale='one oscillator: (sample-128)*volume/(127*255)',
                              music_volume=15, system_volume=None, native_game_capture=False,
                              source_level_acceptance=False),
                  raw_levels=dict(roland=raw_levels(full_ref), doc_model=raw_levels(mixed)),
                  files={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in [full_reference, folder/'stored.bin', folder/'unit.bin',
                                   folder/'waves.bin', folder/'stereo.txt']+
                                  ([diagnostic] if write_diagnostics else [])},
                  raw_level_limitations='Different renderer/device scales; not an in-game volume comparison. '
                    'Model sums above 1 are retained and can clip a unity-gain audio output. '
                    'Roland reference files are unchanged. The native game must be captured separately.',
                  level_policy=level_policy,
                  reference_comparison='equal overall RMS for shape; original relative levels reported separately')
    (folder/'solo-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Suggested measured level corrections, in dB.',
           '# Audition reference/ and doc-channel WAVs before copying into the recipe.',
           ('# These compensate measured source-level error at the fixed DOC output scale.' if source_levels
            else '# These are relative to one common song gain, not per-note normalization.'),
           '[doc.levels]']
    for row in rows:lines.append(f'ch{row["channel"]:02} = {row["level_correction_db"]:.4f}')
    (folder/'suggested-levels.toml').write_text('\n'.join(lines)+'\n')
    return report
