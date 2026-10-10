"""Audit changed material edges in retained native/full-column comparisons.

Geometry must remain exact. Material differences may move within the existing
bounded interpolation envelope, but may not erase a previously visible strip.
The raw comparison retains every disagreement, including allowed edge shifts.
"""
import argparse
import json
from pathlib import Path


def runs(pages):
    first = 0
    for end in range(1, len(pages)+1):
        if end == len(pages) or pages[end] != pages[first]:
            yield first, end, pages[first]
            first = end


def audit(receipt, radius):
    result = dict(poses=0, old_disagreements=0, new_disagreements=0,
                  added_boundary_columns=0, corner_boundary_columns=0,
                  invalid_columns=[], lost_strips=[])
    for case in receipt['cases']:
        for row in case['rows']:
            result['poses'] += 1
            result['old_disagreements'] += len(row['old_page_disagreements'])
            result['new_disagreements'] += len(row['new_page_disagreements'])
            assert not row['new_bad'], (case['view'], row)
            added = row['introduced_page_disagreements']
            if not added:
                continue
            before, after, reference = row['details']
            pages = reference['pages']
            for col in added:
                neighbors = range(max(0, col-radius), min(len(pages), col+radius+1))
                exact_page = any(after['pages'][col] == pages[n] for n in neighbors)
                # Ordinary wall pages are the two orientations of one tile.
                # At a perpendicular corner, compare that tile identity while
                # still requiring the target column's exact geometric plane.
                corner = any(after['pages'][col]//2 == pages[n]//2
                             and (reference['planes'][col] ^ reference['planes'][n]) & 0x8000
                             and not (reference['planes'][col] | reference['planes'][n]) & 0x6000
                             for n in neighbors)
                if not exact_page and not corner:
                    result['invalid_columns'].append(dict(view=case['view'], pose=row.get('pose', row), column=col))
                else:
                    result['added_boundary_columns'] += 1
                    result['corner_boundary_columns'] += int(not exact_page and corner)
            for first, end, page in runs(pages):
                if end-first >= 3 and page in before['pages'][first:end] and page not in after['pages'][first:end]:
                    result['lost_strips'].append(dict(view=case['view'], first=first, end=end, page=page))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipts', nargs='+', type=Path)
    parser.add_argument('--columns', type=int, choices=(0, 1, 2), default=2)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    results = []
    identities = set()
    for path in args.receipts:
        data = json.loads(path.read_text())
        identities.add((data['before_sha256'], data['after_sha256']))
        results.append(dict(receipt=path.name, **audit(data, args.columns)))
    assert len(identities) == 1, 'receipts compare different executable pairs'
    before, after = identities.pop()
    args.out.write_text(json.dumps(dict(before_sha256=before, after_sha256=after,
        boundary_columns=args.columns, geometry_exact=True, cases=results), indent=2)+'\n')
    print(json.dumps(results, indent=2))
    assert all(not r['invalid_columns'] and not r['lost_strips'] for r in results)


if __name__ == '__main__':
    main()
