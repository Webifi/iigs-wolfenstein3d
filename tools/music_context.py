"""Musical-context features and song-held-out comparisons for mapping drafts."""
from collections import Counter
import math
import statistics
from game_profile import fields, number

REFERENCE_AUTHORITIES = ('project-arrangement', 'composer-original')


def validate_settings(settings):
    fields(settings, ('format', 'notes', 'accompaniment'), 'heuristics')
    if type(settings['format']) is not int or settings['format'] != 1:
        raise ValueError('unsupported heuristics format')
    expected = dict(notes=('median_pitch', 'pitch_span', 'distinct_pitch_fraction', 'log_note_seconds',
        'log_gap_seconds', 'mean_melodic_step', 'repeated_pitch_fraction'),
        accompaniment=('accompanying_voices', 'lowest_voice_fraction', 'highest_voice_fraction',
        'interval_above_bass', 'interval_from_ensemble', 'shared_onset_fraction',
        'harmonic_interval_fraction', 'parallel_motion_fraction'))
    for group, names in expected.items():
        fields(settings[group], names, 'heuristics.'+group)
        for key, value in settings[group].items():
            number(value, 0.001, 10000, group+'.'+key)


def features(all_notes, line):
    """Describe a part and the notes accompanying it, using the IMF score only."""
    def mean(values):
        return statistics.mean(values) if values else 0.0

    pitches = [n['key'] for n in line]
    lengths = [n['end']-n['start'] for n in line]
    gaps = [b['start']-a['start'] for a, b in zip(line, line[1:]) if b['start'] > a['start']]
    steps = [b-a for a, b in zip(pitches, pitches[1:])]
    counts, low, high, bass, relative, together, harmony, centers = [], [], [], [], [], [], [], []
    for note in line:
        other = [n for n in all_notes if n['channel'] != note['channel'] and
                 n['start'] <= note['start']+0.005 and n['end'] > note['start']]
        simultaneous = [n for n in all_notes if n['channel'] != note['channel'] and
                        abs(n['start']-note['start']) <= 0.015]
        counts.append(len(other))
        together.append(bool(simultaneous))
        if other:
            keys = [n['key'] for n in other]
            center = statistics.median(keys)
            centers.append(center)
            low.append(note['key'] <= min(keys))
            high.append(note['key'] >= max(keys))
            bass.append(note['key']-min(keys))
            relative.append(note['key']-center)
            harmony.append(mean([abs(note['key']-k) % 12 in (0, 3, 4, 7, 8, 9) for k in keys]))
        else:
            centers.append(None)
    parallel = [int((b-a)*(d-c) > 0) for a, b, c, d in zip(pitches, pitches[1:], centers, centers[1:])
                if c is not None and d is not None and a != b and c != d]
    return dict(median_pitch=statistics.median(pitches), pitch_span=max(pitches)-min(pitches),
        distinct_pitch_fraction=len(set(pitches))/len(pitches),
        log_note_seconds=math.log2(max(statistics.median(lengths), 0.001)),
        log_gap_seconds=math.log2(max(statistics.median(gaps) if gaps else 1, 0.001)),
        mean_melodic_step=mean([abs(s) for s in steps]), repeated_pitch_fraction=mean([s == 0 for s in steps]),
        accompanying_voices=mean(counts), lowest_voice_fraction=mean(low), highest_voice_fraction=mean(high),
        interval_above_bass=mean(bass), interval_from_ensemble=mean(relative),
        shared_onset_fraction=mean(together), harmonic_interval_fraction=mean(harmony),
        parallel_motion_fraction=mean(parallel))


def label(mapping):
    return tuple(mapping[k] for k in ('program', 'bank_msb', 'bank_lsb', 'drum_key', 'transpose'))


def ranked(examples, patch, context, settings, accompaniment=True):
    candidates = [e for e in examples if e['patch'] == patch]
    weighted = list(settings['notes'].items())
    if accompaniment:
        weighted += list(settings['accompaniment'].items())
    ranked_examples = []
    for example in candidates:
        distance = sum(((context[key]-example['context'][key])/scale)**2 for key, scale in weighted)
        ranked_examples.append((distance, example['song'], example['opl_channel'], example))
    return [dict(example=e, distance=d) for d, _, _, e in sorted(ranked_examples, key=lambda row: row[:3])]


def evaluate(reports, settings):
    validate_settings(settings)
    examples = [e for report in reports if report['authority'] in REFERENCE_AUTHORITIES
                for e in report.get('examples', [])]
    methods = {name: dict(predicted=0, program_matches=0, full_mapping_matches=0)
               for name in ('patch_majority', 'note_context', 'with_accompaniment')}
    cases = []
    for example in examples:
        train = [e for e in examples if e['song'] != example['song'] and e['patch'] == example['patch']]
        if not train:
            continue
        histogram = Counter(label(e['mapping']) for e in train)
        majority = sorted(histogram, key=lambda value: (-histogram[value], value))[0]
        note = ranked(train, example['patch'], example['context'], settings, False)[0]
        ensemble = ranked(train, example['patch'], example['context'], settings, True)[0]
        predictions = dict(patch_majority=majority, note_context=label(note['example']['mapping']),
                           with_accompaniment=label(ensemble['example']['mapping']))
        for method, predicted in predictions.items():
            methods[method]['predicted'] += 1
            methods[method]['program_matches'] += predicted[:3] == label(example['mapping'])[:3]
            methods[method]['full_mapping_matches'] += predicted == label(example['mapping'])
        cases.append(dict(song=example['song'], opl_channel=example['opl_channel'], patch=example['patch'],
            expected=list(label(example['mapping'])), predicted={k: list(v) for k, v in predictions.items()},
            accompaniment_reference=ensemble['example']['song'],
            accompaniment_distance=ensemble['distance']))
    return dict(reference_examples=len(examples), methods=methods, cases=cases,
                scope='exploratory leave-one-song-out; exact OPL patch; selected project and composer arrangements')
