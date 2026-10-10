"""Keep unchanged generated files from invalidating expensive dependents."""
import os


def write_generated(path, text, *, force=False):
    if not force and path.exists() and path.read_text() == text:
        # Written again with its old time: Make sees no change, and the step cache
        # (tools/step_cache.py) records the file as an output of this step.
        old = path.stat()
        path.write_text(text)
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        return False
    path.write_text(text)
    return True
