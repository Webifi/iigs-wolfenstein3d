#!/usr/bin/env python3
"""Pack an 800K floppy set from a completed floppy-store build.

Usage: python3 tools/pack_floppies.py dist/floppy-output/wolf3d [--out DIR] [--max-disks N]

The edition folder must hold the native-build.json of a build made with
WOLF_STORE_MEDIUM=floppy. The packer reruns that build's recorded mkdisk
command in its work directory, without the hard disk outputs, with the floor
disk units, and writes DIR/disk1.po onward (default: EDITION/floppies).
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('edition', type=Path, help='output folder holding native-build.json')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--max-disks', type=int, default=8)
    args = parser.parse_args()
    report_path = args.edition.resolve() / 'native-build.json'
    report = json.loads(report_path.read_text())
    stage = Path(report['work_directory'])
    if not stage.is_dir():
        raise SystemExit(f'work directory {stage} is gone; rebuild the edition first')
    command = next((list(c) for c in report['commands'] if len(c) > 1 and c[1] == 'tools/mkdisk.py'), None)
    if command is None:
        raise SystemExit(f'{report_path} records no mkdisk command')
    for flag in ('--hd', '--scsi'):
        if flag in command:
            at = command.index(flag)
            del command[at:at + 2]
    if '--hd-only' in command:
        command.remove('--hd-only')
    out = (args.out or report_path.parent / 'floppies').resolve()
    out.mkdir(parents=True, exist_ok=True)
    command[command.index('--out') + 1] = str(out / 'disk')
    if '--disk-units' not in command:
        command += ['--disk-units', 'build/assets/episode-disk.json', '--campaign', 'build/gen/campaign.json']
    command += ['--max-disks', str(args.max_disks)]
    env = dict(os.environ,
               WOLF_PROFILE=str(stage / 'profiles/selected/profile.toml'),
               WOLF_DOS_DATA=str(stage / 'licensed-data'),
               WOLF_REFERENCE_SOURCE=str(stage / 'data/reference'),
               WOLF_FRONTEND_ROOT=str(stage))
    subprocess.run(command, cwd=stage, env=env, check=True)
    for disk in sorted(out.glob('disk*.po'), key=lambda p: int(p.stem[4:])):
        print(disk)


if __name__ == '__main__':
    main()
