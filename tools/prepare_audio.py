"""Track selected prepared-music inputs without rerendering or touching them."""
import json
import hashlib
import os
from pathlib import Path

from music_pack import MusicPack, ROOT, selected_pack
from wolfdata import PROFILE
from write_generated import write_generated


def main():
    from audio_provenance import validate
    receipt = validate(selected_pack())
    report = MusicPack(selected_pack(), PROFILE).inspect()
    report['audio_build_identity'] = receipt['identity']
    preserved = os.environ.get('WOLF_EFFECT_SAMPLES')
    if preserved:
        folder = Path(preserved).resolve()
        manifest = folder/'samples.toml'
        if not manifest.is_file():
            raise ValueError('Missing preserved effect manifest: '+str(manifest))
        report['preserved_effects'] = dict(folder=str(folder), files={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [manifest, *sorted(folder.glob('*.u8'))]})
    generated = ROOT / 'build/gen'
    generated.mkdir(parents=True, exist_ok=True)
    write_generated(generated / 'audio-input.json', json.dumps(report, indent=2) + '\n')
    floor_ids = [PROFILE.music_names.index(name) for name in PROFILE.document['audio']['floor_songs']]
    write_generated(generated / 'music_floors.inc', '              .word ' + ','.join(map(str, floor_ids)) + '\n')


if __name__ == '__main__':
    main()
