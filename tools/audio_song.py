"""Convert one validated prepared song, without pack-wide provenance work."""
import argparse
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
import shutil
from audio_workers import permit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('recipe',type=Path)
    parser.add_argument('--preserved-samples',type=Path,required=True)
    parser.add_argument('--licensed-imf',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--require-identical',action='store_true')
    parser.add_argument('--model-diagnostics',action='store_true')
    args=parser.parse_args();args.record_sources=False
    # A cache miss is a fresh conversion, including the fitter's own receipts.
    shutil.rmtree(args.out,ignore_errors=True)
    args.out.mkdir(parents=True,exist_ok=True)
    from audio_music import music
    with permit(),(args.out/'compiler.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
        music(args)


if __name__=='__main__':main()
