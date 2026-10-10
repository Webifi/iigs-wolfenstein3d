"""Learn OPL-to-Roland choices from explicitly paired source parts.

The part correspondences are editable annotations. Pitch-sequence comparisons
check those annotations; they do not establish authorship or recover lost MIDI
controllers. Composer arrangements and project arrangements stay separate.
"""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import statistics
from music_context import features, REFERENCE_AUTHORITIES

MAPPING_FIELDS = ('program', 'bank_msb', 'bank_lsb', 'drum_key', 'transpose')


def identity(candidate):
    return tuple(candidate[k] for k in MAPPING_FIELDS)


def align(a, b, drum=False):
    if not a or not b:
        return [], dict(coverage=0.0, reason='empty part')
    if drum:
        if len(a) != len(b):
            return [], dict(coverage=0.0, reason='percussion note counts differ; pair a smaller phrase')
        pairs = list(zip(range(len(a)), range(len(b))))
        shift, competing = 0, 0
    else:
        ak, bk = [n['key'] for n in a], [n['key'] for n in b]
        # An explicitly paired, complete part can be checked note for note.
        # A chromatic run may also resemble itself shifted by one note; that
        # weaker subsequence must not invalidate a complete correspondence.
        shifts = {y-x for x, y in zip(ak, bk)} if len(ak) == len(bk) else set()
        if len(shifts) == 1 and -36 <= next(iter(shifts)) <= 36:
            shift = next(iter(shifts))
            pairs = list(zip(range(len(a)), range(len(b))))
            competing = 0
        else:
            results = []
            for shift in range(-36, 37):
                blocks = SequenceMatcher(None, [k+shift for k in ak], bk, autojunk=False).get_matching_blocks()
                pairs = [(block.a+i, block.b+i) for block in blocks for i in range(block.size)]
                results.append((len(pairs), -abs(shift), shift, pairs))
            results.sort(reverse=True)
            _, _, shift, pairs = results[0]
            competing = results[1][0]
    coverage = len(pairs)/len(a)
    if coverage < 0.90 or len(pairs) < 6 or (not drum and (len(pairs)-competing)/len(a) < 0.10):
        return [], dict(coverage=coverage, reason='pitch sequence is incomplete or ambiguous')
    # Local time ratios allow deliberate tempo differences between arrangements.
    ratios = [(b[v]['start']-b[y]['start'])/(a[u]['start']-a[x]['start'])
              for (x, y), (u, v) in zip(pairs, pairs[1:])
              if a[u]['start']-a[x]['start'] > 0.03 and b[v]['start'] > b[y]['start']]
    if not ratios:
        return [], dict(coverage=coverage, reason='insufficient onset intervals')
    ratio = statistics.median(ratios)
    consistent = sum(0.80 <= r/ratio <= 1.25 for r in ratios)/len(ratios)
    if consistent < 0.85:
        return [], dict(coverage=coverage, reason='onset sequence disagrees with the annotated part')
    return pairs, dict(coverage=coverage, transpose=shift, onset_interval_agreement=consistent,
                       median_tempo_ratio=ratio)


def compare(fm, midi, song, authority, pairings):
    observations, diagnostics, examples = [], [], []
    for part in pairings:
        a = [n for n in fm if n['channel'] == part['opl_channel'] and
             ('patch' not in part or n['patch'] == part['patch'])]
        b = [n for n in midi if n['channel'] == part['midi_channel'] and
             ('drum_key' not in part or n['key'] == part['drum_key']) and
             ('midi_program' not in part or n['program'] == part['midi_program'])]
        drum = part['midi_channel'] == 10
        if drum and 'drum_key' not in part:
            raise ValueError(song+': a percussion pair needs an explicit MIDI drum key')
        pairs, diagnostic = align(a, b, drum)
        diagnostics.append(dict(part, **diagnostic))
        if not pairs:
            continue
        grouped = defaultdict(Counter)
        samples = defaultdict(list)
        for ai, bi in pairs:
            f, m = a[ai], b[bi]
            mapping = (m['program'], m['bank'][0], m['bank'][1], m['key'] if drum else -1,
                       0 if drum else diagnostic['transpose'])
            grouped[f['patch']][mapping] += 1
            samples[f['patch'], mapping].append(f)
        for (patch, mapping), line in samples.items():
            examples.append(dict(song=song, authority=authority, patch=patch,
                opl_channel=part['opl_channel'], notes=len(line),
                mapping=dict(zip(MAPPING_FIELDS, mapping)), context=features(fm, line)))
        for patch, choices in grouped.items():
            candidates = [dict(zip(MAPPING_FIELDS, c), matched=count) for c, count in choices.most_common()]
            observations.append(dict(song=song, authority=authority, patch=patch,
                opl_channel=part['opl_channel'], midi_channel=part['midi_channel'],
                notes=sum(choices.values()), selected=candidates[0] if len(candidates) == 1 else None,
                candidates=candidates))
    return dict(song=song, authority=authority, diagnostics=diagnostics,
                observations=observations, examples=examples)


def aggregate(reports):
    by_patch = defaultdict(list)
    for report in reports:
        for observation in report['observations']:
            by_patch[observation['patch']].append(observation)
    result = []
    for patch, observations in sorted(by_patch.items()):
        project = [o for o in observations if o['authority'] == 'project-arrangement']
        original = [o for o in observations if o['authority'] == 'composer-original']
        evidence = project or original or observations
        choices = {identity(c) for o in evidence for c in o['candidates']}
        choice = next(iter(choices)) if len(choices) == 1 else None
        result.append(dict(patch=patch, mapping=dict(zip(MAPPING_FIELDS, choice)) if choice else None,
            authority='project-arrangement' if project else 'composer-original' if original else 'unverified',
            observations=observations, candidates=[dict(zip(MAPPING_FIELDS, c)) for c in sorted(choices)]))
    return result


def held_out(reports):
    """Song-level holdout: an unseen song never trains its own prediction."""
    counts = Counter(reference_parts=0, predicted_parts=0, matching_parts=0)
    for held in reports:
        if held['authority'] not in REFERENCE_AUTHORITIES:
            continue
        train = {p['patch']: p for p in aggregate([r for r in reports
            if r is not held and r['authority'] in REFERENCE_AUTHORITIES])}
        for o in held['observations']:
            if not o['selected']:
                continue
            counts['reference_parts'] += 1
            prediction = train.get(o['patch'], {}).get('mapping')
            if prediction:
                counts['predicted_parts'] += 1
                counts['matching_parts'] += identity(prediction) == identity(o['selected'])
    return dict(counts)
