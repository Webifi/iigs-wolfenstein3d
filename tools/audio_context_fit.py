"""Allocate captured velocity variants and waveform detail within DOC RAM.

Half-dB reuse identifies equivalent captures. When they cannot all fit, auto-fit
also considers measured approximations within the same program, bank and root.
Those losses are recorded separately; they are never labelled equivalent audio.
Explicit per-sample settings protect a capture from this second kind of sharing.
"""
from collections import Counter, defaultdict
import copy
import math
import json
import sys

from audio_fit import DOC_RATE, curve_value, match_response, comparable_sources, comparison_holds, aligned_releases
from audio_timbre import BankAllocationError, choose_bank, spectrum, difference


def weight(zone, per_channel):
    return sum(1/per_channel[n.ch] for n in zone.notes if n.half == 0)


def minimum_pages(zone):
    """A lower bound, used only to skip allocations which cannot possibly fit."""
    rate, source = zone.measured_source
    root = zone.capture['key']
    speeds = [2**((n.key-root+bend)/12) for n in zone.notes for _,bend in n.bends]
    lo, hi = min(speeds), max(speeds)
    if zone.drum or zone.r.mode not in (1,3) or zone.notes[0].preset[1] in (118,127):
        floor = 6000 if zone.drum or zone.notes[0].preset[1] in (118,127) else DOC_RATE*(513/512)/lo
        size = 1 << math.ceil(math.log2(max(256, len(source)/rate*floor+1)))
        return size//256
    floor = DOC_RATE*(513/512)/lo
    count = round(.02*lo*floor)+min(128,max(8,round(.004*floor)))+math.ceil(floor*hi/140*1.12)+32
    return (1 << math.ceil(math.log2(max(256,count))))//256+1


def protected(sampler, zone):
    return any(any(n.ch+1 == row['channel'] and row.get('key',-1) in (-1,n.key)
                   for n in zone.notes) for row in sampler.overrides)


def adequate_gain_source(zone, metrics):
    # Amplification cannot recover precision absent from the 16-bit recording.
    # A signed 8-bit DOC table needs at least 127 source counts to retain its
    # own amplitude resolution. Louder captures remain candidates; the measured
    # timbre/envelope loss decides whether they are suitable for sharing.
    return metrics['gain_db'] <= .5 or max(map(abs,zone.measured_source[1]),default=0)*32768 >= 127


def relation(sampler, main, other):
    sr, ref, values = comparable_sources(main,other)
    key = ('approximate', main.capture['capture_sha256'], len(ref),
           other.capture['capture_sha256'], len(values))
    if key not in sampler.compare_cache:
        holds=comparison_holds(main,other)
        fundamental = 440*2**((main.capture['key']-69)/12)
        metrics = match_response(ref, values, sr, allow_approximation=True, holds=holds,
                                 fundamental=fundamental)
        if holds is not None:
            ref,values=aligned_releases(ref,values,sr,holds,max(2,math.ceil(.02*fundamental))/fundamental)
        # A broad band can contain several different harmonics. Compare those
        # too, weighting windows by audible energy rather than quiet-tail time.
        width = 2048
        end = min(len(values),len(ref),round(sr))
        starts = sorted(set(round(i*max(0,end-width)/11) for i in range(12)))
        windows = []
        for at in starts:
            a,b = values[at:at+width],ref[at:at+width]
            power = sum(v*v for v in a)
            if power:
                loss = difference(spectrum(a,sr,fundamental),spectrum(b,sr,fundamental))['distance']
                windows.append((power,loss))
        spectral = sum(w*e for w,e in windows)/max(1e-30,sum(w for w,_ in windows))
        metrics['allocation_loss'] = max(spectral,metrics['after']['worst_db'])
        metrics['allocation_loss_method'] = 'energy-weighted harmonic and third-octave distance, with corrected-envelope error'
        sampler.compare_cache[key] = metrics
    return sampler.compare_cache[key]


def nearest_pair(sampler, zones, per_channel):
    families = defaultdict(list)
    for z in zones:
        if protected(sampler,z):
            continue
        c = z.capture
        articulation=bool(getattr(z,'capture_baked_articulation',False))
        families[z.drum,z.notes[0].preset,tuple(c.get('bank',(0,0))),c['key'],articulation].append(z)
    choices = []
    for family in families.values():
        # Adjacent played velocities provide a bounded agglomerative search.
        # The response measurement decides the merge, including GS controls;
        # equal velocity alone never means equal sound.
        ordered = sorted(family, key=lambda z:(z.capture['velocity'], z.capture['capture_sha256']))
        for left,right in zip(ordered,ordered[1:]):
            for main,other in ((left,right),(right,left)):
                # The retained recording must include the other recording's
                # complete audible interval, including a short note's release.
                if len(main.measured_source[1])/main.measured_source[0] < len(other.measured_source[1])/other.measured_source[0]:
                    continue
                holds=comparison_holds(main,other)
                if holds is not None and holds[0]+.001<holds[1]:
                    continue
                metrics = relation(sampler,main,other)
                if not adequate_gain_source(main,metrics):
                    continue
                error = metrics['allocation_loss']
                cost = error*weight(other,per_channel)
                choices.append((cost/max(1,minimum_pages(other)),cost,main,other,metrics))
    return min(choices,key=lambda row:(row[0],row[1],row[2].capture['capture_sha256'])) if choices else None


def merge(main, other, metrics, cost):
    z = copy.copy(main)
    z.notes = list(main.notes)+list(other.notes)
    z.capture = copy.deepcopy(main.capture)
    z.context_loss = getattr(main,'context_loss',0.)+getattr(other,'context_loss',0.)+cost
    main_hold,other_hold = main.capture_input[4],other.capture_input[4]
    if getattr(main,'capture_baked_articulation',False):
        # These curves include the release at its original onset-relative
        # time. Sharing a longer recorded articulation must not shift it.
        main_hold=other_hold=None
    correction = metrics.get('curve_db',[])
    for n in other.notes:
        n.capture_level_db = getattr(n,'capture_level_db',0.)+metrics['gain_db']
        prior = getattr(n,'capture_response_curve',[])
        if correction or prior:
            count = max(len(correction),len(prior))
            curve = []
            for i in range(count):
                age = i*.01
                prior_age = (other_hold+age-main_hold if main_hold is not None and
                             other_hold is not None and age>main_hold else
                             min(age,other_hold) if other_hold is not None else age)
                curve.append((curve_value(correction,age) if correction else 0.)+
                             (curve_value(prior,prior_age) if prior else 0.))
            n.capture_response_curve = curve
            n.capture_response_hold = main_hold
    for n in z.notes:
        n.z = z
    z.capture.setdefault('shared_variants',[]).append(dict(
        channel=other.notes[0].ch+1,velocity=other.capture['velocity'],
        gain_db=metrics['gain_db'],metrics=metrics,
        source_capture_sha256=other.capture['capture_sha256'],
        sharing='measured approximation selected by the bank allocator',needs_audition=True))
    z.capture['shared_variants'].extend(copy.deepcopy(other.capture.get('shared_variants',[])))
    return z


def fit_contexts(sampler, owner, budget):
    per_channel = Counter(n.ch for n in owner.notes if n.half == 0)
    original = owner.q
    zones = list(owner.zones)
    candidates = {}
    candidate_owners = {}
    merges = []
    initial = len(zones)
    best = None
    direct=all(hasattr(n,'capture_reference') for n in owner.notes)

    def combine():
        pair = nearest_pair(sampler,zones,per_channel)
        if pair is None:
            return False
        _,cost,main,other,metrics = pair
        joined = merge(main,other,metrics,cost)
        at = min(zones.index(main),zones.index(other))
        zones.remove(main);zones.remove(other);zones.insert(at,joined)
        merges.append(dict(program=joined.capture['program'],key=joined.capture['key'],
            retained_velocity=main.capture['velocity'],shared_velocity=other.capture['velocity'],
            retained_hold=main.capture_input[4],shared_hold=other.capture_input[4],
            measured_loss=metrics['allocation_loss'],weighted_loss=cost))
        print(f'{owner.name}: sharing program {joined.capture["program"]}, key {joined.capture["key"]}, '
              f'velocities {main.capture["velocity"]}/{other.capture["velocity"]}; '
              f'measured response distance {metrics["allocation_loss"]:.3f}',file=sys.stderr,flush=True)
        return True

    # Avoid expensive loop searches when even their mathematical lower bound
    # exceeds RAM, or when the player cannot address this many descriptors.
    while len(zones)>64 or sum(minimum_pages(z) for z in zones)>budget:
        if not combine():
            if hasattr(sampler,'out'):
                (sampler.out/'allocation-failure.json').write_text(json.dumps([
                    dict(program=z.capture['program'],key=z.capture['key'],velocity=z.capture['velocity'],
                         seconds=len(z.measured_source[1])/z.measured_source[0],minimum_pages=minimum_pages(z),
                         notes=len(z.notes),peak=max(map(abs,z.measured_source[1]))) for z in zones],indent=2)+'\n')
            raise BankAllocationError(sum(minimum_pages(z) for z in zones),budget)
    while True:
        if not direct and best is not None and sum(getattr(z,'context_loss',0.) for z in zones) >= best[0]:
            break
        owner.zones = zones
        pending=[z for z in zones if id(z) not in candidates]
        def fit_one(z):
            # Quality and candidate selection are mutable per-instrument state.
            local_owner=copy.copy(owner);local_sampler=copy.copy(sampler)
            local_owner.capture_factory=local_sampler
            return local_sampler.fit_options(local_owner,z,original,per_channel)
        from audio_workers import map_fits
        for z,rows in zip(pending,map_fits(fit_one,pending)):
            candidate_owners[id(z)]=z
            candidates[id(z)]=rows
        choices = [candidates[id(z)] for z in zones]
        options = [[(row['pages'],row['error']) for row in rows] for rows in choices]
        minimum = sum(min(p for p,_ in rows) for rows in options)
        for available in range(budget,minimum-1,-1):
            selected = choose_bank(options,available)
            for z,rows,index in zip(zones,choices,selected):
                z.__dict__.clear();z.__dict__.update(rows[index]['state'])
            owner.layout()
            if owner.low >= 64:
                report = dict(
                    method=('all original played variants against each final representation' if direct else
                            'joint measured context and waveform loss along a nearest-response merge search'),
                    budget_pages=budget,used_pages=244-owner.low,
                    source_contexts=initial,stored_contexts=len(zones),context_merges=list(merges),
                    options=[[dict(pages=row['pages'],weighted_error=row['error']) for row in rows] for rows in choices],
                    selected=selected,listening_accepted=False)
                score = sum(rows[index]['error'] for rows,index in zip(choices,selected))
                if not direct:score+=sum(getattr(z,'context_loss',0.) for z in zones)
                report['combined_measured_loss'] = score
                if best is None or score < best[0]:
                    best = (score,[(z,dict(z.__dict__)) for z in zones],
                            [(n,dict(n.__dict__)) for n in owner.notes],report)
                break
        if not combine():
            if best is None:
                raise BankAllocationError(minimum,budget)
            break
    _,states,notes,report = best
    owner.zones = [z for z,_ in states]
    for z,state in states:
        z.__dict__.clear();z.__dict__.update(state)
    for n,state in notes:
        n.__dict__.clear();n.__dict__.update(state)
    owner.layout()
    owner.fit_allocation = report
