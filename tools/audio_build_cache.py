"""Content-based producer stages: input identity plus verified output identity."""
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import time


def file_version(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=65536)
def checked_digest(path, version):
    h = hashlib.sha256()
    with Path(path).open('rb') as file:
        if file_version(os.fstat(file.fileno())) != version:
            raise ValueError('Build file changed before hashing: '+path)
        for block in iter(lambda: file.read(1024*1024), b''):
            h.update(block)
        if file_version(os.fstat(file.fileno())) != version:
            raise ValueError('Build file changed while hashing: '+path)
    return h.hexdigest()


def digest(path):
    # Full-track captures are checked once per process. Even same-size edits
    # with restored modification times invalidate the cached hash via ctime.
    path = Path(path).resolve()
    return checked_digest(str(path), file_version(path.stat()))


def inputs(paths, *, exclude_dirs=(), **values):
    files = {}
    for value in paths:
        path = Path(value).resolve()
        if path.is_dir():
            selected = sorted(p for p in path.rglob('*') if p.is_file()
                              and '__pycache__' not in p.parts
                              and not set(p.relative_to(path).parts[:-1]).intersection(exclude_dirs))
        elif path.is_file():
            selected = [path]
        else:
            raise ValueError('Missing build dependency: '+str(path))
        for p in selected:
            files[str(p)] = digest(p)
    return dict(files=files, values=values)


def outputs(folder):
    return {str(p.relative_to(folder)):digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and p.name != '.stage.json' and '__pycache__' not in p.parts}


def stage(root, name, dependencies, action):
    key = hashlib.sha256(json.dumps(dependencies, sort_keys=True).encode()).hexdigest()
    folder = Path(root)/'.audio-cache'/name/key
    marker = folder/'.stage.json'
    old = None
    if marker.is_file():
        try:
            old = json.loads(marker.read_text())
        except (OSError, ValueError):
            pass
    if old and old['inputs'] == dependencies and old['outputs'] == outputs(folder):
        print('Validated cached inputs and outputs: '+name, flush=True)
        return folder, False
    if folder.exists():
        # Preserve edits, failed evidence and corrupt artifacts for inspection.
        folder.rename(folder.with_name(key+'.stale-'+str(time.time_ns())))
    folder.mkdir(parents=True)
    print('Building: '+name, flush=True)
    action(folder)
    verify_inputs(dependencies)
    checked = outputs(folder)
    if not checked:
        raise ValueError('Build stage produced no files: '+name)
    marker.write_text(json.dumps(dict(inputs=dependencies, outputs=checked), indent=2)+'\n')
    return folder, True


def verify_inputs(value):
    """Reject a build that observed changing source/compiler files mid-stage."""
    if isinstance(value,dict):
        for name,expected in value.get('files',{}).items():
            path=Path(name)
            if not path.is_file() or digest(path)!=expected:
                raise ValueError('Build input changed during stage: '+name)
        for key,child in value.items():
            if key!='files':verify_inputs(child)
    elif isinstance(value,list):
        for child in value:verify_inputs(child)
