"""The code a Python step can run, as hashes that ignore code it cannot reach.

A step loads some project modules (tools/step_trace.py records their files).
Every top-level statement of a loaded module runs at import, so each one is
part of the key, except plain function and class definitions: a top-level
def or class is part of the key only when its name is used by code that is
part of the key (any Name, attribute or identifier-like string in it, closed
under this rule). A decorated def is always part of it (a decorator can
register it). A def's whole text counts (body, defaults, nested code).

So an edit to a function the step cannot call, a new function, a comment or a
moved line does not change the key; an edit to a reachable function, to a
module-level constant or import, or a new def that shadows a used name does.
Names are matched without their module, which over-approximates (never misses
a call by name). Calls by computed names (getattr with a built string) are
the documented limit; this code base uses them for memmap names, see below.

tools/memmap.py is data: its top-level statements build the address table, so
they are not part of the key. The values the step reads are instead: the
step's attribute reads of the memmap module and its NAMES lookups (recorded at
run time by tools/step_trace.py), and the globals that reachable memmap
functions use (fingerprinted from the module here).
"""
import ast
import hashlib
import json
import re

IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
TEMPLATE = re.compile(r'@MM:([A-Z][A-Z0-9_]*)')
# The cache's own code decides keys, never outputs.
TRACER_FILES = ('/tools/step_trace.py', '/tools/steptrace/sitecustomize.py', '/tools/code_key.py',
                '/tools/step_cache.py', '/tools/shared_cache.py')
MEMMAP = '/tools/memmap.py'

_parsed = {}


def is_memmap(path):
    return path.endswith(MEMMAP)


def names_in(node):
    found = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Name):
            found.add(item.id)
        elif isinstance(item, ast.Attribute):
            found.add(item.attr)
        elif isinstance(item, ast.alias):
            found.add(item.name.split('.')[0])
            found.update(item.name.split('.'))
            if item.asname:
                found.add(item.asname)
        elif isinstance(item, ast.Constant) and isinstance(item.value, str):
            if IDENTIFIER.match(item.value):
                found.add(item.value)
            elif '@MM:' in item.value:
                found.update(TEMPLATE.findall(item.value))
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(item.name)
    return found


class WithoutDocstrings(ast.NodeTransformer):
    """Remove documentation while retaining literal values used by code."""

    def generic_visit(self, node):
        super().generic_visit(node)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
        return node


def dump(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


class Module:
    """One source file split into statements (always run) and named defs.
    data=True (tools/memmap.py read through tools/step_trace.py's recording
    module): the statements are data, keyed by the values read instead."""

    def __init__(self, path, text, data=False):
        tree = WithoutDocstrings().visit(ast.parse(text, filename=path))
        self.path = path
        self.memmap = data
        self.statements = []      # (hash, names) of statements that run at import
        self.defs = {}            # name -> [(hash, names)] of plain top-level defs
        for node in tree.body:
            plain = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.decorator_list
            if plain:
                self.defs.setdefault(node.name, []).append((dump(node), names_in(node)))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue  # a docstring
            else:
                self.statements.append((dump(node), names_in(node)))

    def statement_hash(self):
        if self.memmap:
            return 'memmap'
        return hashlib.sha256(json.dumps([h for h, _ in self.statements]).encode()).hexdigest()

    def roots(self):
        if self.memmap:
            return set()
        found = set()
        for _, names in self.statements:
            found |= names
        return found


def parse(path, digest=None, data=False):
    key = (path, digest, data)
    if key not in _parsed:
        with open(path, encoding='utf-8', errors='surrogateescape') as handle:
            _parsed[key] = Module(path, handle.read(), data)
    return _parsed[key]


def reach(modules, roots=None):
    """The used names: the modules' statements and roots, closed over defs."""
    names = set(roots or ())
    for module in modules:
        names |= module.roots()
    grown = True
    while grown:
        grown = False
        for module in modules:
            for name, versions in module.defs.items():
                if name in names:
                    for _, used in versions:
                        if not used <= names:
                            names |= used
                            grown = True
    return names


def entry(module, names):
    return dict(statements=module.statement_hash(), data=module.memmap,
                defs={name: [h for h, _ in versions] for name, versions in sorted(module.defs.items()) if name in names})


def analyze(files, roots=None, data=()):
    """files: {path: sha256}; data: the files read as recorded values
    (memmap). Returns (names, {path: entry})."""
    modules = [parse(path, digest, path in data) for path, digest in sorted(files.items())
               if not path.endswith(TRACER_FILES)]
    names = reach(modules, roots)
    return names, {module.path: dict(entry(module, names), sha=files[module.path]) for module in modules}


def still_valid(path, digest, recorded, names):
    """A changed module file still gives the recorded entry for these names."""
    module = parse(path, digest, recorded.get('data', False))
    return entry(module, names) == {k: v for k, v in recorded.items() if k != 'sha'}


def _canon(value):
    """A text for a value: functions and modules count as code (keyed apart),
    containers element by element, other values by repr."""
    if callable(value) or type(value).__name__ == 'module':
        return 'code'
    if isinstance(value, dict):
        return 'd{' + ','.join(_canon(k) + ':' + _canon(v) for k, v in dict.items(value)) + '}'
    if isinstance(value, (list, tuple)):
        return type(value).__name__[0] + '[' + ','.join(_canon(v) for v in value) + ']'
    if isinstance(value, (set, frozenset)):
        return 's{' + ','.join(sorted(_canon(v) for v in value)) + '}'
    text = repr(value)
    if ' at 0x' in text:
        text = type(value).__name__ + ':' + text.split(' at 0x')[0]
    return text


def fingerprint(value):
    return hashlib.sha1(_canon(value).encode()).hexdigest()


def memmap_globals(module, names):
    """Fingerprints of the memmap globals that reachable memmap defs use."""
    used = set()
    for versions in (v for k, v in module.defs.items() if k in names):
        for _, inner in versions:
            used |= inner
    return used - {'NAMES'}


def memmap_values(path, keys):
    """Current fingerprints for recorded memmap keys ('NAME' or 'NAMES[NAME]'
    or 'NAMES*' for the whole table)."""
    module = load_tool(path, '_memmap_for_cache')
    table = getattr(module, 'NAMES', {})
    result = {}
    for key in keys:
        if key == '#memmap':
            result[key] = path
        elif key == '#all':
            result[key] = fingerprint({k: v for k, v in vars(module).items() if not k.startswith('__')})
        elif key == 'NAMES*':
            result[key] = fingerprint(table)
        elif key.startswith('NAMES[') and key.endswith(']'):
            name = key[6:-1]
            result[key] = fingerprint(table[name]) if name in table else None
        else:
            result[key] = fingerprint(getattr(module, key)) if hasattr(module, key) else None
    return result


def load_tool(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def elf_values(tool, path, keys):
    """Current fingerprints for the ELF keys tools/step_trace.py records."""
    segments, symbols = load_tool(tool, '_elf_for_cache').read(path)
    result = {}
    for key in keys:
        if key == '#sha':
            import hashlib as _hashlib
            with open(path, 'rb') as handle:
                result[key] = fingerprint(_hashlib.sha256(handle.read()).hexdigest())
        elif key == 'sym*':
            result[key] = fingerprint(dict(symbols))
        elif key.startswith('sym:'):
            result[key] = fingerprint(symbols.get(key[4:]))
        elif key == 'seg#':
            result[key] = fingerprint(len(segments))
        elif key.startswith('seg:'):
            index, _, field = key[4:].partition(':')
            whole = index.endswith('*')
            index = int(index.rstrip('*'))
            if index >= len(segments):
                result[key] = 'missing'
            elif whole:
                result[key] = fingerprint(dict(segments[index]))
            else:
                result[key] = fingerprint(segments[index].get(field))
        else:
            result[key] = 'unknown'
    return result


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in dict.items(value)}
    if isinstance(value, list):
        return [_plain(v) for v in list.__iter__(value)]
    return value


def toml_digest(value):
    """The digest of a whole profile table (tools/step_trace.py records it)."""
    return hashlib.sha1(json.dumps(_plain(value), sort_keys=True, default=str).encode()).hexdigest()


def toml_parts(module, root):
    """The documents a recorded profile root names, loaded again now:
    load_profile() (which checks it) for a game profile, read_toml() else."""
    kind, path = json.loads(root)
    if kind == 'profile':
        loaded = module.load_profile(path)
        return {'document': loaded.document, 'conversion': loaded.conversion}
    return {'toml': module.read_toml(path)}


def toml_values(parts, keys):
    """Current digests for recorded profile keys (not the #file: entries)."""
    result = {}
    for key in keys:
        if key.startswith('#file:'):
            continue
        kind, part, *path = json.loads(key)
        node, found = parts.get(part), part in parts
        for step in path:
            try:
                node = node[step]
            except (KeyError, IndexError, TypeError):
                found = False
                break
        if kind == 'w':
            result[key] = toml_digest(node) if found else 'missing'
        elif kind == 'c':
            result[key] = ('dict' if isinstance(node, dict) else 'list' if isinstance(node, list) else 'leaf') if found else 'missing'
        else:
            result[key] = fingerprint(node if found else '(missing)')
    return result


def value_toml(path):
    """Project profiles read through the TOML loader are keyed by values."""
    path = str(path)
    if not path.endswith('.toml') or '/profiles/' not in path:
        return False
    return True


def stat_state(path):
    """What an existence check shows: "file:SIZE", "dir", "other" or None."""
    import os
    import stat as kinds
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return 'other'
    if kinds.S_ISDIR(info.st_mode):
        return 'dir'
    if kinds.S_ISREG(info.st_mode):
        return 'file' if value_toml(path) else 'file:%d' % info.st_size
    return 'other'
