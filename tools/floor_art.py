"""Source floor colors and complete sprite dependencies for native conversion."""
from functools import lru_cache

from game_profile import read_toml
from map_semantics import MapSemantics
from wolfdata import ROOT, PROFILE


@lru_cache(None)
def semantics():
    return MapSemantics(PROFILE.resource('map_semantics'))


def shapes(level):
    catalog = semantics()
    report = catalog.inspect_floor(level['planes'])
    actors, objects, weapons = set(), set(), set()
    for resource in report['resources']:
        name = resource['resource_id']
        target = (weapons if name == 'player.weapons' else
                  actors if name.startswith(('actor.', 'projectile.')) else objects)
        target.update(catalog.source_sprites(resource))
    return actors, objects, weapons


@lru_cache(None)
def colors():
    doc = read_toml(ROOT / 'profiles/native/world-colors.toml')
    return doc[PROFILE.document['engine']]


def ceiling(floor):
    return colors()['ceiling'][floor]


def floor_color():
    return colors()['floor']
