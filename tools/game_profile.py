"""Load documented, human-editable DOS input and conversion profiles."""
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:
    from vendor import tomli as tomllib

PROFILE_DIR = Path(__file__).resolve().parents[1] / 'profiles'
REQUIRED = ('AUDIOHED', 'AUDIOT', 'GAMEMAPS', 'MAPHEAD',
            'VGADICT', 'VGAGRAPH', 'VGAHEAD', 'VSWAP')


def fields(table, expected, where, optional=()):
    if not isinstance(table, dict):
        raise ValueError(where + ': expected a table')
    missing, extra = set(expected) - table.keys(), table.keys() - set(expected) - set(optional)
    if missing or extra:
        detail = []
        if missing:
            detail.append('missing ' + ', '.join(sorted(missing)))
        if extra:
            detail.append('unknown ' + ', '.join(sorted(extra)))
        raise ValueError(where + ': ' + '; '.join(detail))


def integer(value, low, high, where):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{where}: expected an integer from {low} to {high}')


def number(value, low, high, where):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f'{where}: expected a number from {low} to {high}')


def read_toml(path):
    try:
        return tomllib.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError(f'{path}: {error}') from error


def conversion_settings(path):
    doc = read_toml(path)
    fields(doc, ('format', 'artwork', 'page', 'hallway_title', 'other_title', 'world'), str(path))
    integer(doc['format'], 1, 1, 'conversion.format')
    art = doc['artwork']
    fields(art, ('metric', 'chroma_weight', 'palette_alignment'), 'artwork')
    if art['metric'] not in ('oklab', 'rgb') or art['palette_alignment'] != 'soft-permutation':
        raise ValueError('artwork: metric must be oklab or rgb; alignment must preserve fitted colors')
    number(art['chroma_weight'], 0.01, 20, 'artwork.chroma_weight')
    page = doc['page']
    fields(page, ('rounds', 'restarts', 'dither_mode', 'serpentine', 'dither_candidates',
                  'dither_amount', 'flat_snap'), 'page')
    integer(page['rounds'], 1, 1000, 'page.rounds')
    integer(page['restarts'], 1, 100, 'page.restarts')
    if page['dither_mode'] not in ('nearest', 'fs', 'pairs') or type(page['serpentine']) is not bool:
        raise ValueError('page: invalid dithering mode or serpentine flag')
    number(page['flat_snap'], 0, 1000000, 'page.flat_snap')
    for name in ('page', 'hallway_title', 'other_title'):
        table = doc[name]
        if name != 'page':
            keys = ('palettes', 'restarts', 'dither_candidates', 'dither_amount')
            fields(table, keys + (('protected_boxes',) if name == 'hallway_title' else ()), name)
            integer(table['palettes'], 1, 16, name + '.palettes')
            integer(table['restarts'], 1, 100, name + '.restarts')
        integer(table['dither_candidates'], 1, 16, name + '.dither_candidates')
        number(table['dither_amount'], 0, 2, name + '.dither_amount')
    boxes = doc['hallway_title']['protected_boxes']
    if not isinstance(boxes, list):
        raise ValueError('hallway_title.protected_boxes: expected a list')
    for box in boxes:
        if not isinstance(box, list) or len(box) != 5:
            raise ValueError('protected box: expected [x0, y0, x1, y1, weight]')
        x0, y0, x1, y1, weight = box
        for value in box[:4]:
            integer(value, 0, 320, 'protected box coordinate')
        if not 0 <= x0 < x1 <= 320 or not 0 <= y0 < y1 <= 200:
            raise ValueError('protected box: outside the 320 by 200 picture')
        number(weight, 1, 1000, 'protected box weight')
    world = doc['world']
    fields(world, ('light_gains', 'palette_fit_gains', 'error_chroma_weight', 'error_hue_weight', 'large_error_scale',
                   'noise_chroma_weight', 'noise_hue_weight'), 'world', optional=('wall_coverage_share', 'wall_light_gains'))
    if 'wall_coverage_share' in world:
        number(world['wall_coverage_share'], 0, 1, 'world.wall_coverage_share')
    gains = world['light_gains']
    if not isinstance(gains, list) or len(gains) != 4:
        raise ValueError('world.light_gains: the native renderer requires four lights')
    for gain in gains:
        number(gain, 0, 1, 'world.light_gains')
    if gains != sorted(gains) or gains[-1] != 1:
        raise ValueError('world.light_gains: increasing gains must end at 1.0')
    if 'wall_light_gains' in world:
        walls = world['wall_light_gains']
        if not isinstance(walls, list) or len(walls) != 4 or walls != sorted(walls) or walls[-1] != 1:
            raise ValueError('world.wall_light_gains: four increasing gains must end at 1.0')
        for gain in walls:
            number(gain, 0, 1, 'world.wall_light_gains')
    fit = world['palette_fit_gains']
    if not isinstance(fit, list) or not fit or fit != sorted(fit) or fit[-1] != 1:
        raise ValueError('world.palette_fit_gains: increasing palette samples must end at 1.0')
    for gain in fit:
        number(gain, 0, 1, 'world.palette_fit_gains')
    for key, value in world.items():
        if key not in ('light_gains', 'wall_light_gains', 'palette_fit_gains'):
            number(value, 0, 1000, 'world.' + key)
    return doc


@dataclass(frozen=True)
class GameProfile:
    path: Path
    document: dict
    conversion: dict

    @property
    def key(self):
        return self.document['id']

    @property
    def title(self):
        return self.document['title']

    @property
    def files(self):
        return self.document['files']

    @property
    def episodes(self):
        return self.document['maps']['episodes']

    @property
    def floors(self):
        return self.document['maps']['count']

    @property
    def sounds(self):
        return self.document['audio']['sounds']

    @property
    def music(self):
        return self.document['audio']['music']

    @property
    def music_names(self):
        return self.document['audio']['song_names']

    @property
    def required_music(self):
        audio = self.document['audio']
        used = set(audio['floor_songs']) | set(audio['events'].values())
        return {index: name for index, name in enumerate(self.music_names) if name in used}

    @property
    def spear(self):
        return self.document['engine'] == 'spear'

    @property
    def public_game_data(self):
        return self.document['publication'] == 'shareware'

    @property
    def layouts(self):
        return self.document['graphics']['layouts']

    def resource(self, name):
        value = self.document.get(name)
        return (self.path.parent / value).resolve() if value else None

    @cached_property
    def campaign(self):
        from campaign_profile import Campaign
        path = self.resource('campaign')
        return Campaign(path, self) if path else None

    def floor_label(self, index):
        if not 0 <= index < self.floors:
            raise ValueError('floor outside ' + self.key)
        if self.campaign:
            floor = self.campaign.floors[index]
            episode = self.campaign.episodes[floor['episode_id']]
            number = episode.get('display_episode_number')
            local = floor['display_floor_number']
            return f'E{number}M{local}' if number is not None else f'Floor {local}'
        return f'Floor {index + 1}'


def load_profile(path):
    path = Path(path).resolve()
    doc = read_toml(path)
    fields(doc, ('format', 'id', 'title', 'engine', 'publication', 'conversion', 'files',
                 'maps', 'audio', 'graphics'), str(path), optional=('campaign', 'map_semantics'))
    integer(doc['format'], 1, 1, 'profile.format')
    if not isinstance(doc['id'], str) or not re.fullmatch('[a-z0-9][a-z0-9-]*', doc['id']):
        raise ValueError('profile.id: use lowercase letters, digits and hyphens')
    if not isinstance(doc['title'], str) or not doc['title'].strip():
        raise ValueError('profile.title: expected a name')
    if not isinstance(doc['engine'], str) or not re.fullmatch('[a-z0-9][a-z0-9-]*', doc['engine']):
        raise ValueError('profile.engine: expected a stable native ruleset ID')
    if doc['publication'] not in ('shareware', 'user-supplied'):
        raise ValueError('profile.publication: expected shareware or user-supplied')
    if not isinstance(doc['conversion'], str) or not doc['conversion']:
        raise ValueError('profile.conversion: expected a TOML file path')
    for name in ('campaign', 'map_semantics'):
        if name in doc and (not isinstance(doc[name], str) or not doc[name]):
            raise ValueError('profile.' + name + ': expected a TOML file path')
    fields(doc['files'], REQUIRED, 'files')
    for stem, name in doc['files'].items():
        if not isinstance(name, str) or not name or '/' in name or '\\' in name or name in ('.', '..'):
            raise ValueError('files.' + stem + ': expected a filename, without a directory')
    if len({name.upper() for name in doc['files'].values()}) != len(REQUIRED):
        raise ValueError('files: every source role requires a distinct filename')
    fields(doc['maps'], ('episodes', 'count', 'width', 'height', 'compression'), 'maps')
    # Host directory counts are separate from the selected native format's
    # capacity. EP03's 60-floor limit is checked at the capability boundary.
    integer(doc['maps']['count'], 1, 65535, 'maps.count')
    integer(doc['maps']['episodes'], 1, doc['maps']['count'], 'maps.episodes')
    if doc['maps']['width'] != 64 or doc['maps']['height'] != 64 or doc['maps']['compression'] != 'carmack-rlew':
        raise ValueError('maps: this decoder supports 64 by 64 Carmack/RLEW maps')
    fields(doc['audio'], ('sounds', 'music', 'song_names', 'floor_songs', 'events'), 'audio')
    integer(doc['audio']['sounds'], 1, 256, 'audio.sounds')
    integer(doc['audio']['music'], 1, 64, 'audio.music')
    names = doc['audio']['song_names']
    if not isinstance(names, list) or len(names) != doc['audio']['music']:
        raise ValueError('audio.song_names: one name is required for every source music ID')
    if any(not isinstance(name, str) or not re.fullmatch('[A-Z][A-Z0-9_]*', name) for name in names):
        raise ValueError('audio.song_names: use uppercase letters, digits and underscores')
    if len(set(names)) != len(names):
        raise ValueError('audio.song_names: duplicate song name')
    floor_songs = doc['audio']['floor_songs']
    if not isinstance(floor_songs, list) or len(floor_songs) != doc['maps']['count']:
        raise ValueError('audio.floor_songs: one song name is required for every floor')
    events = doc['audio']['events']
    if not isinstance(events, dict) or not events:
        raise ValueError('audio.events: expected named title/menu/ending song selections')
    if any(not isinstance(name, str) or name not in names for name in floor_songs + list(events.values())):
        raise ValueError('audio: floor/event song is missing from song_names')
    fields(doc['graphics'], ('layouts',), 'graphics', optional=('palette_sampling',))
    sampling = doc['graphics'].get('palette_sampling', {})
    fields(sampling, (), 'graphics.palette_sampling', optional=('include_objects', 'exclude_objects'))
    for field, values in sampling.items():
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError('graphics.palette_sampling.' + field + ': expected sprite names')
        if len(values) != len(set(values)):
            raise ValueError('graphics.palette_sampling.' + field + ': duplicate sprite name')
    if not isinstance(doc['graphics']['layouts'], list) or not doc['graphics']['layouts']:
        raise ValueError('graphics.layouts: expected at least one layout')
    signatures = set()
    for layout in doc['graphics']['layouts']:
        fields(layout, ('name', 'chunks', 'pictures', 'first_picture', 'tile8_count', 'roles'), 'graphics.layouts', optional=('demo_count',))
        if not isinstance(layout['name'], str) or not layout['name']:
            raise ValueError('graphics.layouts.name: expected a name')
        integer(layout['chunks'], 5, 4096, 'graphics.layouts.chunks')
        integer(layout['pictures'], 1, layout['chunks'] - 4, 'graphics.layouts.pictures')
        integer(layout['first_picture'], 3, 3, 'graphics.layouts.first_picture')
        integer(layout['tile8_count'], 1, 1024, 'graphics.layouts.tile8_count')
        integer(layout.get('demo_count', 4), 0, 7, 'graphics.layouts.demo_count')
        signature = (layout['chunks'], layout['pictures'])
        if signature in signatures:
            raise ValueError('graphics.layouts: duplicate count signature')
        signatures.add(signature)
        if not isinstance(layout['roles'], dict):
            raise ValueError('graphics.layouts.roles: expected named chunk numbers')
        for name, value in layout['roles'].items():
            integer(value, 0, layout['chunks'] - 1, 'graphics.layouts.roles.' + name)
    return GameProfile(path, doc, conversion_settings(path.parent / doc['conversion']))


PROFILES = {path.stem: load_profile(path) for path in sorted(PROFILE_DIR.glob('*.toml'))}


def profile(key):
    if isinstance(key, GameProfile):
        return key
    if str(key) in PROFILES:
        return PROFILES[str(key)]
    if Path(key).is_file():
        return load_profile(key)
    raise ValueError('unknown profile or missing TOML file: ' + str(key))
