"""Write a standalone, file://-compatible listening page and unchanged WAVs."""
import ctypes
import array
import base64
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
from urllib.parse import quote
import wave


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_wav(source, target):
    source, target = Path(source), Path(target)
    # APFS clones retain independent file contents without another audio copy.
    if sys.platform == 'darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.clonefile(bytes(source), bytes(target), 0) == 0:
            return
    shutil.copyfile(source, target)


_wav_info = {}


def recording_info(source, identity):
    # Repeated table exports reuse measurements only for identical WAV bytes.
    if identity not in _wav_info:
        with wave.open(str(source), 'rb') as wav:
            info = dict(rate=wav.getframerate(), channels=wav.getnchannels(), frames=wav.getnframes())
            if wav.getsampwidth() != 2:
                raise ValueError('Expected 16-bit PCM comparison WAV: '+str(source))
            pcm = array.array('h', wav.readframes(wav.getnframes()))
            if sys.byteorder != 'little':
                pcm.byteswap()
            peak = max(map(abs, pcm), default=0)/32768
            rms = math.sqrt(sum(v*v for v in pcm)/max(1,len(pcm)))/32768
            info.update(peak_dbfs=20*math.log10(peak or 1e-9), rms_dbfs=20*math.log10(rms or 1e-9))
        _wav_info[identity] = info
    return _wav_info[identity]


def export(out, title, items):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    audio = out/'audio'
    audio.mkdir(exist_ok=True)
    catalog = dict(format=1, title=title, gain=1, normalization=False, items=[])
    checked_bindings = set()
    from doc_preview import BindingChecks
    doc_checks = BindingChecks()
    audit = ['Recorded WAV levels; player gain 1.0 (0 dB).',
             'No normalization, matching, compression or limiting.', '']
    for row_index, row in enumerate(items):
        saved = dict(label=row['label'], note=row['note'], default_version=row.get('default_version', 0), versions=[])
        for key in ('section','song','song_id','part','channel','effect_id','status'):
            if key in row:
                saved[key] = row[key]
        for version_index, version in enumerate(row['versions']):
            if version.get('status')=='unavailable':
                saved['versions'].append(dict(label=version['label'],kind=version['kind'],
                    status='unavailable',reason=version['reason'],provenance={}))
                continue
            source = Path(version['source']).resolve(strict=True)
            identity = digest(source)
            expected = version.get('sha256')
            if expected and identity != expected:
                raise ValueError('Comparison WAV changed: '+str(source))
            audio_info = recording_info(source, identity)
            target = audio/f'{row_index:03d}-{version_index:02d}-{identity[:12]}.wav'
            if target.exists():
                if digest(target) != identity:
                    import time
                    target.rename(target.with_name(target.name+'.stale-'+str(time.time_ns())))
                    copy_wav(source,target)
            else:
                copy_wav(source, target)
                if digest(target) != identity:
                    raise ValueError('Comparison WAV copy failed')
            provenance = dict(version.get('provenance', {}), source_file=str(source), wav_sha256=identity, **audio_info)
            binding=provenance.get('build_binding')
            if binding:
                key=json.dumps(binding,sort_keys=True)
                if key not in checked_bindings:
                    if binding.get('renderer_type')=='compiled-doc-python':
                        from doc_preview import validate_binding
                        validate_binding(binding,doc_checks)
                    else:
                        from audio_provenance import validate_binding
                        validate_binding(binding)
                    checked_bindings.add(key)
                if binding.get('renderer_type')=='compiled-doc-python':
                    provenance['build_status']='Verified compiled bank '+binding['bank_sha256'][:12]+(' · packaged image checked' if binding.get('media') else ' · audio-only build')
                else:
                    provenance['build_status']='Verified native capture for bank '+binding['bank_sha256'][:12]+' · image '+binding['disk_sha256'][:12]
            else:
                provenance['build_status']='Reference recording; not verified as installed audio for this build'
            label=version['label']
            if 'current' in label.lower():label=label.replace('Current','Recorded').replace('current','recorded')
            # Classic scripts can load beside a locally opened HTML file.
            # The payload contains the exact WAV bytes, not re-encoded audio.
            # Only the selected comparison is decoded; playback retains the
            # original player's single AudioContext clock and unity gains.
            payload = audio/(identity+'.js')
            encoded_wav = base64.b64encode(source.read_bytes()).decode('ascii')
            script = ('window.audioFileLoaded('+json.dumps(identity)+','+json.dumps(encoded_wav)+');\n').encode('ascii')
            if not payload.exists() or digest(payload) != hashlib.sha256(script).hexdigest():
                if payload.exists():
                    import time
                    payload.rename(payload.with_name(payload.name+'.stale-'+str(time.time_ns())))
                payload.write_bytes(script)
            audit.append(f"{row['label']} / {label}: RMS {audio_info['rms_dbfs']:.2f} dBFS, peak {audio_info['peak_dbfs']:.2f} dBFS; SHA256 {identity}")
            saved['versions'].append(dict(label=label, kind=version['kind'],
                file=quote(target.relative_to(out).as_posix()), payload=quote(payload.relative_to(out).as_posix()), provenance=provenance))
        catalog['items'].append(saved)
    if not catalog['items']:
        raise ValueError('No recordings to preview')
    doc_checks.verify()
    encoded = json.dumps(catalog, ensure_ascii=True).replace('<', '\\u003c')
    template = Path(__file__).with_name('audio_compare.html').read_text()
    player = Path(__file__).with_suffix('.js').read_text()
    (out/'index.html').write_text(template.replace('__AUDIO_MANIFEST__', encoded).replace('__PLAYER_SCRIPT__', player), encoding='utf-8')
    (out/'sources.json').write_text(json.dumps(catalog, indent=2)+'\n')
    (out/'volume-audit.txt').write_text('\n'.join(audit)+'\n')
    return out/'index.html'


def export_status(out,title,message,status):
    return export(out,title,[dict(label=title,note=message,status=status,versions=[])])
