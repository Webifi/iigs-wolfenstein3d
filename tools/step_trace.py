"""Record what one Python process of a build step reads and writes.

tools/step_cache.py runs a step with STEP_TRACE_DIR set and tools/steptrace on
PYTHONPATH; tools/steptrace/sitecustomize.py then calls install() in the step
and in every Python process the step starts (multiprocessing workers too).

Each process writes one file STEP_TRACE_DIR/<pid>-<n>.trace of JSON lines:
- ["r", path, state, t]  first read of a path: state is the sha256 of the file
  at that moment, "dir", or null (missing). Opens and existence checks (stat)
  count.
- ["s", path, state, t]  first existence check (stat) of a path: "file:SIZE",
  "dir" or null; "file" for a profile read by value.
- ["c", path, state, t]  a project source file executed (imported or run).
- ["p", path, state, t]  an explicit semantic source fingerprint.
- ["l", path, names, t]  first listing of a folder (os.listdir, os.scandir,
  glob, Path.iterdir/glob): the sorted names, or null when it is missing. The
  import system's own listings are left out (the modules found count, and a
  failed import records the files it looked for as missing reads).
- ["w", path, t]         first write, create, delete or rename of a path.
- ["e", name, value]     first read of an environment variable (null: unset).
- ["v", key, digest]     a value read from tools/memmap.py: an attribute of the
  module, "NAMES[NAME]" for one table entry, "NAMES*" for the whole table.
- ["y", path, key, digest] a value read from an ELF file through tools/elf.py
  (see _check_elf).
- ["t", root, key, digest] a value read from a game profile, its conversion
  settings or profiles/native/world-colors.toml through game_profile.read_toml
  (see _toml_context); key "#file:PATH" gives the sha256 of a file the root
  was read from.
- ["x", argv]            a program started that is not a traced Python.
- ["end"]                the process exited normally (written at exit).
t is time.monotonic_ns(), comparable between the processes of one step.
"""
import builtins
import hashlib
import json
import os
import sys
import threading
import time
import types

_local = threading.local()
_out = None
_seen = {'r': set(), 'c': set(), 'p': set(), 'w': set()}
_stated = set()
_listed = set()
_env = set()
_values = set()
_ignore = ()
_explicit_ignore = ()
_roots = ()
_lock = threading.RLock()
_folder = None
_pythons = set()
_imports = set()
_memmap = []


def _emit(item):
    line = json.dumps(item, separators=(',', ':')) + '\n'
    with _lock:
        _out.write(line)
        _out.flush()


def _norm(path):
    if isinstance(path, int):
        return None
    try:
        path = os.fspath(path)
    except TypeError:
        return None
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not path or path.startswith('<'):
        return None
    path = os.path.abspath(path)
    if path.startswith(_explicit_ignore) or (not path.startswith(_roots) and path.startswith(_ignore)):
        return None
    return path


def _state(path):
    """sha256 of a file, 'dir' or None, read without triggering the hooks."""
    try:
        with open(path, 'rb') as handle:
            digest = hashlib.sha256()
            for block in iter(lambda: handle.read(1 << 20), b''):
                digest.update(block)
            return digest.hexdigest()
    except IsADirectoryError:
        return 'dir'
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return 'unreadable'


def _read(path, kind='r'):
    """kind 'r': the bytes of a file (unless this process wrote it first);
    kind 'c': a source file executed. A file can be both."""
    path = _norm(path)
    if path is None or path in _seen[kind] or (kind == 'r' and path in _seen['w']):
        return
    _seen[kind].add(path)
    if kind == 'p':
        from source_identity import source_digest
        state = source_digest(path)
    else:
        state = _state(path)
    _emit([kind, path, state, time.monotonic_ns()])


def _stat(path):
    """An existence check: what a stat shows a step (kind, and the size of a
    file; a profile read by value counts by its values, not its size)."""
    path = _norm(path)
    if path is None or path in _stated:
        return
    _stated.add(path)
    from code_key import stat_state
    _emit(['s', path, stat_state(path), time.monotonic_ns()])


def _write(path):
    path = _norm(path)
    if path is None or path in _seen['w']:
        return
    _seen['w'].add(path)
    _emit(['w', path, time.monotonic_ns()])


def _listing(path):
    path = _norm(path if path is not None else '.')
    if path is None or path in _listed:
        return
    _listed.add(path)
    try:
        names = sorted(os.listdir(path))
    except (FileNotFoundError, NotADirectoryError):
        names = None
    except OSError:
        names = ['(unreadable)']
    _emit(['l', path, names, time.monotonic_ns()])


WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _from_import_system():
    try:
        return sys._getframe(3).f_code.co_filename.startswith(('<frozen importlib', '<frozen zipimport'))
    except ValueError:
        return False


def _entry_source(path):
    """The interpreter opens its script before there is a Python caller."""
    try:
        sys._getframe(3)
    except ValueError:
        return (isinstance(path, str) and path.endswith('.py') and sys.argv
                and os.path.abspath(path) == os.path.abspath(sys.argv[0]))
    return False


def _semantic_source_read():
    try:
        code = sys._getframe(3).f_code
        if os.path.normpath(code.co_filename).endswith('/tools/source_identity.py'):
            if code.co_name == '_source_bytes':return 'p'
            if code.co_name == 'function_source':return 'c'
    except ValueError:
        pass
    return 'r'


def _hook(event, args):
    if getattr(_local, 'busy', False):
        return
    _local.busy = True
    try:
        _event(event, args)
    except Exception as error:  # never break the step; it is just not cached
        try:
            _emit(['x', ['(trace error: %s %s)' % (event, error)]])
        except Exception:
            pass
    finally:
        _local.busy = False


def _event(event, args):
    if event == 'open':
        path, mode, flags = args
        if mode is None:
            writes = bool(flags & WRITE_FLAGS)
            reads = not (flags & os.O_TRUNC) and (not writes or bool(flags & (os.O_RDWR | os.O_APPEND)))
        else:
            writes = any(c in mode for c in 'wax+')
            reads = 'r' in mode or 'a' in mode
        if reads and not writes and (_from_import_system() or _entry_source(path)):
            return  # module source or bytecode: recorded as executed code
        if reads and not writes and _toml_file(path):
            return  # a profile read by value (see _toml_context)
        if reads:
            _read(path, _semantic_source_read())
        if writes:
            _write(path)
    elif event in ('os.listdir', 'os.scandir'):
        if not _from_import_system():
            _listing(args[0] if args else None)
    elif event == 'import':
        _imports.add(args[0].partition('.')[0])
        _check_memmap()
        _check_elf()
        _check_toml()
    elif event in ('exec', 'compile'):
        name = getattr(args[0], 'co_filename', None) if event == 'exec' else args[1]
        if isinstance(name, str) and name.endswith('.py') and os.path.isfile(name):
            _read(name, 'c')
    elif event == 'os.mkdir':
        # makedirs(exist_ok=True) tries mkdir on folders that exist: no change.
        if not os.path.isdir(args[0]):
            _write(args[0])
    elif event in ('os.remove', 'os.rmdir', 'os.truncate', 'shutil.rmtree'):
        _write(args[0])
    elif event in ('os.rename', 'os.link', 'os.symlink'):
        if event == 'os.rename':
            _read(args[0])
            _write(args[0])
        _write(args[1])
    elif event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.spawn'):
        # Popen: (executable, args, cwd, env); system: (command,);
        # posix_spawn/exec: (path, argv, env); spawn: (mode, path, args, env).
        argv = args[{'subprocess.Popen': 1, 'os.system': 0, 'os.spawn': 2}.get(event, 1)]
        at = {'subprocess.Popen': 3, 'os.spawn': 3}.get(event, 2)
        env = args[at] if event != 'os.system' and len(args) > at else None
        argv = argv.split() if isinstance(argv, (str, bytes)) else list(argv or [])
        argv = [os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in argv]
        if env is not None:
            env = {os.fsdecode(k) if isinstance(k, bytes) else k: v for k, v in dict(env).items()}
        traced = bool(argv) and os.path.realpath(argv[0]) in _pythons and (
            env is None or env.get('STEP_TRACE_DIR') == _folder)
        if not traced:
            _emit(['x', argv])


def _wrap_stat(function):
    def stat(path, *args, **kwargs):
        if not getattr(_local, 'busy', False) and not isinstance(path, int) and not kwargs.get('dir_fd'):
            _local.busy = True
            try:
                _stat(path)
            except Exception as error:
                _emit(['x', ['(trace error: stat %s)' % error]])
            finally:
                _local.busy = False
        return function(path, *args, **kwargs)
    stat.__wrapped__ = function
    return stat


def _wrap_environ():
    environ_type = type(os.environ)
    getitem = environ_type.__getitem__
    setitem = environ_type.__setitem__

    def __getitem__(self, key):
        try:
            value = getitem(self, key)
        except KeyError:
            value = None
        if self is os.environ and key not in _env and not str(key).startswith('STEP_TRACE'):
            _env.add(key)
            _emit(['e', key, value])
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        if self is os.environ:
            _env.add(key)
        setitem(self, key, value)
    environ_type.__getitem__ = __getitem__
    environ_type.__setitem__ = __setitem__


# -- tools/memmap.py values ---------------------------------------------------

def _value(key, value):
    if key in _values:
        return
    _values.add(key)
    busy = getattr(_local, 'busy', False)
    _local.busy = True
    try:
        from code_key import fingerprint
        _emit(['v', key, fingerprint(value)])
    finally:
        _local.busy = busy


class _RecordingNames(dict):
    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        _value('NAMES[%s]' % key, value)
        return value

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return self[key]
        _value('NAMES[%s]' % key, None)
        return default

    def __contains__(self, key):
        _value('NAMES[%s]' % key, dict.get(self, key))
        return dict.__contains__(self, key)

    def _whole(self):
        _value('NAMES*', dict(dict.items(self)))

    def __iter__(self):
        self._whole()
        return dict.__iter__(self)

    def __len__(self):
        self._whole()
        return dict.__len__(self)

    def keys(self):
        self._whole()
        return dict.keys(self)

    def items(self):
        self._whole()
        return dict.items(self)

    def values(self):
        self._whole()
        return dict.values(self)

    def copy(self):
        self._whole()
        return dict(dict.items(self))


class _RecordingModule(types.ModuleType):
    def __getattribute__(self, name):
        value = types.ModuleType.__getattribute__(self, name)
        if name == '__dict__':
            _value('#all', {k: v for k, v in value.items() if not k.startswith('__')})
        elif name[:2] != '__' and not isinstance(value, _RecordingNames):
            _value(name, value)
        return value


def _check_memmap():
    if _memmap:
        return
    module = sys.modules.get('memmap')
    path = getattr(module, '__file__', None) or ''
    if module is None or not path.endswith(os.path.join('tools', 'memmap.py')) or type(module) is not types.ModuleType:
        return
    if 'NAMES' not in module.__dict__ or 'write_outputs' not in module.__dict__:
        return  # still importing
    _memmap.append(module)
    # Marks that this process read memmap values through the recording module;
    # tools/code_key.py then keys memmap on those values, not on its source.
    _emit(['v', '#memmap', os.path.abspath(path)])
    table = module.__dict__['NAMES']
    if isinstance(table, dict):
        module.__dict__['NAMES'] = _RecordingNames(table)
    module.__class__ = _RecordingModule


# -- tools/elf.py results ----------------------------------------------------
# A step that reads build/wolf.elf through elf.read() depends on the symbols and
# segment fields it looks at, not on every byte of the file:
# ["y", path, key, digest] with key "#sha" (the file), "sym:NAME", "sym*" (the
# whole table), "seg#" (the number of segments), "seg:I:FIELD" or "seg:I*".

_elf = []


def _elf_value(path, key, value):
    mark = (path, key)
    if mark in _values:
        return
    _values.add(mark)
    busy = getattr(_local, 'busy', False)
    _local.busy = True
    try:
        from code_key import fingerprint
        _emit(['y', path, key, fingerprint(value)])
    finally:
        _local.busy = busy


class _RecordingSymbols(dict):
    def __init__(self, path, table):
        dict.__init__(self, table)
        self._path = path

    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        _elf_value(self._path, 'sym:%s' % key, value)
        return value

    def get(self, key, default=None):
        _elf_value(self._path, 'sym:%s' % key, dict.get(self, key))
        return dict.get(self, key, default)

    def __contains__(self, key):
        _elf_value(self._path, 'sym:%s' % key, dict.get(self, key))
        return dict.__contains__(self, key)

    def _whole(self):
        _elf_value(self._path, 'sym*', dict(dict.items(self)))

    def __iter__(self):
        self._whole()
        return dict.__iter__(self)

    def __len__(self):
        self._whole()
        return dict.__len__(self)

    def keys(self):
        self._whole()
        return dict.keys(self)

    def items(self):
        self._whole()
        return dict.items(self)

    def values(self):
        self._whole()
        return dict.values(self)

    def copy(self):
        self._whole()
        return dict(dict.items(self))


class _RecordingSegment(dict):
    def __init__(self, path, index, fields):
        dict.__init__(self, fields)
        self._path = path
        self._index = index

    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        _elf_value(self._path, 'seg:%d:%s' % (self._index, key), value)
        return value

    def get(self, key, default=None):
        _elf_value(self._path, 'seg:%d:%s' % (self._index, key), dict.get(self, key))
        return dict.get(self, key, default)

    def _whole(self):
        _elf_value(self._path, 'seg:%d*' % self._index, dict(dict.items(self)))

    def __iter__(self):
        self._whole()
        return dict.__iter__(self)

    def keys(self):
        self._whole()
        return dict.keys(self)

    def items(self):
        self._whole()
        return dict.items(self)

    def values(self):
        self._whole()
        return dict.values(self)

    def copy(self):
        self._whole()
        return dict(dict.items(self))


class _RecordingSegments(list):
    def __init__(self, path, segments):
        list.__init__(self, [_RecordingSegment(path, i, s) if isinstance(s, dict) else s
                             for i, s in enumerate(segments)])
        self._path = path

    def _count(self):
        _elf_value(self._path, 'seg#', list.__len__(self))

    def __iter__(self):
        self._count()
        return list.__iter__(self)

    def __len__(self):
        self._count()
        return list.__len__(self)

    def __getitem__(self, index):
        self._count()
        return list.__getitem__(self, index)


def _check_elf():
    if _elf:
        return
    module = sys.modules.get('elf')
    path = getattr(module, '__file__', None) or ''
    if module is None or not path.endswith(os.path.join('tools', 'elf.py')) or 'read' not in module.__dict__:
        return
    _elf.append(module)
    original = module.__dict__['read']

    def read(path, *args, **kwargs):
        name = _norm(path)
        busy = getattr(_local, 'busy', False)
        _local.busy = True
        try:
            result = original(path, *args, **kwargs)
            digest = _state(name) if name else None
        finally:
            _local.busy = busy
        if name is None or not (isinstance(result, tuple) and len(result) == 2):
            if name:
                _read(name)
            return result
        segments, symbols = result
        _elf_value(name, '#sha', digest)
        return _RecordingSegments(name, segments), _RecordingSymbols(name, symbols)
    read.__wrapped__ = original
    module.read = read


# -- game profiles read by value --------------------------------------------------
# game_profile loads every profile (and its conversion settings) at import and
# checks every field. A step depends on the values it then reads, and on the
# profiles still loading; tools/step_cache.py checks both by loading them
# again with game_profile. Only these small documents are read by value; the
# larger TOML files (map semantics, campaigns) count whole.

def _value_toml(path):
    from code_key import value_toml
    return value_toml(path)


def _toml_context():
    """(read_toml path, load_profile path, inside a loader) from the stack."""
    frame = sys._getframe(1)
    toml = profile = None
    loader = False
    for _ in range(60):
        if frame is None:
            break
        code = frame.f_code
        if code.co_filename.endswith(os.sep + 'game_profile.py'):
            if code.co_name == 'read_toml' and toml is None:
                toml = frame.f_locals.get('path')
            elif code.co_name == 'load_profile':
                loader = True
                profile = frame.f_locals.get('path')
            elif code.co_name == 'conversion_settings':
                loader = True
        frame = frame.f_back
    return toml, profile, loader


def _toml_root(toml, profile):
    name = _norm(toml) if toml is not None else None
    if name is None or not _value_toml(name):
        return None, None
    if profile is not None:
        owner = _norm(profile)
        return json.dumps(['profile', owner]), ('document' if owner == name else 'conversion')
    return json.dumps(['toml', name]), 'toml'


def _toml_file(path):
    """A read of a value-level TOML file inside read_toml: note its sha256."""
    if not str(path).endswith('.toml'):
        return False
    toml, profile, _ = _toml_context()
    root, _part = _toml_root(toml, profile)
    if root is None:
        return False
    name = _norm(path)
    if name != _norm(toml):
        return False
    mark = ('#file', root, name)
    if mark not in _values:
        _values.add(mark)
        _emit(['t', root, '#file:' + name, _state(name)])
    return True


def _toml_note(node, key, kind, value):
    if getattr(_local, 'busy', False):
        return
    path = node._key + ((key,) if kind != 'w' else ())
    mark = (node._root, node._part, path, kind)
    if mark in _values:
        return
    busy = getattr(_local, 'busy', False)
    _local.busy = True
    try:
        if _toml_context()[2]:
            return  # read by game_profile's own loading and checks
        _values.add(mark)
        from code_key import fingerprint, toml_digest
        if kind == 'w':
            digest = toml_digest(value)
        elif kind == 'c':
            digest = 'dict' if isinstance(value, dict) else 'list'
        else:
            digest = fingerprint(value)
        _emit(['t', node._root, json.dumps([kind, node._part] + list(path)), digest])
    finally:
        _local.busy = busy


def _toml_value(node, key, value):
    if isinstance(value, (_TomlDict, _TomlList)):
        _toml_note(node, key, 'c', value)
    else:
        _toml_note(node, key, 'v', value)
    return value


class _TomlDict(dict):
    def __getitem__(self, key):
        try:
            value = dict.__getitem__(self, key)
        except KeyError:
            _toml_note(self, key, 'v', '(missing)')
            raise
        return _toml_value(self, key, value)

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return self[key]
        _toml_note(self, key, 'v', '(missing)')
        return default

    def __contains__(self, key):
        if dict.__contains__(self, key):
            _toml_value(self, key, dict.__getitem__(self, key))
            return True
        _toml_note(self, key, 'v', '(missing)')
        return False

    def _whole(self):
        _toml_note(self, None, 'w', self)

    def __iter__(self):
        self._whole()
        return dict.__iter__(self)

    def __len__(self):
        self._whole()
        return dict.__len__(self)

    def keys(self):
        self._whole()
        return dict.keys(self)

    def items(self):
        self._whole()
        return dict.items(self)

    def values(self):
        self._whole()
        return dict.values(self)

    def copy(self):
        self._whole()
        return dict(dict.items(self))

    def __eq__(self, other):
        self._whole()
        return dict.__eq__(self, other)

    def __ne__(self, other):
        self._whole()
        return dict.__ne__(self, other)

    def __repr__(self):
        self._whole()
        return dict.__repr__(self)

    __hash__ = None


class _TomlList(list):
    def __getitem__(self, index):
        if isinstance(index, slice):
            self._whole()
            return list.__getitem__(self, index)
        try:
            value = list.__getitem__(self, index)
        except IndexError:
            _toml_note(self, index, 'v', '(missing)')
            raise
        return _toml_value(self, index if index >= 0 else index + list.__len__(self), value)

    def _whole(self):
        _toml_note(self, None, 'w', self)

    def __iter__(self):
        self._whole()
        return list.__iter__(self)

    def __len__(self):
        self._whole()
        return list.__len__(self)

    def __contains__(self, value):
        self._whole()
        return list.__contains__(self, value)

    def index(self, *args):
        self._whole()
        return list.index(self, *args)

    def count(self, value):
        self._whole()
        return list.count(self, value)

    def __eq__(self, other):
        self._whole()
        return list.__eq__(self, other)

    def __ne__(self, other):
        self._whole()
        return list.__ne__(self, other)

    def __repr__(self):
        self._whole()
        return list.__repr__(self)

    __hash__ = None


def _wrap_toml(value, root, part, key):
    if isinstance(value, dict):
        node = _TomlDict()
        for k, v in value.items():
            dict.__setitem__(node, k, _wrap_toml(v, root, part, key + (k,)))
    elif isinstance(value, list):
        node = _TomlList(_wrap_toml(v, root, part, key + (i,)) for i, v in enumerate(value))
    else:
        return value
    node._root, node._part, node._key = root, part, key
    return node


_toml_modules = set()


def _check_toml():
    for name in ('vendor.tomli', 'tomllib'):
        module = sys.modules.get(name)
        if module is None or name in _toml_modules or 'loads' not in vars(module):
            continue
        _toml_modules.add(name)
        original = module.loads

        def loads(text, *args, _original=original, **kwargs):
            doc = _original(text, *args, **kwargs)
            toml, profile, _ = _toml_context()
            root, part = _toml_root(toml, profile)
            if root is None or not isinstance(doc, dict):
                return doc
            return _wrap_toml(doc, root, part, ())
        loads.__wrapped__ = original
        module.loads = loads


def _wrap_import():
    original = builtins.__import__

    def __import__(name, *args, **kwargs):
        module = original(name, *args, **kwargs)
        if not _memmap and 'memmap' in sys.modules:
            _check_memmap()
        if not _elf and 'elf' in sys.modules:
            _check_elf()
        if len(_toml_modules) < 2 and ('vendor.tomli' in sys.modules or 'tomllib' in sys.modules):
            _check_toml()
        return module
    builtins.__import__ = __import__


def _finish():
    _check_memmap()
    _local.busy = True
    for name, module in list(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and path.endswith('.py'):
            _read(path, 'c')
        elif path and path.endswith(('.so', '.pyd', '.dylib')):
            _read(path)
    # An import that failed depends on the module staying absent.
    for name in sorted(_imports - set(sys.modules)):
        for folder in sys.path:
            folder = _norm(folder or '.')
            if folder:
                _read(os.path.join(folder, name + '.py'))
                _read(os.path.join(folder, name, '__init__.py'))
    _emit(['end'])
    _out.close()


def install(folder):
    global _out, _ignore, _folder, _explicit_ignore, _roots
    import atexit
    _folder = folder
    _roots = tuple(p.rstrip('/') + '/' for p in
                   [os.path.realpath(os.getcwd())] + os.environ.get('STEP_TRACE_ROOTS', '').split(os.pathsep) if p)
    _explicit_ignore = tuple(p.rstrip('/') + '/' for p in
                             [os.path.abspath(folder)] + os.environ.get('STEP_TRACE_IGNORE', '').split(os.pathsep) if p)
    ignored = {sys.prefix, sys.base_prefix, sys.exec_prefix, '/System/', '/usr/lib/', '/usr/share/',
               '/Library/Developer/', '/dev/', os.path.expanduser('~/Library/Caches/'),
               os.path.realpath(os.environ.get('TMPDIR', '/tmp')), '/tmp/', '/private/tmp/',
               '/private/var/folders/', '/var/folders/', os.path.abspath(folder)}
    ignored.update(p for p in os.environ.get('STEP_TRACE_IGNORE', '').split(os.pathsep) if p)
    _ignore = tuple(sorted(p if p.endswith('/') else p + '/' for p in ignored))
    _pythons.update({os.path.realpath(sys.executable), os.path.realpath(getattr(sys, '_base_executable', sys.executable))})
    for name in ('python3', 'python'):
        for directory in os.environ.get('PATH', '').split(os.pathsep):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                _pythons.add(os.path.realpath(candidate))
    counter = 0
    while True:
        counter += 1
        path = os.path.join(folder, '%d-%d.trace' % (os.getpid(), counter))
        try:
            _out = open(path, 'x', encoding='utf-8')
            break
        except FileExistsError:
            continue
    _emit(['start', os.getpid(), list(sys.argv)])
    # The digests come from tools/code_key.py, whatever the step's sys.path is.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import code_key  # noqa: F401
    finally:
        sys.path.pop(0)
    main = sys.argv[0] if sys.argv and sys.argv[0].endswith('.py') and os.path.isfile(sys.argv[0]) else None
    os.stat = _wrap_stat(os.stat)
    os.lstat = _wrap_stat(os.lstat)
    import pathlib
    accessor = getattr(pathlib, '_NormalAccessor', None)
    for name in ('stat', 'lstat'):
        if accessor is not None and name in accessor.__dict__:
            setattr(accessor, name, staticmethod(_wrap_stat(accessor.__dict__[name])))
    _wrap_environ()
    _wrap_import()
    atexit.register(_finish)
    sys.addaudithook(_hook)
    # The main script (python3 tools/x.py) is read before any hook exists.
    if main:
        _local.busy = True
        _read(main, 'c')
        _local.busy = False
