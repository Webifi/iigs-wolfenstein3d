"""Check that every hard-disk volume named by the boot header is present."""
import argparse
from pathlib import Path


def complete(path):
    def header(file):
        with file.open('rb') as stream:
            stream.seek(512)
            return stream.read(512)
    try:
        first = header(path)
        if len(first) != 512 or first[:7] != b'WOLFGS\x01' or not 1 <= first[7] <= 2:
            return False
        for number in range(2, first[7]+1):
            other = header(path.with_name(path.stem+str(number)+path.suffix))
            if (len(other) != 512 or other[:6] != b'WOLFGS'
                    or other[6:8] != bytes((number, first[7]))
                    or other[368:436] != first[368:436]):
                return False
        return True
    except OSError:
        return False


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('disk', type=Path)
    p.add_argument('--make', action='store_true', help='print a rebuild prerequisite when incomplete')
    args = p.parse_args()
    ok = complete(args.disk)
    if args.make:
        if not ok:
            print('force-registered-media')
    elif not ok:
        raise SystemExit('Hard-disk volume set is incomplete or mismatched')
