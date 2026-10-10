"""Recheck an existing native demo log without launching MAME.

The ordinary demo checker remains exact by default. This explicit audit logs
the fields affected by shared visibility and fails all other gameplay drift.
It must accompany independent native visibility and picture validation.
"""

import argparse
import json
from pathlib import Path

from demo_check import audit_shared_visibility, oracle_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('demo', type=int, choices=range(4))
    parser.add_argument('log', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    native = []
    end = None
    with args.log.open() as stream:
        for line in stream:
            if line.startswith('STATE '):
                native.append(json.loads(line[6:]))
            elif line.startswith(('DEMOEND', 'DEMOFLOOR', 'TIMEOUT')):
                end = line.split()[0]
    result = audit_shared_visibility(native, oracle_rows(args.demo))
    result.update(log=str(args.log), demo=args.demo, end=end)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    if result['unexpected'] or end != 'DEMOEND':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
