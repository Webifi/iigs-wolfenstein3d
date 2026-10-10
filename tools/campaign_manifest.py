"""Emit host campaign/resource manifests and explicit native capability gaps."""
import hashlib
import struct

from campaign_profile import digest, identity
from game_profile import fields, integer, read_toml, REQUIRED
from map_semantics import MapSemantics

DECODER_CAPABILITIES = ['source.maps.carmack-rlew-64x64', 'source.sprites.wolf-posts',
                        'source.graphics.wolf-vga', 'source.audio.wolf-banks-imf']


def native_support(manifest, path=None):
    required = manifest['required_capabilities']
    unresolved = [dict(source_floor_index=f['source_floor_index'], **row)
                  for f in manifest['floor_resources'] for row in f['unmapped_codes']]
    if path is None:
        return dict(checked=False, supported=False, missing_capabilities=required,
                    unmet_limits=[], unmapped_codes=unresolved,
                    reason='Supply an engine-owned capability manifest to check native support.')
    doc = read_toml(path)
    fields(doc, ('format', 'engine_id', 'save_abi', 'capabilities', 'limits'), 'native capabilities')
    integer(doc['format'], 1, 1, 'native capabilities format')
    identity(doc['engine_id'], 'engine_id'); identity(doc['save_abi'], 'save_abi')
    MapSemantics.capabilities(doc['capabilities'])
    fields(doc['limits'], ('floors', 'episodes', 'map_width', 'map_height', 'source_info_max'), 'native limits')
    for key, value in doc['limits'].items():
        integer(value, 0, 65535, 'native limit ' + key)
    unmet = [dict(name=key, required=value, supported=doc['limits'][key])
             for key, value in manifest['required_limits'].items() if value > doc['limits'][key]]
    missing = sorted(set(required) - set(doc['capabilities']))
    return dict(checked=True, supported=not (missing or unmet or unresolved), engine_id=doc['engine_id'],
                save_abi=doc['save_abi'], capability_manifest_sha256=digest(doc),
                missing_capabilities=missing, unmet_limits=unmet, unmapped_codes=unresolved,
                runtime_verified=False, allocation_verified=False)


def compile_manifest(data, native_capabilities=None):
    game = data.profile
    campaign = game.campaign
    if campaign is None:
        raise ValueError('source profile needs an explicit campaign TOML reference')
    semantic_path = game.resource('map_semantics')
    if semantic_path is None:
        raise ValueError('source profile needs an explicit map_semantics TOML reference')
    semantics = MapSemantics(semantic_path)
    # Decode all containers before claiming source coverage. This also selects
    # the actual graphics layout for optional artwork-role references.
    source_report = data.inspect()
    maps = data.maps()
    pages, first_sprite, first_sound = data.vswap()
    result = campaign.manifest()
    result['decoder_capabilities'] = DECODER_CAPABILITIES
    required = set(result['required_capabilities'])
    plane_hashes, resources = {}, []
    for index, source in enumerate(maps):
        floor = campaign.floors[index]
        planes = source['planes']
        raw = b''.join(struct.pack('<%dH' % len(p), *p) for p in planes)
        plane_hashes[floor['floor_id']] = hashlib.sha256(raw).hexdigest()
        report = semantics.inspect_floor(planes)
        if report['resources'] and not report['source_sprite_catalog_resolved']:
            raise ValueError('resource manifest needs a source sprite catalog')
        missing = [i for i in report['source_sprite_ids']
                   if first_sprite + i >= first_sound or not pages[first_sprite + i]]
        if missing:
            raise ValueError('source floor %d is missing required VSWAP sprite pages: %s' % (index, missing))
        report['source_sprite_pages_verified'] = True
        report.update(source_floor_index=index, floor_id=floor['floor_id'],
                      source_planes_sha256=plane_hashes[floor['floor_id']])
        # Conservative source materials, including the flipped elevator and
        # the eight shared door pages. Final packing remains engine-owned.
        flagged_materials = {row['parameters']['wall_material'] for row in report['objects']
                             if row['plane'] == 0 and 'wall_material' in row['parameters']}
        report['wall_tile_codes'] = sorted({v for v in planes[0] if 0 < v < 64} | flagged_materials |
                                          ({22} if 21 in planes[0] else set()))
        report['shared_door_page_count'] = 8
        report['music_name'] = floor['music_name']
        report['sound_dependencies_verified'] = False
        required.update(report['required_capabilities'])
        resources.append(report)
    result['required_capabilities'] = sorted(required)
    result['floor_resources'] = resources
    result['required_limits'] = dict(floors=game.floors, episodes=game.episodes,
        map_width=game.document['maps']['width'], map_height=game.document['maps']['height'],
        source_info_max=max(r['source_info_max'] for r in resources))
    result['source_files'] = {stem:dict(filename=data.filename(stem),
        **source_report['files'][data.filename(stem)]) for stem in REQUIRED}
    result['graphics_layout'] = source_report['graphics_layout']
    result['source_profile_sha256'] = digest(game.document)
    result['map_semantics_sha256'] = semantics.semantic_identity()
    result['source_content_sha256'] = digest(dict(files={k:v['sha256'] for k,v in result['source_files'].items()},
        metadata=result['metadata_sha256'], map_semantics=result['map_semantics_sha256']))
    result['save_content_sha256'] = digest(dict(format=1, maps=plane_hashes, rules=campaign.save_rules(),
        map_semantics=result['map_semantics_sha256']))
    result['identity_note'] = 'Pair save_content_sha256 with the engine save ABI; disk placement and executable build IDs are not content identity.'
    result['native_support'] = native_support(result, native_capabilities)
    return result


def require_supported(manifest):
    support = manifest['native_support']
    if support['supported']:
        return
    errors = []
    if not support['checked']:
        errors.append(support['reason'])
    if support['missing_capabilities']:
        errors.append('missing native capabilities: ' + ', '.join(support['missing_capabilities']))
    if support['unmet_limits']:
        errors.append('native capacity exceeded: ' + ', '.join(
            str(r['name']) + ' needs ' + str(r['required']) + ', supports ' + str(r['supported']) for r in support['unmet_limits']))
    if support['unmapped_codes']:
        errors.append('unmapped source codes: ' + ', '.join(
            'floor %d plane %d code %d' % (r['source_floor_index'], r['plane'], r['code']) for r in support['unmapped_codes']))
    raise ValueError('; '.join(errors))
