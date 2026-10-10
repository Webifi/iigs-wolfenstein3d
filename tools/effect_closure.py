"""Difficulty-independent sound residency from the complete map resource closure."""
from collections import Counter
from functools import lru_cache
import math
from game_profile import fields, read_toml
from map_semantics import MapSemantics
from wolfdata import ROOT, PROFILE, source_data
from wolfaudio import NAMES, AVAILABLE


@lru_cache(maxsize=1)
def floor_effects():
    doc=read_toml(ROOT/'profiles/audio'/('native-effects-spear.toml' if PROFILE.spear else 'native-effects-wolf3d.toml'))
    fields(doc,('format','common','resources','silent_prefixes'),'native effects')
    if doc['format']!=1: raise ValueError('unsupported native effect recipe')
    ids={name:i for i,name in enumerate(NAMES)}
    def validate(weights):
        for name,value in weights.items():
            if name not in ids: raise ValueError('unknown effect name: '+name)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('effect weight must be positive: '+name)
    validate(doc['common'])
    for weights in doc['resources'].values():validate(weights)
    semantics=MapSemantics(PROFILE.resource('map_semantics'))
    unknown=set(doc['resources'])-set(semantics.resources)
    if unknown:raise ValueError('unknown effect resources: '+str(sorted(unknown)))
    result=[]
    for floor,level in enumerate(source_data().maps()):
        inspected=semantics.inspect_floor(level['planes'])
        roots=Counter({r:1 for r in semantics.document['always_resources']})
        for obj in inspected['objects']:
            source=semantics.lookup[obj['plane'],obj['code']]
            if 'resource_id' in source:roots[source['resource_id']]+=obj['count']
        counts=Counter()
        for root,count in roots.items():
            for resource in semantics.closure([root]):counts[resource['resource_id']]+=count
        weight={ids[n]:v for n,v in doc['common'].items()}
        reasons={ids[n]:['common'] for n in doc['common']}
        for resource,count in sorted(counts.items()):
            if resource not in doc['resources']:
                if any(resource.startswith(p) for p in doc['silent_prefixes']):continue
                raise ValueError('unmapped sound resource: '+resource)
            for name,value in doc['resources'][resource].items():
                sid=ids[name];weight[sid]=weight.get(sid,0)+count*value
                reasons.setdefault(sid,[]).append(resource)
        weight = {i: v for i, v in weight.items() if i in AVAILABLE}
        reasons = {i: v for i, v in reasons.items() if i in AVAILABLE}
        result.append(dict(floor=floor,weights=weight,reasons=reasons,
                           resources=sorted(counts),resource_counts=dict(counts),
                           effects=sorted(weight),difficulty_independent=True))
    return result


@lru_cache(maxsize=1)
def pin_weights():
    """Rank pins by original actor/item starts, separately from sound coverage.

    Coverage includes every reachable sound. Ranking counts placed actors and
    pickups, with carried weapons accumulating within each episode. Potential
    drops and rare menu events must not displace frequent gun and sight sounds.
    Registered actors also contribute sounds of their spawned actors/projectiles.
    All difficulty variants count, so the selected plan is difficulty independent.
    """
    recipe = read_toml(ROOT/'profiles/audio'/('pinning-spear.toml' if PROFILE.spear else 'pinning-wolf3d.toml'))
    fields(recipe, ('format', 'common', 'initial_weapons', 'doors', 'pushwall',
                    'pickups', 'pickup_weapons'), 'sound pin ranking')
    if recipe['format'] != 1:
        raise ValueError('unsupported sound pin ranking recipe')
    native = read_toml(ROOT/'profiles/audio'/('native-effects-spear.toml' if PROFILE.spear else 'native-effects-wolf3d.toml'))
    ids = {name: i for i, name in enumerate(NAMES)}

    def weights(table):
        result = {}
        for name, value in table.items():
            if name not in ids:
                raise ValueError('unknown pin-ranking effect: ' + name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('pin-ranking weight must be positive: ' + name)
            result[ids[name]] = value
        return result

    common = weights(recipe['common'])
    initial = weights(recipe['initial_weapons'])
    doors = weights(recipe['doors'])
    pushwall = weights(recipe['pushwall'])
    for sound in recipe['pickups'].values():
        if sound not in ids:
            raise ValueError('unknown pickup sound: ' + sound)
    pickup_weapons = {kind: weights(value) for kind, value in recipe['pickup_weapons'].items()}
    actor_weights = {resource: weights(value) for resource, value in native['resources'].items()
                     if resource.startswith(('actor.', 'projectile.'))}
    semantics = MapSemantics(PROFILE.resource('map_semantics'))
    campaign = PROFILE.campaign
    carried = {}
    result = []
    for floor, level in enumerate(source_data().maps()):
        episode = campaign.floors[floor]['episode_id']
        if episode not in carried:
            carried[episode] = dict(initial)
        w = dict(common)

        def add(table, count=1):
            for sid, value in table.items():
                w[sid] = w.get(sid, 0) + count * value

        inspected = semantics.inspect_floor(level['planes'])
        pickups = Counter()
        actors = Counter()
        has_pushwall = False
        for obj in inspected['objects']:
            if obj['behavior'] == 'door':
                add(doors, obj['count'])
            elif obj['behavior'] == 'pushwall':
                has_pushwall = True
            elif obj['kind'] == 'pickup':
                pickups[obj['behavior']] += obj['count']
            elif obj['kind'] == 'actor':
                source = semantics.lookup[obj['plane'], obj['code']]
                actors[source['resource_id']] += obj['count']
        if has_pushwall:
            add(pushwall)
        for kind, count in pickups.items():
            sound = recipe['pickups'].get(kind)
            if sound is not None:
                add({ids[sound]: 1}, count)
            if kind in pickup_weapons:
                carried[episode].update(pickup_weapons[kind])
        for actor, count in actors.items():
            for resource in semantics.closure([actor]):
                name = resource['resource_id']
                if name.startswith(('actor.', 'projectile.')):
                    if name not in actor_weights:
                        raise ValueError('unmapped pin-ranking actor/projectile: ' + name)
                    add(actor_weights[name], count)
        add(carried[episode])
        result.append({i: v for i, v in w.items() if i in AVAILABLE})
    return result
