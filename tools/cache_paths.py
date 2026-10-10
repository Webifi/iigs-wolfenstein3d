"""Rebind path-bearing build metadata when a cached result moves stages.

Only the audio compiler's JSON reports contain build/source absolute paths.
Binary assets are copied verbatim. Receipts bind the relocated reports again,
using the same hashing and JSON format as audio_provenance.complete.
"""
import hashlib
import json
from pathlib import Path


def metadata(path):
    path = str(path).replace('\\', '/')
    return (path.endswith(('.json', '/build.log', '/compiler.log')) and '/build/audio/music/' in path
            or path.endswith('/build/gen/audio-input.json'))


def relocate(outputs, old, new):
    pairs = [(v + '/', new[k] + '/') for k, v in old.items() if k in new and v != new[k]]
    if not pairs:
        return {}
    changed = {}
    receipts = []
    for name, state in outputs.items():
        path = Path(name)
        if state in (None, 'dir', 'other') or not metadata(name):
            continue
        raw = path.read_bytes()
        data = raw
        for before, after in pairs:
            data = data.replace(before.encode(), after.encode())
            data = data.replace((before[:-1] + '"').encode(), (after[:-1] + '"').encode())
        if str(path).endswith('/build/gen/audio-input.json'):
            doc = json.loads(data)
            if 'audio_build_identity' in doc:
                receipt = path.parent.parent / 'audio/music/audio-build.json'
                doc['audio_build_identity'] = json.loads(receipt.read_text())['identity']
                data = (json.dumps(doc, indent=2) + '\n').encode()
        if data != raw:
            path.write_bytes(data)
            changed[name] = hashlib.sha256(data).hexdigest()
        if path.name == 'audio-build.json':
            receipts.append(path)
    for path in sorted(receipts, key=lambda p: -len(p.parts)):
        doc = json.loads(path.read_text())
        # Inputs themselves are unchanged. Their names moved with the source;
        # outputs may be reports containing those names.
        doc['outputs'] = {name: hashlib.sha256((path.parent / name).read_bytes()).hexdigest()
                          for name in doc['outputs']}
        prior = doc.pop('identity', None)
        doc['identity'] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
        data = (json.dumps(doc, indent=2) + '\n').encode()
        path.write_bytes(data)
        changed[str(path)] = hashlib.sha256(data).hexdigest()
        log = path.parent / 'build.log'
        if str(log) in outputs and prior:
            data = log.read_bytes().replace(prior.encode(), doc['identity'].encode())
            log.write_bytes(data)
            changed[str(log)] = hashlib.sha256(data).hexdigest()
    return changed
