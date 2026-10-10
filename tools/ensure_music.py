"""Rebuild Makefile music when any recipe, input, compiler or output is stale."""
import argparse
from pathlib import Path
import subprocess
import sys

from audio_provenance import validate
from game_profile import profile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',required=True)
    p.add_argument('--data',required=True,type=Path)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--import-only',action='store_true')
    a=p.parse_args()
    try:
        receipt=validate(a.out)
        if not a.import_only:
            required={str(a.source.resolve()),str(a.data.resolve()),str(profile(a.profile).path.resolve())}
            if receipt['kind']!='music-pack' or not required.issubset(set(receipt['roots'])):
                raise ValueError('Music was built from a different source/profile')
        return
    except (OSError,ValueError,KeyError) as error:
        if a.import_only:p.exit(2,str(error)+'\n')
    subprocess.run([sys.executable,str(Path(__file__).with_name('audio_compile.py')),'music-pack',str(a.source),
                    '--profile',a.profile,'--data',str(a.data),'--out',str(a.out),'--require-identical'],check=True)
    validate(a.out)


if __name__=='__main__':main()
