"""Validate selected native-build inputs before converting game assets."""
import json

from wolfdata import ROOT, PROFILE, source_data
from write_generated import write_generated


def main():
    data = source_data()
    # Inspectors may accept additional data formats. Native generation
    # requires one of the Wolf or Spear campaign layouts handled below.
    if PROFILE.key not in ('shareware','wolf3d') and not PROFILE.spear:
        raise SystemExit('Native image generation for ' + PROFILE.key + ' is not implemented yet. '
                         'Use tools/wolf_image.py inspect to validate this profile; '
                         'this engine build currently supports Wolf3D campaigns.')
    report = data.inspect()
    report['profile_definition'] = PROFILE.document
    report['conversion_settings'] = PROFILE.conversion
    generated = ROOT / 'build/gen'
    generated.mkdir(parents=True, exist_ok=True)
    write_generated(generated / 'source-profile.json', json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
