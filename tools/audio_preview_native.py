"""Optional exact C loop for the DOC preview's float buffers."""
import ctypes
import functools
import hashlib
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

@functools.lru_cache(maxsize=1)
def library():
    if os.environ.get('WOLF_HOST_NATIVE', '1') == '0':
        return None
    source = Path(__file__).with_name('audio_preview_kernel.c')
    compiler = shlex.split(os.environ.get('CC', shutil.which('cc') or ''))
    if not compiler:
        return None
    flags = ['-O3', '-std=c99', '-fPIC', '-ffp-contract=off', '-fno-fast-math', '-shared']
    key = hashlib.sha256(source.read_bytes() + repr((compiler, flags, sys.platform, platform.machine())).encode()).hexdigest()
    folder = source.parent.parent / 'build/host'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (key + ('.dylib' if sys.platform == 'darwin' else '.so'))
    if not target.is_file():
        temporary = target.with_name(target.name + '.' + str(os.getpid()) + '.tmp')
        try:
            subprocess.run(compiler + flags + [str(source), '-o', str(temporary)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.replace(temporary, target)
        except (OSError, subprocess.CalledProcessError):
            temporary.unlink(missing_ok=True)
            return None
    target.read_bytes()
    result = ctypes.CDLL(str(target))
    result.audio_preview_part.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64, ctypes.c_uint,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_double, ctypes.POINTER(ctypes.c_int)]
    result.audio_preview_part.restype = ctypes.c_uint64
    return result


def part(ram, output, first, end, osc, shift, table, gain):
    ram_buffer = (ctypes.c_ubyte * len(ram)).from_buffer(ram)
    output_buffer = (ctypes.c_float * len(output)).from_buffer(output)
    halted = ctypes.c_int()
    phase = library().audio_preview_part(ram_buffer, output_buffer, first, end,
        osc['phase'], osc['fc'], shift, osc['size'], table, osc['control'], gain,
        ctypes.byref(halted))
    if halted.value:
        osc['control'] |= 1
    return phase
