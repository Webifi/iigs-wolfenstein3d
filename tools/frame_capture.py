"""Retain exact frame hashes after a completed renderer comparison.

Raw captures are scratch output. Successful paired comparisons compact them;
failed comparisons keep them for diagnosis. Identical streams share one small
JSON hash index. No disk image, sound recording, or emulator state is changed.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile

FRAME_BYTES = 32000
STORE = Path(__file__).resolve().parents[1] / 'build/tests/frame-hashes'


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        json.dump(value, f, indent=2)
        f.write('\n')
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _identity(path):
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns


def _raw_index(path):
    original = _identity(path)
    whole = hashlib.sha256()
    hashes = []
    with path.open('rb') as f:
        while frame := f.read(FRAME_BYTES):
            if len(frame) != FRAME_BYTES:
                raise ValueError(f'Partial frame in {path}')
            whole.update(frame)
            hashes.append(hashlib.sha256(frame).hexdigest())
    if not hashes or original != _identity(path):
        raise ValueError(f'Empty or changing capture: {path}')
    return dict(format=1, frame_bytes=FRAME_BYTES, frames=len(hashes),
                bytes=original[2], sha256=whole.hexdigest(), frame_sha256=hashes)


def _saved_index(path):
    pointer = json.loads(path.with_name(path.name + '.json').read_text())
    contents = (path.parent / pointer['index']).read_bytes()
    if hashlib.sha256(contents).hexdigest() != pointer['index_sha256']:
        raise ValueError(f'Damaged frame hash index for {path}')
    index = json.loads(contents)
    if (index['format'] != 1 or index['frame_bytes'] != FRAME_BYTES
            or index['sha256'] != pointer['sha256']
            or index['frames'] != pointer['frames']
            or index['bytes'] != index['frames'] * FRAME_BYTES
            or len(index['frame_sha256']) != index['frames']):
        raise ValueError(f'Invalid frame hash index for {path}')
    return index


def capture_index(path):
    """Read hashes from a raw stream or its retained index."""
    path = Path(path)
    return _raw_index(path) if path.exists() else _saved_index(path)


def read_frame(path, number):
    """Return one raw frame, or None when only hashes have been retained."""
    path = Path(path)
    if not path.exists():
        return None
    with path.open('rb') as f:
        f.seek((number - 1) * FRAME_BYTES)
        frame = f.read(FRAME_BYTES)
    if len(frame) != FRAME_BYTES:
        raise ValueError(f'Missing frame {number}: {path}')
    return frame


def compact_capture(path, store=STORE):
    """Remove a closed stream only after its complete hash index is verified.

    The caller must first persist its comparison and any needed failure samples.
    This function does not decide whether a failed trial has been resolved.
    """
    path = Path(path)
    if path.name != 'frames.pixels' or path.is_symlink():
        raise ValueError(f'Not a regular renderer capture: {path}')
    path = path.parent.resolve() / path.name
    if not path.exists():
        _saved_index(path)
        return dict(removed_files=0, removed_allocated_bytes=0)
    original = _identity(path)
    allocation = getattr(path.stat(), 'st_blocks', 0) * 512
    index = _raw_index(path)
    result = json.loads((path.parent / 'result.json').read_text())
    if result['frames'] != index['frames']:
        raise ValueError(f'Capture/result frame count differs: {path}')
    target = Path(store).resolve() / (index['sha256'] + '.json')
    if target.exists():
        if json.loads(target.read_text()) != index:
            raise ValueError(f'Conflicting frame hash index: {target}')
    else:
        _write_json(target, index)
    pointer = dict(format=1, raw_removed=True, frames=index['frames'],
                   sha256=index['sha256'], index=os.path.relpath(target, path.parent),
                   index_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    _write_json(path.with_name(path.name + '.json'), pointer)
    if _saved_index(path) != index or original != _identity(path):
        raise ValueError(f'Capture changed during compaction: {path}')
    path.unlink()
    return dict(removed_files=1, removed_allocated_bytes=allocation)


def clean_paint_result(case):
    """Only automatically prune runs whose transient-write check also passed."""
    summary = json.loads((case.parent / 'summary.json').read_text())
    rows = [r for r in summary['cases'] if f'd{r["demo"]}-v{r["view"]}' == case.name]
    return len(rows) == 1 and rows[0]['wrong_bytes'] == rows[0]['exposed_bytes'] == 0
