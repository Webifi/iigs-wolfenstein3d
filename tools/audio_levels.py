"""Source-referred level measurements at one fixed DOC output scale."""
import hashlib
import json
import math
from pathlib import Path

from game_profile import read_toml

POLICY = Path(__file__).resolve().parents[1]/'profiles/audio/source-levels.toml'


def conversion_level_mode(cfg, preserved=False):
    """Synthesis follows the source; offline rebuilds retain their saved policy."""
    mode = cfg.get('level_mode', 'legacy' if preserved else 'source')
    if mode not in ('source', 'legacy'):
        raise ValueError('doc.level_mode must be source or legacy')
    if not preserved:
        if mode != 'source':
            raise ValueError('full synthesis requires doc.level_mode = "source"; '
                             'legacy levels belong to historical offline packages')
        if cfg.get('capture_source') != 'instrument-track':
            raise ValueError('source-level synthesis requires complete instrument-track references')
    return mode


def source_reference_receipt(sampler):
    """Bind unchanged renderer output to the selected full performance and parts."""
    from audio_recipes import debug_midi, sha
    rows = []
    for channel in [None] + sorted({n['channel'] for n in sampler.notes}):
        stem = 'full' if channel is None else f'channel-{channel:02}'
        wav = sampler.out/'reference'/(stem+'.wav')
        receipt = wav.with_suffix('.json')
        midi = wav.with_suffix('.mid')
        if not all(p.is_file() for p in (wav, receipt, midi)):
            raise ValueError('missing complete Roland reference and render receipt: '+stem)
        saved = json.loads(receipt.read_text())
        requested = sha(debug_midi(sampler.data, sampler.doc, channel, None))
        expected = dict(wav_sha256=sha(wav.read_bytes()), midi_sha256=sha(midi.read_bytes()),
                        renderer_sha256=sampler.renderer_sha256, rom_inputs=sampler.rom_inputs,
                        romset=sampler.romset, render_policy=sampler.doc['render'])
        if (any(saved.get(k) != v for k, v in expected.items()) or
                saved.get('render_requested_midi_sha256', saved.get('midi_sha256')) != requested):
            raise ValueError('Roland reference differs from the selected source or renderer: '+stem)
        rows.append(dict(file=wav.relative_to(sampler.out).as_posix(),
                         receipt_sha256=sha(receipt.read_bytes()),
                         requested_midi_sha256=requested, **expected))
    return dict(format=1, post_render_gain=1, normalization=False,
                selected_midi_sha256=sha(sampler.data), references=rows)


def source_level_policy(path=POLICY):
    doc=read_toml(path)
    if doc.keys()!={'format','music_volume','system_volume','route','oscillator_scale'}:
        raise ValueError('unknown or missing source-level policy fields')
    if (doc['format'],doc['music_volume'],doc['system_volume'],doc['route'])!=(1,15,15,'stock-mono'):
        raise ValueError('source-level policy requires maximum-volume stock mono output')
    scale=doc['oscillator_scale']
    if type(scale) not in (int,float) or not math.isfinite(scale) or not 0<scale<=1:
        raise ValueError('invalid fixed DOC oscillator scale')
    return dict(doc,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                physical_hardware_calibration=False)


def source_level_error(model_to_reference_db, policy):
    # compare_solos measures the average of the two unscaled model routes.
    # The mono device sums them, so account for that fixed factor of two.
    return model_to_reference_db+20*math.log10(2*policy['oscillator_scale'])


def adjust_track_levels(tracks, levels):
    """Apply static calibration after envelope and pan quantization.

    Retain the envelope's existing steps and cadence. A constant part gain
    uses the player's finer 1/8-octave exponent, not the envelope's 3 dB
    grid. Explicit silence stays silent.
    """
    for voice in tracks:
        for on, end, note, frequency, values, step in voice:
            key=f'k{note.key:02}' if note.ch==9 else f'ch{note.ch+1:02}'
            offset=round(-levels.get(key,0.)/(20*math.log10(2)/8))
            for i,value in enumerate(values):
                if type(value) is not int or value==127:
                    continue
                adjusted=value+offset
                if adjusted<0:
                    raise ValueError('source level exceeds exponent range for '+key)
                values[i]=min(127,adjusted)
