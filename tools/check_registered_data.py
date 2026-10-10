"""Check all six registered episodes; use wolf_image.py for other profiles."""
import argparse
import json
from pathlib import Path
import struct
from dos_data import DosData


def inspect(folder):
    return DosData(folder, 'wolf3d').inspect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        text = json.dumps(inspect(args.directory), indent=2) + '\n'
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding='utf-8')
        else:
            print(text, end='')
    except (OSError, ValueError, IndexError, struct.error) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
