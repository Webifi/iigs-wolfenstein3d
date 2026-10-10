"""Source identities for converted title, credit, rating and ending pages."""
import hashlib
import json
from source_identity import source_bytes


def digest(data):
    return hashlib.sha256(data).hexdigest()


def page_inputs(root, source, conversion, palette):
    """Cache only conversions made from the same source, rules and converter."""
    chunks = source.graphics()
    layout = source.graphics_layout
    converters = ('art_pages.py', 'art_lumps.py', 'build_menu.py', 'build_frontend.py',
                  'wolfpics.py', 'gscolor.py', 'page_text.py', 'wolfdata.py', 'dos_data.py',
                  'attract_assets.py', 'shr_search.py', 'host_kernels.c')
    if source.profile.spear:
        converters += ('spear_pages.py',)
    inputs = dict(
        profile=source.profile.key, layout=layout,
        source_files={name: digest(source.read(name)) for name in ('VGADICT', 'VGAHEAD', 'VGAGRAPH')},
        palette_sha256=digest(bytes(channel for color in palette for channel in color)),
        conversion=conversion, campaign=source.profile.campaign.document,
        converters={name: digest(source_bytes(root/'tools'/name)) for name in converters})
    key = digest(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode())
    roles = layout['roles']
    pictures = {name: roles[name] for name in ('title', 'title_top', 'title_bottom', 'title_palette', 'credits', 'rating') if name in roles}
    if source.profile.spear:
        pictures.update((name, index) for name, index in roles.items()
                        if name.startswith(('ending_picture_', 'ending_palette_')))
    for episode in source.profile.campaign.document['episode_menu_order']:
        campaign = source.profile.campaign
        ending = campaign.endings[campaign.episodes[episode]['ending_id']]
        pictures['ending_' + episode] = roles[ending['picture_role']] + ending.get('picture_offset', 0)
    provenance = dict(format=1, cache_identity=key, inputs=inputs,
                      source_chunks={name: dict(chunk=index, sha256=digest(chunks[index]))
                                     for name, index in pictures.items()})
    return key, provenance
