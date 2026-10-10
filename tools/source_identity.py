"""Semantic fingerprints for compiler source and parsed configuration files."""
import ast
import functools
import hashlib
import inspect
import json
from pathlib import Path

from code_key import WithoutDocstrings


def source_bytes(path):
    """Read a declared code dependency; ordinary file reads remain byte keyed."""
    path = Path(path)
    info = path.stat()
    return _source_bytes(path, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))[1]


@functools.lru_cache(maxsize=1024)
def _source_bytes(path, state):
    with open(path, 'rb') as handle:
        data = handle.read()
    if path.suffix == '.py':
        tree = WithoutDocstrings().visit(ast.parse(data, filename=str(path)))
        return data, ast.dump(tree, include_attributes=False).encode()
    if path.suffix == '.toml':
        from game_profile import tomllib
        return data, json.dumps(tomllib.loads(data.decode('utf-8')), default=str).encode()
    return data, data


def source_digest(path):
    return hashlib.sha256(source_bytes(path)).hexdigest()


def function_source(function):
    """Original function text for code generation, keyed as Python code."""
    function = inspect.unwrap(function)
    with open(function.__code__.co_filename, encoding='utf-8') as handle:
        lines = handle.readlines()
    return ''.join(inspect.getblock(lines[function.__code__.co_firstlineno-1:]))
