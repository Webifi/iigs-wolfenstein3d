"""Immutable results shared by independent build stages on this host.

WOLF_SHARED_CACHE selects the directory; empty or 0 disables sharing. Only
complete files are published. Locks are per command or codec input, released
by the OS if a builder exits. No shared index is rewritten or garbage-collected
by a build. Stage-local traces and file-stat memoization stay in .stepcache.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


def folder():
    value = os.environ.get('WOLF_SHARED_CACHE')
    return Path(value).expanduser().resolve() if value and value != '0' else None


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class SharedCache:
    def __init__(self, root):
        self.root = Path(root) / 'v1'
        self.parsed = {}

    def blob(self, digest):
        return self.root / 'blobs' / digest[:2] / digest

    def lock(self, key):
        return locked(self.root / 'locks' / (key + '.lock'))

    def records(self, key):
        for path in sorted((self.root / 'steps' / key).glob('*.json')):
            try:
                if path in self.parsed:
                    yield self.parsed[path]
                    continue
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() == path.stem:
                    record = json.loads(data)
                    if isinstance(record, dict):
                        self.parsed[path] = record
                        yield record
            except (OSError, ValueError):
                continue

    def publish(self, key, record, source, copy):
        if record.get('opaque') or any(not p.startswith('@stage/') for p in record['outputs']):
            return
        # A result is visible only after every referenced blob exists.
        data = json.dumps({k: v for k, v in record.items() if k != 'seconds'},
                          sort_keys=True, separators=(',', ':')).encode()
        path = self.root / 'steps' / key / (hashlib.sha256(data).hexdigest() + '.json')
        if path.is_file():
            return
        for state in set(record['outputs'].values()):
            if state in (None, 'dir', 'other'):
                continue
            target = self.blob(state)
            if not target.is_file():
                origin = source(state)
                if not origin.is_file():
                    return  # a partially pruned legacy stage is not a result
                copy(origin, target)
        atomic(path, data)


def codec_path(namespace, identity, data):
    root = folder()
    if root is None:
        return None
    key = hashlib.sha256(identity + data).hexdigest()
    return SharedCache(root).root / 'codecs' / namespace / key[:2] / key


def codec(namespace, identity, data, encode):
    """A pure encoder result, keyed by its implementation and all input bytes."""
    root = folder()
    if root is None:
        return encode()
    key = hashlib.sha256(identity + data).hexdigest()
    cache = SharedCache(root)
    path = codec_path(namespace, identity, data)
    with cache.lock(namespace + '-' + key):
        if path.is_file():
            packed = path.read_bytes()
            # The prefix detects truncated or corrupted entries.
            if len(packed) >= 32 and hashlib.sha256(packed[32:]).digest() == packed[:32]:
                return packed[32:]
        result = encode()
        atomic(path, hashlib.sha256(result).digest() + result)
        return result
