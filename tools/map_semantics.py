"""Preserve source map words and report their named behavior requirements."""
from collections import Counter
from pathlib import Path
from game_profile import fields, integer, read_toml
from campaign_profile import identity, records, text, digest


class MapSemantics:
    def __init__(self, path):
        self.document = read_toml(path)
        d = self.document
        fields(d, ('format', 'catalog_id', 'source_references', 'objects'), 'map semantics',
               optional=('resources', 'always_resources', 'sprite_catalog'))
        integer(d['format'], 1, 1, 'map semantics format')
        identity(d['catalog_id'], 'catalog_id')
        if not isinstance(d['source_references'], list):
            raise ValueError('map semantics source_references: expected a list')
        for ref in d['source_references']:
            text(ref, 'source reference')
        self.lookup = {}
        self.objects = records(d['objects'], 'name', 'map objects')
        for row in self.objects.values():
            fields(row, ('name', 'plane', 'kind', 'behavior', 'capabilities'), 'map object',
                   optional=('codes', 'ranges', 'parameters', 'resource_id'))
            text(row['name'], 'object.name')
            integer(row['plane'], 0, 2, 'object.plane')
            identity(row['kind'], 'object.kind'); identity(row['behavior'], 'object.behavior')
            self.capabilities(row['capabilities'])
            if not isinstance(row.get('parameters', {}), dict):
                raise ValueError('object.parameters: expected named source behavior parameters')
            codes = row.get('codes', [])
            ranges = row.get('ranges', [])
            if not isinstance(codes, list) or not isinstance(ranges, list):
                raise ValueError('object codes/ranges: expected lists')
            values = list(codes)
            for pair in ranges:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError('object range: expected [first, last], inclusive')
                lo, hi = pair
                integer(lo, 0, 65535, 'first code'); integer(hi, lo, 65535, 'last code')
                values.extend(range(lo, hi + 1))
            if not values:
                raise ValueError('map object has no codes or ranges')
            for code in values:
                integer(code, 0, 65535, 'map code')
                key = (row['plane'], code)
                if key in self.lookup:
                    raise ValueError('ambiguous map semantics for plane/code ' + str(key))
                self.lookup[key] = row
        resources = d.get('resources', [])
        self.resources = records(resources, 'resource_id', 'resources') if resources else {}
        for row in self.resources.values():
            fields(row, ('resource_id', 'sprite_names', 'sprite_prefixes', 'requires', 'capabilities'), 'resource')
            identity(row['resource_id'], 'resource_id'); self.capabilities(row['capabilities'])
            for key in ('sprite_names', 'sprite_prefixes', 'requires'):
                if not isinstance(row[key], list) or any(not isinstance(n, str) or not n for n in row[key]):
                    raise ValueError('resource.' + key + ': expected a list of names')
            for ref in row['requires']:
                self.resource(ref)
        always = d.get('always_resources', [])
        if not isinstance(always, list):
            raise ValueError('always_resources: expected a list')
        for ref in always:
            self.resource(ref)
        for row in self.objects.values():
            if 'resource_id' in row:
                self.resource(row['resource_id'])
        self.sprite_ids = {}
        if 'sprite_catalog' in d:
            text(d['sprite_catalog'], 'sprite_catalog')
            catalog = read_toml(Path(path).parent / d['sprite_catalog'])
            fields(catalog, ('format', 'catalog_id', 'sprites'), 'sprite catalog')
            integer(catalog['format'], 1, 1, 'sprite catalog format')
            identity(catalog['catalog_id'], 'sprite catalog_id')
            if not isinstance(catalog['sprites'], dict) or not catalog['sprites']:
                raise ValueError('sprites: expected named source indices')
            for name, index in catalog['sprites'].items():
                text(name, 'sprite name'); integer(index, 0, 65535, 'sprite index')
            self.sprite_ids = catalog['sprites']
            for row in self.resources.values():
                self.source_sprites(row)

    @staticmethod
    def capabilities(values):
        if not isinstance(values, list):
            raise ValueError('capabilities: expected a list of IDs')
        for value in values:
            identity(value, 'capability')

    def resource(self, ref):
        if not isinstance(ref, str) or ref not in self.resources:
            raise ValueError('unknown resource dependency: ' + str(ref))
        return self.resources[ref]

    def closure(self, roots):
        pending, found = list(roots), set()
        while pending:
            ref = pending.pop()
            if ref in found:
                continue
            row = self.resource(ref); found.add(ref); pending.extend(row['requires'])
        return [self.resources[ref] for ref in sorted(found)]

    def source_sprites(self, resource):
        names = set(resource['sprite_names'])
        for prefix in resource['sprite_prefixes']:
            matches = {n for n in self.sprite_ids if n.startswith(prefix)}
            if not matches:
                raise ValueError('resource sprite prefix has no source entries: ' + prefix)
            names.update(matches)
        missing = names - self.sprite_ids.keys()
        if missing:
            raise ValueError('unknown resource sprites: ' + ', '.join(sorted(missing)))
        return sorted({self.sprite_ids[n] for n in names})

    def inspect_floor(self, planes):
        capabilities, objects, unmapped = set(), [], []
        roots = set(self.document.get('always_resources', []))
        # Area words outside the engine's area table can carry editor data only
        # in sealed cells. Include doors and movable walls in the reachability
        # check so opening a route cannot expose such a cell during play.
        sealed = {i for i, code in enumerate(planes[0])
                  if self.lookup.get((0, code), {}).get('parameters', {}).get('sealed')}
        if sealed:
            reachable, pending = set(), [i for i, code in enumerate(planes[1])
                                        if self.lookup.get((1, code), {}).get('kind') in ('player', 'actor')]
            while pending:
                cell = pending.pop()
                if cell in reachable:
                    continue
                reachable.add(cell)
                x, y = cell % 64, cell // 64
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < 64 and 0 <= ny < 64):
                        continue
                    other = ny * 64 + nx
                    if other not in reachable and (planes[0][other] >= 90 or planes[1][other] == 98):
                        pending.append(other)
            if sealed & reachable or any(planes[1][i] for i in sealed):
                raise ValueError('out-of-range area metadata must remain empty and sealed from play')
        for plane, words in enumerate(planes):
            counts = Counter(words)
            for code, count in sorted(counts.items()):
                row = self.lookup.get((plane, code))
                if row is None:
                    positions = [dict(x=i % 64, y=i // 64) for i, v in enumerate(words) if v == code]
                    unmapped.append(dict(plane=plane, code=code, count=count, positions=positions))
                    continue
                capabilities.update(row['capabilities'])
                if 'resource_id' in row:
                    roots.add(row['resource_id'])
                objects.append(dict(plane=plane, code=code, count=count, name=row['name'],
                                    kind=row['kind'], behavior=row['behavior'], parameters=row.get('parameters', {})))
        resources = self.closure(roots)
        for row in resources:
            capabilities.update(row['capabilities'])
        source_sprites = sorted({i for r in resources for i in self.source_sprites(r)}) if self.sprite_ids else []
        return dict(objects=objects, unmapped_codes=unmapped, resources=resources,
                    source_sprite_ids=source_sprites, source_sprite_catalog_resolved=bool(self.sprite_ids),
                    required_capabilities=sorted(capabilities),
                    source_info_max=max(planes[1]), all_words_preserved=True,
                    native_allocation_verified=False)

    def semantic_identity(self):
        # The effective word-to-behavior mapping avoids identity changes caused
        # by merely splitting one code range into several named records.
        rows = []
        for (plane, code), row in sorted(self.lookup.items()):
            rows.append(dict(plane=plane, code=code, kind=row['kind'], behavior=row['behavior'],
                             parameters=row.get('parameters', {}), resource_id=row.get('resource_id'),
                             capabilities=sorted(row['capabilities'])))
        return digest(dict(objects=rows, resources=sorted(self.resources.values(),key=lambda r:r['resource_id']),
                           always_resources=sorted(self.document.get('always_resources', [])),
                           source_sprite_ids=self.sprite_ids))
