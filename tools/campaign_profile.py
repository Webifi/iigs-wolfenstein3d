"""Validate editable campaigns independently of native table placement."""
import copy
import hashlib
import json
import re

from game_profile import fields, integer, read_toml


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(where + ': expected nonempty text')


def identity(value, where):
    if not isinstance(value, str) or not re.fullmatch('[a-z0-9][a-z0-9_.-]*', value):
        raise ValueError(where + ': use a stable ID containing lowercase letters, digits, dots or hyphens')


def records(value, key, where):
    if not isinstance(value, list) or not value:
        raise ValueError(where + ': expected at least one record')
    out = {}
    for row in value:
        if not isinstance(row, dict) or key not in row:
            raise ValueError(where + ': missing ' + key)
        ident = row[key]
        if type(ident) not in (int, str):
            raise ValueError(where + ': invalid ' + key)
        if ident in out:
            raise ValueError(where + ': duplicate ' + key + ' ' + str(ident))
        out[ident] = row
    return out


class Campaign:
    def __init__(self, path, game):
        self.path = path
        self.game = game
        self.document = read_toml(path)
        self.validate()

    def validate(self):
        d, game = self.document, self.game
        fields(d, ('format', 'profile_id', 'campaign_id', 'title', 'episode_menu_order',
                   'default_episode', 'source_references', 'episodes', 'floors', 'routes', 'endings'),
               'campaign')
        integer(d['format'], 1, 1, 'campaign.format')
        for key in ('profile_id', 'campaign_id', 'default_episode'):
            identity(d[key], 'campaign.' + key)
        if d['profile_id'] != game.key:
            raise ValueError('campaign.profile_id does not match the selected source profile')
        text(d['title'], 'campaign.title')
        if not isinstance(d['source_references'], list):
            raise ValueError('campaign.source_references: expected a list of source descriptions')
        for ref in d['source_references']:
            text(ref, 'campaign.source_references')
        self.episodes = records(d['episodes'], 'episode_id', 'episodes')
        self.floors = records(d['floors'], 'source_floor_index', 'floors')
        self.endings = records(d['endings'], 'ending_id', 'endings')
        order = d['episode_menu_order']
        if not isinstance(order, list) or any(not isinstance(e, str) for e in order) or \
                len(order) != len(self.episodes) or set(order) != set(self.episodes):
            raise ValueError('episode_menu_order must contain each episode ID exactly once')
        if d['default_episode'] not in self.episodes or len(order) != game.episodes:
            raise ValueError('campaign episodes/default do not match the source profile')
        if set(self.floors) != set(range(game.floors)):
            raise ValueError('floors must explicitly cover every bundled source floor index')
        floor_ids, display_pairs, episode_numbers = set(), set(), set()
        roles = set.intersection(*(set(layout['roles']) for layout in game.layouts))
        for ending in self.endings.values():
            fields(ending, ('ending_id', 'kind'), 'ending',
                   optional=('picture_role', 'picture_offset', 'music_name'))
            identity(ending['ending_id'], 'ending.ending_id')
            identity(ending['kind'], 'ending.kind')
            self.asset_roles(ending, roles)
        for floor in self.floors.values():
            fields(floor, ('floor_id', 'source_floor_index', 'episode_id', 'display_floor_number',
                           'title', 'role', 'tally_kind', 'music_name'), 'floor',
                   optional=('par_seconds', 'bonus_points', 'picture_role', 'picture_offset'))
            identity(floor['floor_id'], 'floor.floor_id')
            if floor['floor_id'] in floor_ids:
                raise ValueError('duplicate floor_id: ' + floor['floor_id'])
            floor_ids.add(floor['floor_id'])
            integer(floor['source_floor_index'], 0, game.floors - 1, 'source_floor_index')
            identity(floor['episode_id'], 'floor.episode_id')
            if floor['episode_id'] not in self.episodes:
                raise ValueError('floor references an unknown episode_id')
            integer(floor['display_floor_number'], 1, 65535, 'display_floor_number')
            pair = (floor['episode_id'], floor['display_floor_number'])
            if pair in display_pairs:
                raise ValueError('duplicate displayed floor number within an episode')
            display_pairs.add(pair)
            text(floor['title'], 'floor.title')
            identity(floor['role'], 'floor.role')
            identity(floor['tally_kind'], 'floor.tally_kind')
            if floor['tally_kind'] == 'par_ratios':
                integer(floor.get('par_seconds'), 1, 86400, 'floor.par_seconds')
            elif 'par_seconds' in floor:
                raise ValueError('par_seconds requires tally_kind = "par_ratios"')
            if floor['tally_kind'] == 'fixed_bonus':
                integer(floor.get('bonus_points'), 0, 0x7fffffff, 'floor.bonus_points')
            elif 'bonus_points' in floor:
                raise ValueError('bonus_points requires tally_kind = "fixed_bonus"')
            self.asset_roles(floor, roles)
            if floor['music_name'] != game.document['audio']['floor_songs'][floor['source_floor_index']]:
                raise ValueError('floor music differs from audio.floor_songs for ' + floor['floor_id'])
        for episode in self.episodes.values():
            fields(episode, ('episode_id', 'title', 'start_source_floor_index',
                             'boss_source_floor_indices', 'ending_id'), 'episode',
                   optional=('display_episode_number',))
            identity(episode['episode_id'], 'episode.episode_id')
            text(episode['title'], 'episode.title')
            if 'display_episode_number' in episode:
                n = episode['display_episode_number']
                integer(n, 1, 65535, 'display_episode_number')
                if n in episode_numbers:
                    raise ValueError('duplicate display_episode_number')
                episode_numbers.add(n)
            self.in_episode(episode['start_source_floor_index'], episode['episode_id'])
            bosses = episode['boss_source_floor_indices']
            if not isinstance(bosses, list) or any(type(i) is not int for i in bosses) or len(bosses) != len(set(bosses)):
                raise ValueError('boss_source_floor_indices: expected distinct source indices')
            for index in bosses:
                self.in_episode(index, episode['episode_id'])
            identity(episode['ending_id'], 'episode.ending_id')
            if episode['ending_id'] not in self.endings:
                raise ValueError('episode references an unknown ending_id')
        if not isinstance(d['routes'], list) or not d['routes']:
            raise ValueError('routes: expected explicit route records')
        self.routes = {}
        for route in d['routes']:
            destination = route.get('destination_kind') if isinstance(route, dict) else None
            if destination not in ('floor', 'ending'):
                raise ValueError('route.destination_kind: expected floor or ending')
            target = 'target_source_floor_index' if destination == 'floor' else 'ending_id'
            fields(route, ('source_floor_index', 'trigger', 'destination_kind', target, 'show_tally'),
                   'route', optional=('arrival',) if destination == 'floor' else ())
            index = route['source_floor_index']
            integer(index, 0, game.floors - 1, 'route.source_floor_index')
            identity(route['trigger'], 'route.trigger')
            if type(route['show_tally']) is not bool:
                raise ValueError('route.show_tally: expected a boolean')
            if route['show_tally'] and self.floors[index]['tally_kind'] == 'none':
                raise ValueError('route requests tally on a floor with no tally')
            key = (index, route['trigger'])
            if key in self.routes:
                raise ValueError('ambiguous duplicate route trigger at source floor ' + str(index))
            self.routes[key] = route
            episode_id = self.floors[index]['episode_id']
            if destination == 'floor':
                integer(route[target], 0, game.floors - 1, 'route.target_source_floor_index')
                identity(route.get('arrival', 'map_start'), 'route.arrival')
            else:
                identity(route[target], 'route.ending_id')
                if route[target] != self.episodes[episode_id]['ending_id']:
                    raise ValueError('route ending must match its episode ending_id')
        self.reachability()

    def in_episode(self, index, episode_id):
        integer(index, 0, self.game.floors - 1, 'source floor reference')
        if self.floors[index]['episode_id'] != episode_id:
            raise ValueError('floor reference crosses episode boundary')

    def asset_roles(self, row, roles):
        if 'music_name' in row and (not isinstance(row['music_name'], str) or row['music_name'] not in self.game.music_names):
            raise ValueError('unknown music_name: ' + str(row['music_name']))
        if 'picture_role' in row:
            if not isinstance(row['picture_role'], str) or row['picture_role'] not in roles:
                raise ValueError('picture_role must exist in every accepted graphics layout')
            offset = row.get('picture_offset', 0)
            integer(offset, 0, 4095, 'picture_offset')
            for layout in self.game.layouts:
                if layout['roles'][row['picture_role']] + offset >= layout['chunks']:
                    raise ValueError('picture role plus offset is outside the graphics layout')
        elif 'picture_offset' in row:
            raise ValueError('picture_offset needs picture_role')

    def reachability(self):
        adjacency = {i: [] for i in self.floors}
        ending_sources = set()
        for route in self.routes.values():
            source = route['source_floor_index']
            if route['destination_kind'] == 'floor':
                adjacency[source].append(route['target_source_floor_index'])
            else:
                ending_sources.add(source)
        used_endings = {r['ending_id'] for r in self.routes.values() if r['destination_kind'] == 'ending'}
        if used_endings != set(self.endings):
            raise ValueError('endings have no explicit route: ' + ', '.join(sorted(set(self.endings) - used_endings)))
        finished = set(ending_sources)
        while True:
            more = {i for i in self.floors if any(j in finished for j in adjacency[i])}
            if more <= finished:
                break
            finished.update(more)
        for episode in self.episodes.values():
            todo = [episode['start_source_floor_index']]
            reached = set()
            while todo:
                index = todo.pop()
                if index not in reached:
                    reached.add(index); todo.extend(adjacency[index])
            expected = {i for i, f in self.floors.items() if f['episode_id'] == episode['episode_id']}
            if not expected <= reached:
                raise ValueError('unreachable campaign floors: ' + str(sorted(expected - reached)))
            # Every map must be able to reach an ending, not just a start.
            if not expected <= finished:
                raise ValueError('floors have no route to an ending: ' + str(sorted(expected - finished)))

    def normalized(self):
        d = dict(self.document)
        d['episodes'] = [d for _, d in sorted(self.episodes.items())]
        d['endings'] = [d for _, d in sorted(self.endings.items())]
        d['floors'] = [d for _, d in sorted(self.floors.items())]
        d['routes'] = [dict(r, **({'arrival': r.get('arrival', 'map_start')} if r['destination_kind'] == 'floor' else {}))
                       for _, r in sorted(self.routes.items())]
        return copy.deepcopy(d)

    def manifest(self):
        d = self.normalized()
        order = {name: i for i, name in enumerate(d['episode_menu_order'])}
        floors = sorted(self.floors.values(), key=lambda f: (order[f['episode_id']], f['display_floor_number']))
        mapping = {f['source_floor_index']: i for i, f in enumerate(floors)}
        d['floors'] = [dict(f, compiled_floor_index=mapping[f['source_floor_index']]) for f in floors]
        d['source_to_compiled'] = [dict(source_floor_index=i, compiled_floor_index=mapping[i]) for i in sorted(mapping)]
        for episode in d['episodes']:
            episode['start_compiled_floor_index'] = mapping[episode['start_source_floor_index']]
            episode['boss_compiled_floor_indices'] = [mapping[i] for i in episode['boss_source_floor_indices']]
        for route in d['routes']:
            route['compiled_floor_index'] = mapping[route['source_floor_index']]
            if route['destination_kind'] == 'floor':
                route['target_compiled_floor_index'] = mapping[route['target_source_floor_index']]
        return dict(format=1, kind='campaign-manifest', campaign=d,
                    metadata_sha256=digest(self.normalized()), required_capabilities=self.requirements(),
                    full_game_runtime_verified=False)

    def requirements(self):
        needed = {'rules.' + self.game.document['engine'], 'campaign.explicit-routes',
                  'save.campaign-identity'}
        if len(self.episodes) > 1:
            needed.add('menu.episode-selection')
        if any(r['destination_kind'] == 'floor' and
               self.floors[r['source_floor_index']]['episode_id'] != self.floors[r['target_source_floor_index']]['episode_id']
               for r in self.routes.values()):
            needed.add('campaign.cross-episode-routes')
        needed.update('route.' + r['trigger'] for r in self.routes.values())
        needed.update('arrival.' + r.get('arrival', 'map_start') for r in self.routes.values()
                      if r['destination_kind'] == 'floor')
        needed.update('tally.' + f['tally_kind'] for f in self.floors.values())
        needed.update('ending.' + e['kind'] for e in self.endings.values())
        return sorted(needed)

    def save_rules(self):
        """Gameplay identity excludes prose, table order, and physical placement."""
        name = lambda i: self.floors[i]['floor_id']
        floors = [dict(floor_id=f['floor_id'], episode_id=f['episode_id'], role=f['role'],
                       tally_kind=f['tally_kind'], par_seconds=f.get('par_seconds'),
                       bonus_points=f.get('bonus_points')) for f in self.floors.values()]
        routes = []
        for r in self.routes.values():
            routes.append(dict(floor_id=name(r['source_floor_index']), trigger=r['trigger'],
                destination_kind=r['destination_kind'], target=(name(r['target_source_floor_index'])
                if r['destination_kind'] == 'floor' else r['ending_id']),
                show_tally=r['show_tally'], arrival=r.get('arrival', 'map_start')))
        episodes = [dict(episode_id=e['episode_id'], start=name(e['start_source_floor_index']),
                         bosses=sorted(name(i) for i in e['boss_source_floor_indices']), ending_id=e['ending_id'])
                    for e in self.episodes.values()]
        return dict(format=1, ruleset=self.game.document['engine'], campaign_id=self.document['campaign_id'],
                    episodes=sorted(episodes,key=lambda e:e['episode_id']),
                    floors=sorted(floors,key=lambda f:f['floor_id']),
                    routes=sorted(routes,key=lambda r:(r['floor_id'],r['trigger'])),
                    endings=sorted((dict(ending_id=e['ending_id'],kind=e['kind']) for e in self.endings.values()),
                                   key=lambda e:e['ending_id']))
