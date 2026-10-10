"""Skip a build step when nothing it read has changed (a verifying trace).

The first run of a step records what it actually read and wrote:
- Python steps run with tools/step_trace.py in every one of their processes:
  file contents, folder listings, existence checks, environment variables,
  memmap values, modules that failed to import, and the code files executed
  (keyed by tools/code_key.py: only the code the step can reach counts);
- assembler and linker runs record the source, every #include candidate
  (found or missing), the linker scripts and objects, and the program binary.
Before the next run the record is checked: every input must still have the
recorded state (sha256 of its bytes, "dir" or missing), every folder the
recorded names, every code file the same reachable code. Then the step is
skipped and its outputs are put back in their recorded state from a
content-addressed store of APFS clones (a later step may have changed a file
this step wrote, or the stage may have deleted it). Any difference, or an
untraced program started by the step, runs the step again.

A step's previous products do not count as inputs. A file read before it is
overwritten does count when an earlier step produces it.
"""
from contextlib import nullcontext
import concurrent.futures
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import code_key
import shared_cache

FORMAT = 3
# Pure content caches of the codecs: their files are keyed by the bytes they
# hold, so reading or writing them never changes a step's result.
PURE_CACHES = ('build/b1cache', 'build/lzsa1cache', 'build/lz16cache', 'build/hlzcache', 'build/host')
# Environment variables that differ between shells and never reach a step's output.
VOLATILE_ENVIRONMENT = {'_', 'PWD', 'OLDPWD', 'SHLVL', 'TERM_SESSION_ID', 'SECURITYSESSIONID',
                        'ITERM_SESSION_ID', 'TERM_PROGRAM_VERSION', 'STEP_TRACE_DIR', 'STEP_TRACE_IGNORE', 'STEP_TRACE_ROOTS', 'WOLF_SHARED_CACHE', 'WOLF_AUDIO_POOL', 'WOLF_AUDIO_WORKERS', 'WOLF_JOBS'}
STAGE = '@stage/'
# Records kept per step, newest first: undoing an edit finds the outputs of
# the earlier inputs again instead of running the step.
VERSIONS = 3


def sha_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


_clonefile = None


def clone(source, target):
    """Copy-on-write copy (APFS clonefile); a plain copy elsewhere."""
    global _clonefile
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.%d-%d.tmp' % (os.getpid(), threading.get_ident()))
    if temporary.exists():
        temporary.unlink()
    if _clonefile is None:
        try:
            _clonefile = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True).clonefile
        except (OSError, AttributeError):
            _clonefile = False
    if not _clonefile or _clonefile(os.fsencode(str(source)), os.fsencode(str(temporary)), 0) != 0:
        shutil.copyfile(source, temporary)
    os.replace(temporary, target)


class Hashes:
    """sha256 of files, reused while size, mtime, ctime and inode stay the same."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.table = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.table = {}
        self.dirty = False

    def state(self, path):
        """The sha256 of a file, 'dir', or None when the path does not exist."""
        try:
            info = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            return None
        if not os.path.isfile(path):
            return 'dir' if os.path.isdir(path) else 'other'
        signature = [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino]
        with self.lock:
            known = self.table.get(path)
        if known and known[:4] == signature:
            return known[4]
        digest = sha_file(path)
        with self.lock:
            self.table[path] = signature + [digest]
            self.dirty = True
        return digest

    def note(self, path, digest):
        info = os.stat(path)
        with self.lock:
            self.table[path] = [info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, digest]
            self.dirty = True

    def save(self):
        if self.dirty:
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.table, separators=(',', ':')))
            os.replace(temporary, self.path)
            self.dirty = False


def listing(path):
    try:
        return sorted(os.listdir(path))
    except (FileNotFoundError, NotADirectoryError):
        return None


INCLUDE = re.compile(r'^\s*#\s*include\s+["<]([^">]+)[">]', re.M)


def assembler_inputs(root, source, include_dirs):
    """Every file an as65816 run can read: the source and each #include,
    looked up in the including file's folder, the -I folders and the stage.
    Every candidate path is recorded (found or missing) and every file found
    is followed, whatever the assembler's search order is (a superset), so a
    new file that would shadow an include also starts the run again.
    Conditional includes are all followed."""
    root = Path(root)
    found = []
    pending = [root / source]
    seen = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        found.append(path)
        try:
            text = path.read_text(errors='replace')
        except FileNotFoundError:
            continue
        for name in INCLUDE.findall(text):
            for folder in [path.parent] + [root / d for d in include_dirs] + [root]:
                candidate = folder / name
                found.append(candidate)
                if candidate.is_file():
                    pending.append(candidate)
    return found


LOAD = re.compile(r'\(load\s+"([^"]+)"\)')


def linker_inputs(root, script):
    root = Path(root)
    found, pending = [], [root / script]
    while pending:
        path = pending.pop()
        if path in found:
            continue
        found.append(path)
        try:
            text = path.read_text(errors='replace')
        except FileNotFoundError:
            continue
        pending += [root / name for name in LOAD.findall(text)]
    return found


def folder_state(folder):
    """{path: (size, mtime_ns, ino)} of the files directly in a folder."""
    result = {}
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return result
    for entry in entries:
        if entry.is_file():
            info = entry.stat()
            result[entry.path] = (info.st_size, info.st_mtime_ns, info.st_ino)
    return result


class StepCache:
    def __init__(self, root, folder=None, log=print, jobs=None, source_root=None):
        self.root = Path(root).resolve()
        self.roots = {'@stage': str(self.root)}
        if source_root is not None:
            self.roots['@source'] = str(Path(source_root).resolve())
        self.relocated = {}
        self.folder = Path(folder or self.root / 'build/.stepcache').resolve()
        for name in ('steps', 'blobs', 'traces'):
            (self.folder / name).mkdir(parents=True, exist_ok=True)
        self.hashes = Hashes(self.folder / 'hashes.json')
        shared = shared_cache.folder()
        self.shared = shared_cache.SharedCache(shared) if shared else None
        if self.shared:
            for path in (self.folder / 'steps').glob('*.json'):
                for record in self.stored_versions(path):
                    self.shared.publish(path.stem, record, self.local_blob, clone)
        self.say = log
        self.jobs = jobs or int(os.environ.get('WOLF_JOBS') or os.cpu_count() or 1)
        self.ignore = [str(self.folder)] + [str(self.root / p) for p in PURE_CACHES]
        if shared:
            self.ignore.append(str(shared))
        self.stats = dict(skipped=0, ran=0, restored=0, shared_hits=0)
        self.times = []
        self.lock = threading.Lock()
        self.identity = dict(format=FORMAT, python=sys.version, executable=os.path.realpath(sys.executable))
        self.memmap_checked = {}
        self.profiles, self.loaders = {}, {}
        self.order = {}         # step key -> position in this build (set_plan)
        self.writers = {}       # output path -> positions of the steps that write it
        self.started = set()    # positions of the steps checked or run so far
        self.last = 0
        self.external_outputs = set()

    def completed_outputs(self, paths):
        """Protect outputs already made by a producer with its own cache."""
        self.external_outputs.update(str(Path(path).resolve()) for path in paths)

    # -- the order of a build ------------------------------------------------
    def set_plan(self, commands):
        """Every step of this build, in order. While a step runs, the files
        that only later steps write (or steps of an older build that this
        build no longer has) are absent, as in a build from an empty stage;
        a record is checked against the stage seen the same way."""
        self.order = {}
        for index, command in enumerate(commands):
            self.order.setdefault(self.key(command), index)
        self.last = len(commands)
        self.writers = {}
        if self.shared:
            for command in commands:
                path = self.folder / 'steps' / (self.key(command) + '.json')
                if not path.is_file():
                    records = list(self.shared.records(self.key(command)))
                    if records:
                        shared_cache.atomic(path, json.dumps(records).encode())
        # A fresh stage also needs the directories containing cached products.
        # Restore that skeleton before validating directory existence checks;
        # file contents are restored only when their producer is reached.
        # A record of another profile (same command) names folders this
        # profile never makes; their presence fails this profile's checks.
        # Only a product not made yet may differ from the record.
        if self.shared:
            directories = set()
            build = str(self.root / 'build') + '/'

            def holds(record):
                for path, state in record['inputs'].items():
                    now = self.hashes.state(path)
                    if now == state or self.same_relocated(path, state, now):
                        continue
                    if not (now is None and path.startswith(build)):
                        return False
                return True
            for command in commands:
                for record in self.versions(command):
                    if not holds(record):
                        continue
                    for name, state in record['outputs'].items():
                        path = Path(name)
                        if state is not None and str(path).startswith(str(self.root / 'build') + '/'):
                            directories.add(path if state == 'dir' else path.parent)
            for path in sorted(directories):
                path.mkdir(parents=True, exist_ok=True)
        # The prior format's products still belong to the matching producer.
        # Its record cannot be reused, but parallel replacements must not hide
        # one another's files before their new records have been collected.
        prior = dict(self.identity, format=2)
        prior_order = {self.key(command, prior): self.order[self.key(command)] for command in commands}
        for path in (self.folder / 'steps').glob('*.json'):
            index = self.order.get(path.stem, prior_order.get(path.stem, self.last))
            for record in self.stored_versions(path):
                for output, state in self.absolute(record)['outputs'].items():
                    if state not in (None, 'dir', 'other'):
                        self.writers.setdefault(output, set()).add(index)

    def hidden(self, path, index):
        """A file only steps after `index` (not started yet) write."""
        if index is None or path in self.external_outputs:
            return False
        writers = self.writers.get(path)
        return bool(writers) and min(writers) > index and not (writers & self.started)

    def hide_later(self, command):
        """Remove the files of later steps before a step runs (they are put
        back, or made again, when those steps come)."""
        index = self.order.get(self.key(command))
        if index is None:
            return 0
        removed = 0
        for path in list(self.writers):
            if self.hidden(path, index):
                try:
                    os.unlink(path)
                    removed += 1
                except (FileNotFoundError, IsADirectoryError, PermissionError):
                    pass
        return removed

    def mark(self, command):
        index = self.order.get(self.key(command))
        if index is not None:
            with self.lock:
                self.started.add(index)
        return index

    def drop_old_steps(self):
        """After a complete build: the records of steps this build no longer
        has, and the files only they wrote (unchanged since), are removed."""
        removed = 0
        planned = set(self.order)
        kept, old = set(self.external_outputs), []
        for path in (self.folder / 'steps').glob('*.json'):
            records = [self.absolute(r) for r in self.stored_versions(path)]
            if path.stem in planned:
                for record in records:
                    kept.update(record['outputs'])
            else:
                old.append((path, records))
        for path, records in old:
            for record in records:
                for output, state in record['outputs'].items():
                    if state in (None, 'dir', 'other') or output in kept:
                        continue
                    if self.hashes.state(output) == state:
                        os.unlink(output)
                        removed += 1
            path.unlink()
        return removed

    # -- records -----------------------------------------------------------
    def key(self, command, identity=None):
        """A step's name: its command, with the stage's own path as @stage."""
        words = [self.relative(str(v)) for v in command]
        if len(words) > 1 and words[1] == 'tools/audio_compile.py' and '--jobs' in words:
            words[words.index('--jobs') + 1] = '@workers'
        text = json.dumps([self.identity if identity is None else identity, words], sort_keys=True)
        return hashlib.sha1(text.encode()).hexdigest()

    @staticmethod
    def stored_versions(path):
        """The records in a step file (relative form), newest first."""
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else [data]

    def versions(self, command):
        path = self.folder / 'steps' / (self.key(command) + '.json')
        records = self.stored_versions(path)
        if self.shared:
            records += [r for r in self.shared.records(self.key(command)) if r not in records]
        return [self.absolute(r) for r in records if r.get('identity') == self.identity]

    def load(self, command):
        found = self.versions(command)
        return found[0] if found else None

    def stored(self, command):
        """The newest record of a step in relative form (data/palette-cache)."""
        found = self.stored_versions(self.folder / 'steps' / (self.key(command) + '.json'))
        return found[0] if found else None

    def save(self, command, record):
        path = self.folder / 'steps' / (self.key(command) + '.json')
        new = self.relative(record)
        same = {k: v for k, v in new.items() if k != 'seconds'}
        older = [r for r in self.stored_versions(path)
                 if {k: v for k, v in r.items() if k != 'seconds'} != same]
        temporary = path.with_suffix('.%d.tmp' % threading.get_ident())
        temporary.write_text(json.dumps([new] + older[:VERSIONS - 1], indent=0, sort_keys=True))
        os.replace(temporary, path)
        if self.shared:
            self.shared.publish(self.key(command), new, self.blob, clone)
        # A renamed command may now write files owned by a retired command.
        # Later steps must see these new products, rather than hiding them as
        # old outputs whose original producer is absent from this plan.
        index = self.order.get(self.key(command))
        if index is not None:
            with self.lock:
                for output, state in record['outputs'].items():
                    if state not in (None, 'dir', 'other'):
                        self.writers.setdefault(output, set()).add(index)

    def check(self, command, env, index):
        """The newest record that still holds (made the newest), and the
        reason the newest record fails when none holds."""
        found = self.versions(command)
        if not found:
            return None, 'no record'
        reason = None
        for number, record in enumerate(found):
            why = self.why_not(record, env, index)
            if why is None:
                if self.shared:
                    missing = next((state for state in record['outputs'].values()
                                    if state not in (None, 'dir', 'other')
                                    and self.hashes.state(str(self.blob(state))) != state), None)
                    if missing:
                        reason = reason or 'missing or damaged shared output'
                        continue
                if number:
                    # Files only the newer run made go, as in an empty stage.
                    self.drop_stale(found[0], record)
                    self.save(command, record)
                if self.shared:
                    # Keep stage-local ownership metadata, never a second blob store.
                    self.save(command, record)
                    with self.lock:
                        self.stats['shared_hits'] += 1
                return record, None
            reason = reason or why
        return None, reason

    def relative(self, record):
        def change(text):
            for token, root in self.roots.items():
                text = token if text == root else text.replace(root + '/', token + '/')
            return text
        return self._map(record, change)

    def absolute(self, record):
        def change(text):
            for token, root in self.roots.items():
                text = root if text == token else text.replace(token + '/', root + '/')
            return text
        result = self._map(record, change)
        # Older records may have treated a content cache as a step output.
        # Such files must also stay out of the later-writer deletion plan.
        for field in ('inputs', 'stats', 'listings', 'outputs'):
            if field in result:
                result[field] = {path: state for path, state in result[field].items()
                                 if not self.ignored(path)}
        return result

    def _map(self, value, change):
        if isinstance(value, dict):
            return {change(k) if isinstance(k, str) else k: (v if k == 'origins' else self._map(v, change))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [self._map(v, change) for v in value]
        if isinstance(value, str):
            return change(value)
        return value

    def ignored(self, path):
        return any(path == p or path.startswith(p + '/') for p in self.ignore)

    # -- checking ----------------------------------------------------------
    def why_not(self, record, env, index=None):
        """None when the record still holds, else the first difference.
        index: the step's position; files only later steps write count as
        absent (set_plan)."""
        if record.get('identity') != self.identity:
            return 'other Python or cache format'
        if not record.get('inputs') and not (record.get('code') or {}).get('files'):
            return 'no verifiable inputs'
        if record.get('opaque'):
            return 'untraced program ' + ' '.join(record['opaque'][0])[:80]
        if index is not None and not record.get('overwrites_traced'):
            for path, state in record['outputs'].items():
                if state not in (None, 'dir', 'other') and any(
                        writer < index for writer in self.writers.get(path, ())):
                    return 'overwritten inputs not traced: ' + self.short(path)
        for name, value in record.get('env', {}).items():
            if env.get(name) != value:
                return 'environment ' + name
        for path, state in record['inputs'].items():
            now = self.hashes.state(path)
            if now != state and not (state is None and self.hidden(path, index)) and not self.same_relocated(path, state, now):
                return 'changed ' + self.short(path)
        for path, state in record.get('sources', {}).items():
            from source_identity import source_digest
            try:
                same = source_digest(path) == state
            except (OSError, SyntaxError, ValueError):
                same = False
            if not same:
                return 'source changed ' + self.short(path)
        for path, state in record.get('stats', {}).items():
            if (code_key.stat_state(path) != state and not (state is None and self.hidden(path, index))
                    and not self.same_relocated_stat(path, state)):
                return 'changed ' + self.short(path) + ' (exists/size)'
        outputs = record['outputs']
        for path, names in record.get('listings', {}).items():
            now = listing(path)
            if now is not None:
                now = [n for n in now if os.path.join(path, n) not in outputs
                       and not self.hidden(os.path.join(path, n), index)]
            if now != names:
                return 'folder ' + self.short(path)
        code = record.get('code')
        if code:
            names = None
            for path, entry in code['files'].items():
                if path.endswith(code_key.TRACER_FILES):
                    continue
                state = self.hashes.state(path)
                if state == entry['sha']:
                    continue
                if state in (None, 'dir', 'other'):
                    return 'code missing ' + self.short(path)
                names = names if names is not None else set(code['names'])
                try:
                    same = code_key.still_valid(path, state, entry, names)
                except SyntaxError:
                    same = False
                if not same:
                    return 'code changed ' + self.short(path)
                if entry.get('data') and record.get('memmap'):
                    keys = tuple(sorted(record['memmap']))
                    if (path, state, keys) not in self.memmap_checked:
                        self.memmap_checked[path, state, keys] = code_key.memmap_values(path, keys)
                    if self.memmap_checked[path, state, keys] != record['memmap']:
                        return 'memmap values changed'
        elf = record.get('elf')
        if elf:
            for path, keys in elf['files'].items():
                state = self.hashes.state(path)
                if state is not None and code_key.fingerprint(state) == keys.get('#sha'):
                    continue
                if state is None:
                    return 'missing ' + self.short(path)
                try:
                    now = code_key.elf_values(elf['tool'], path, sorted(keys))
                except (OSError, ValueError, KeyError, IndexError) as error:
                    return 'ELF unreadable ' + self.short(path) + ': ' + str(error)
                now['#sha'] = keys.get('#sha')
                if now != keys:
                    return 'ELF values changed ' + self.short(path) + ' ' + ', '.join(
                        sorted(k for k in keys if now.get(k) != keys[k]))[:120]
        toml = record.get('toml')
        if toml:
            for root, keys in toml['roots'].items():
                files = {k[6:]: v for k, v in keys.items() if k.startswith('#file:')}
                if files and all(self.hashes.state(f) == v for f, v in files.items()):
                    continue
                parts = self.profile_parts(toml['tool'], root)
                if isinstance(parts, Exception):
                    return 'profile does not load: ' + str(parts)[:120]
                now = code_key.toml_values(parts, keys)
                changed = sorted(k for k in now if now[k] != keys[k])
                if changed:
                    return 'profile values changed ' + ', '.join(changed)[:120]
        for path, state in outputs.items():
            if state not in (None, 'dir', 'other') and not self.blob(state).is_file():
                if self.hashes.state(path) != state:
                    return 'lost output ' + self.short(path)
        return None

    def profile_parts(self, tool, root):
        """A profile root loaded again with the stage's game_profile (once per
        build and file state); an exception when it no longer loads."""
        key = (tool, self.hashes.state(tool), root)
        if key not in self.profiles:
            try:
                if (tool, key[1]) not in self.loaders:
                    self.loaders[tool, key[1]] = code_key.load_tool(tool, '_game_profile_for_cache')
                self.profiles[key] = code_key.toml_parts(self.loaders[tool, key[1]], root)
            except Exception as error:  # a profile that fails to load is a change
                self.profiles[key] = error
        return self.profiles[key]

    def same_relocated(self, path, before, now):
        return self.relocated.get(path, {}).get(before) == now and now is not None

    def same_relocated_stat(self, path, state):
        if not isinstance(state, str) or not state.startswith('file:'):
            return False
        now = self.hashes.state(path)
        for old, new in self.relocated.get(path, {}).items():
            if now == new and self.blob(old).stat().st_size == int(state[5:]):
                return True
        return False

    def put_back(self, record):
        """Give every output its recorded state (from the clone store)."""
        restored = 0
        for path, state in record['outputs'].items():
            current = self.hashes.state(path)
            if current == state or state == 'other':
                continue
            if state is None:
                if current == 'dir':
                    continue  # a folder the step removed and another step made again
                os.unlink(path)
            elif state == 'dir':
                os.makedirs(path, exist_ok=True)
            else:
                if current == 'dir':
                    raise ValueError('step cache: a folder is where a file was: ' + path)
                clone(self.blob(state), path)
                self.hashes.note(path, state)
            restored += 1
        if record.get('origins') and record['origins'] != self.roots:
            from cache_paths import relocate
            changed = relocate(record['outputs'], record['origins'], self.roots)
            for path, state in changed.items():
                old = record['outputs'][path]
                self.relocated.setdefault(path, {})[old] = state
                self.keep(path, state)
        with self.lock:
            self.stats['restored'] += restored
        return restored

    def local_blob(self, state):
        return self.folder / 'blobs' / state[:2] / state

    def blob(self, state):
        return self.shared.blob(state) if self.shared else self.local_blob(state)

    def keep(self, path, state):
        if state in (None, 'dir', 'other'):
            return
        blob = self.blob(state)
        if self.hashes.state(str(blob)) != state:
            clone(path, blob)
            self.hashes.note(str(blob), state)

    def short(self, path):
        path = str(path)
        return path[len(str(self.root)) + 1:] if path.startswith(str(self.root) + '/') else path

    def skip(self, command, env, label, quiet=False):
        """Put back a step's outputs when its record holds; else the reason."""
        index = self.mark(command)
        record, reason = self.check(command, env, index)
        if reason is None:
            restored = self.put_back(record)
            with self.lock:
                self.stats['skipped'] += 1
            if not quiet:
                self.say('Build: unchanged ' + label + (' (%d outputs put back)' % restored if restored else ''))
        return reason

    def drop_stale(self, old, new):
        """Remove what an older run of a step wrote and this run did not: a
        build from an empty stage would not have it."""
        if old is None:
            return
        for path, state in old['outputs'].items():
            if path in new['outputs'] or state in (None, 'dir', 'other'):
                continue
            if self.hashes.state(path) == state:
                os.unlink(path)

    def parallel(self, commands, env, log, title, adopt=None):
        """Python steps that do not depend on each other, self.jobs at a time.
        adopt(command, reason) may supply a step's outputs (a seed) instead."""
        began = time.monotonic()
        todo, kept, adopted = [], 0, 0
        for command in commands:
            reason = self.skip(command, env, '', quiet=True)
            if reason is None:
                kept += 1
            elif adopt is not None and adopt(command, reason):
                adopted += 1
            else:
                todo.append((command, reason))
        logs, executed = {}, {}
        if todo:
            with tempfile.TemporaryDirectory(dir=self.folder) as folder:
                results = {}

                def work(item):
                    command, reason = item
                    path = Path(folder) / (self.key(command) + '.log')
                    try:
                        with path.open('w', encoding='utf-8') as output:
                            executed[' '.join(map(str, command))] = self.python(command, env, output, reason)
                    finally:
                        results[' '.join(map(str, command))] = path.read_text()
                failure = None
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.jobs) as pool:
                    for future in [pool.submit(work, item) for item in todo]:
                        try:
                            future.result()
                        except Exception as error:
                            failure = failure or error
            with log.open('a', encoding='utf-8') as output:
                for command, _ in todo:
                    line = ' '.join(map(str, command))
                    output.write('Build: ' + line + '\n' + results.get(line, ''))
            if failure:
                raise failure
        ran = sum(executed.values())
        kept += len(todo) - ran
        self.say('Build: %s: %d unchanged, %d from the seed, %d run (%d at a time) in %.1f s'
                 % (title, kept, adopted, ran, self.jobs, time.monotonic() - began))
        return ran

    # -- Python steps --------------------------------------------------------
    def python(self, command, env, output, reason=None):
        with self.shared.lock(self.key(command)) if self.shared else nullcontext():
            # Another stage may have completed while this one waited.
            return self._python(command, env, output,
                                reason if reason == 'required every build' else None)

    def _python(self, command, env, output, reason=None):
        """Run a Python step under the tracer unless its record still holds."""
        began = time.monotonic()
        command = [str(v) for v in command]
        label = ' '.join(command[1:])
        reason = reason or self.skip(command, env, label)
        if reason is None:
            self.times.append((label, time.monotonic() - began, 'skipped'))
            return False
        self.say('Build: ' + ' '.join(command) + '   [' + reason + ']')
        self.mark(command)
        self.hide_later(command)
        previous = self.load(command)
        trace = Path(tempfile.mkdtemp(prefix='trace-', dir=self.folder / 'traces'))
        step_env = dict(env)
        step_env['STEP_TRACE_DIR'] = str(trace)
        step_env['STEP_TRACE_IGNORE'] = os.pathsep.join(list(self.ignore) + ([env['WOLF_AUDIO_POOL']] if env.get('WOLF_AUDIO_POOL') else []))
        step_env['STEP_TRACE_ROOTS'] = os.pathsep.join(self.roots.values())
        hook = str(self.root / 'tools/steptrace')
        step_env['PYTHONPATH'] = hook + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        try:
            subprocess.run(command, cwd=self.root, env=step_env, stdout=output, stderr=subprocess.STDOUT, check=True)
            record = self.collect(trace, env, self.order.get(self.key(command)))
        finally:
            shutil.rmtree(trace, ignore_errors=True)
        self.drop_stale(previous, record)
        record['seconds'] = round(time.monotonic() - began, 3)
        self.save(command, record)
        with self.lock:
            self.stats['ran'] += 1
        self.times.append((label, time.monotonic() - began, 'ran'))
        return True

    def collect(self, trace, env, index=None):
        reads, writes, listings, environment, opaque = {}, {}, {}, {}, []
        code, values, elf, toml, stats, sources = {}, {}, {}, {}, {}, {}
        complete = True
        for path in sorted(trace.glob('*.trace')):
            lines = path.read_text().splitlines()
            if not lines or lines[-1] != '["end"]':
                complete = False
            for line in lines:
                item = json.loads(line)
                kind = item[0]
                if kind == 'r':
                    _, name, state, when = item
                    if name not in reads or when < reads[name][1]:
                        reads[name] = (state, when)
                elif kind == 'c':
                    code.setdefault(item[1], item[2])
                elif kind == 'p':
                    sources.setdefault(item[1], item[2])
                elif kind == 'w':
                    _, name, when = item
                    if name not in writes or when < writes[name]:
                        writes[name] = when
                elif kind == 'l':
                    _, name, names, when = item
                    if name not in listings or when < listings[name][1]:
                        listings[name] = (names, when)
                elif kind == 'v':
                    values.setdefault(item[1], item[2])
                elif kind == 'y':
                    elf.setdefault(item[1], {}).setdefault(item[2], item[3])
                elif kind == 't':
                    toml.setdefault(item[1], {}).setdefault(item[2], item[3])
                elif kind == 's':
                    _, name, state, when = item
                    if name not in stats or when < stats[name][1]:
                        stats[name] = (state, when)
                elif kind == 'e':
                    if item[1] not in VOLATILE_ENVIRONMENT:
                        environment.setdefault(item[1], item[2])
                elif kind == 'x':
                    opaque.append(item[1])
        if not complete:
            opaque.append(['(a traced process did not finish)'])
        outputs = {}
        for name in writes:
            if self.ignored(name):
                continue
            state = self.hashes.state(name)
            outputs[name] = state
            self.keep(name, state)
        inputs = {name: state for name, (state, when) in reads.items()
                  if not self.ignored(name) and (name not in writes or
                      when < writes[name] and index is not None and any(
                          writer < index for writer in self.writers.get(name, ())))}
        sources = {name: state for name, state in sources.items()
                   if not self.ignored(name) and name not in writes and name not in inputs}
        # An existence check counts by kind and size; a read of the same file
        # counts by its bytes.
        stats = {name: state for name, (state, when) in stats.items()
                 if not self.ignored(name) and name not in writes and name not in inputs and name not in sources}
        folders = {}
        for name, (names, when) in listings.items():
            if self.ignored(name) or name in writes:
                continue
            folders[name] = None if names is None else [n for n in names if os.path.join(name, n) not in writes]
        code = {name: state for name, state in code.items()
                if not self.ignored(name) and name not in writes and state not in (None, 'dir')}
        # Third-party packages are immutable build inputs, not editable project
        # functions. Hash them whole without parsing their symbol graphs.
        external = {name: state for name, state in code.items()
                    if not any(name.startswith(root + os.sep) for root in self.roots.values())}
        inputs.update(external)
        code = {name: state for name, state in code.items() if name not in external}
        # memmap is keyed on the values the step read only when it was read
        # through the recording module (imported as memmap); run as a script,
        # it is code like any other.
        data = {name for name in code if code_key.is_memmap(name) and values.get('#memmap') == name}
        names, entries = code_key.analyze(code, data=data)
        memmap = dict(values) if data else {}
        for name in data:
            module = code_key.parse(name, code[name], True)
            wanted = sorted(code_key.memmap_globals(module, names) - set(module.defs))
            memmap.update(code_key.memmap_values(name, wanted))
        # An ELF read through tools/elf.py counts by the symbols and segment
        # fields the step looked at; read any other way it counts whole.
        elf = {name: keys for name, keys in elf.items()
               if not self.ignored(name) and name not in writes and name not in inputs}
        tool = next((name for name in code if name.endswith('/tools/elf.py')), None)
        if elf and tool is None:
            inputs.update({name: self.hashes.state(name) for name in elf})
            elf = {}
        # The interpreter reads PYTHONHASHSEED itself (set order depends on it).
        environment.setdefault('PYTHONHASHSEED', env.get('PYTHONHASHSEED'))
        # Profiles read by value: checked by loading them again with game_profile.
        loader = next((name for name in code if name.endswith('/tools/game_profile.py')), None)
        if toml and loader is None:
            for keys in toml.values():
                inputs.update({k[6:]: v for k, v in keys.items() if k.startswith('#file:')})
            toml = {}
        return dict(identity=self.identity, origins=dict(self.roots), inputs=inputs, sources=sources, stats=stats, listings=folders,
                    env={k: (env.get(k) if k in env else v) for k, v in environment.items()},
                    outputs=outputs, opaque=opaque, overwrites_traced=True,
                    code=dict(names=sorted(names), files=entries), memmap=memmap,
                    elf=dict(tool=tool, files=elf) if elf else {},
                    toml=dict(tool=loader, roots=toml) if toml else {})

    # -- ordered Python steps, in parallel where their files allow ------------
    @staticmethod
    def files_of(record):
        """(reads, listed folders, writes) of a record; None without one."""
        if record is None or record.get('opaque'):
            return None
        reads = set(record['inputs']) | set(record.get('stats', {})) | set((record.get('code') or {}).get('files', {}))
        reads |= set(record.get('sources', {}))
        reads |= set((record.get('elf') or {}).get('files', {}))
        writes = {path for path, state in record['outputs'].items() if state != 'dir'}
        return reads, set(record.get('listings', {})), writes

    @staticmethod
    def conflict(first, second):
        """Two steps that must keep their order: one writes a file the other
        reads, lists or writes. Unknown files (no record) always conflict."""
        if first is None or second is None:
            return True
        r1, l1, w1 = first
        r2, l2, w2 = second
        if w1 & (r2 | w2) or w2 & r1:
            return True
        return any(os.path.dirname(p) in l2 for p in w1) or any(os.path.dirname(p) in l1 for p in w2)

    def run_steps(self, commands, env, log):
        """Python steps in recipe order. Two steps run at the same time when
        their last records share no file (tools/step_cache.conflict); a step
        without a record waits for every step before it, and every step after
        it waits for it. The new records are checked the same way: when two
        steps that ran side by side touched a common file, every step from
        the first of them on is checked (and run) again in order, so the
        result is the result of the plain order."""
        commands = [[str(v) for v in c] for c in commands]
        count = len(commands)
        # A changed step can start writing files absent from its old record.
        # Treat that output set as unknown until the step has run again.
        records = [self.load(c) for c in commands]
        before = [self.files_of(record) if record is not None and
                  self.why_not(record, env, self.order.get(self.key(command))) is None else None
                  for command, record in zip(commands, records)]
        waits = [[j for j in range(i) if self.conflict(before[j], before[i])] for i in range(count)]
        ancestors = []
        for i in range(count):
            found = set(waits[i])
            for j in waits[i]:
                found |= ancestors[j]
            ancestors.append(found)
        logs = {}
        with tempfile.TemporaryDirectory(dir=self.folder) as folder:
            def work(i):
                path = Path(folder) / ('%03d.log' % i)
                try:
                    with path.open('w', encoding='utf-8') as output:
                        self.python(commands[i], env, output)
                finally:
                    logs[i] = path.read_text()
            futures = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.jobs) as pool:
                def start(i):
                    for j in waits[i]:
                        futures[j].result()
                    work(i)
                # Submit in order: a step only waits for steps submitted before it.
                for i in range(count):
                    futures[i] = pool.submit(start, i)
                failure = None
                for i in range(count):
                    try:
                        futures[i].result()
                    except Exception as error:
                        failure = failure or error
            with log.open('a', encoding='utf-8') as output:
                for i in range(count):
                    if logs.get(i):
                        output.write(logs[i])
            if failure:
                raise failure
        after = [self.files_of(self.load(c)) for c in commands]
        first = None
        for i in range(count):
            for j in range(i):
                if j not in ancestors[i] and self.conflict(after[j], after[i]):
                    first = j if first is None else min(first, j)
        if first is not None:
            self.say('Build: steps that ran side by side shared files; checking again from ' + ' '.join(commands[first][1:]))
            with log.open('a', encoding='utf-8') as output:
                for i in range(first, count):
                    self.python(commands[i], env, output)

    # -- assembler and linker -----------------------------------------------
    def tool(self, command, inputs, outputs=None, folder=None):
        with self.shared.lock(self.key(command)) if self.shared else nullcontext():
            return self._tool(command, inputs, outputs, folder)

    def _tool(self, command, inputs, outputs=None, folder=None):
        """Run a program with known inputs. Outputs: the listed paths, or the
        files that the run changed in `folder`."""
        began = time.monotonic()
        command = [str(v) for v in command]
        label = Path(command[0]).name + ' ' + command[-1]
        index = self.mark(command)
        record, reason = self.check(command, {}, index)
        if reason is None:
            restored = self.put_back(record)
            with self.lock:
                self.stats['skipped'] += 1
            self.times.append((label, time.monotonic() - began, 'skipped'))
            return 'Build: unchanged ' + ' '.join(command) + (' (%d outputs put back)' % restored if restored else ''), None
        self.hide_later(command)
        before = folder_state(self.root / folder) if folder else None
        result = subprocess.run(command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, command, result.stdout)
        if folder:
            after = folder_state(self.root / folder)
            outputs = [path for path, info in after.items() if before.get(path) != info]
        program = shutil.which(command[0]) or command[0]
        record = dict(identity=self.identity, origins=dict(self.roots),
                      inputs={str(p): self.hashes.state(str(p)) for p in [Path(program)] + list(inputs)},
                      listings={}, env={}, outputs={}, opaque=[], overwrites_traced=True)
        for path in outputs:
            path = str(self.root / path)
            state = self.hashes.state(path)
            record['outputs'][path] = state
            self.keep(path, state)
        record['seconds'] = round(time.monotonic() - began, 3)
        self.save(command, record)
        with self.lock:
            self.stats['ran'] += 1
        self.times.append((label, time.monotonic() - began, 'ran'))
        return 'Build: ' + ' '.join(command) + '   [' + reason + ']', result.stdout

    def tools(self, work, log):
        """Run (command, inputs, outputs, folder) jobs in parallel; log in order."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.jobs) as pool:
            futures = [pool.submit(self.tool, *job) for job in work]
            failure = None
            with log.open('a', encoding='utf-8') as handle:
                for future in futures:
                    try:
                        line, text = future.result()
                    except subprocess.CalledProcessError as error:
                        handle.write('Build: ' + ' '.join(map(str, error.cmd)) + '\n')
                        handle.write((error.output or b'').decode(errors='replace'))
                        failure = failure or error
                        continue
                    if text is not None:
                        self.say(line)
                    handle.write(line + '\n')
                    if text:
                        handle.write(text.decode(errors='replace'))
        if failure:
            raise failure

    def assemble(self, assembler, flags, include_dirs, jobs, log):
        """jobs: (source, object, extra flags). Parallel, unchanged objects kept."""
        work = []
        for source, obj, extra in jobs:
            command = [assembler] + flags + extra + ['-o', obj, source]
            work.append((command, assembler_inputs(self.root, source, include_dirs), [obj], None))
        self.tools(work, log)

    def link(self, linker, script, objects, arguments, log):
        """The outputs are the files the run changes in the -o folder."""
        target = arguments[arguments.index('-o') + 1]
        inputs = linker_inputs(self.root, script) + [self.root / o for o in objects]
        self.tools([([linker] + arguments, inputs, None, str(Path(target).parent))], log)

    # -- end -------------------------------------------------------------------
    def summary(self, seconds):
        ran = sorted((t for t in self.times if t[2] == 'ran'), key=lambda t: -t[1])
        return dict(seconds=round(seconds, 1), **self.stats,
                    slowest_runs=[dict(step=n, seconds=round(s, 2)) for n, s, _ in ran[:10]])

    def finish(self):
        """Save the file hashes (of files that still exist) and drop clones
        that no record uses."""
        with self.hashes.lock:
            gone = [path for path in self.hashes.table if not os.path.exists(path)]
            for path in gone:
                del self.hashes.table[path]
            self.hashes.dirty = self.hashes.dirty or bool(gone)
        self.hashes.save()
        if self.shared:
            return 0  # Other stages own shared records; no per-build shared GC.
        used = set()
        for path in (self.folder / 'steps').glob('*.json'):
            for record in self.stored_versions(path):
                used.update(v for v in record['outputs'].values() if v not in (None, 'dir', 'other'))
        removed = 0
        for blob in (self.folder / 'blobs').glob('*/*'):
            if blob.name not in used and not blob.name.endswith('.tmp'):
                blob.unlink()
                removed += 1
        return removed
