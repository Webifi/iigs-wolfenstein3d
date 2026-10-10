"""Palette fits: one step per floor, keyed on what that floor's fit read.

Each floor is fitted by its own `python3 tools/build_colors.py --floors N`
(the same computation as the all-floor run; floors share no state). A fit
runs only when tools/step_cache.py finds a difference in what that fit
actually read: the files it opened, the code it can reach (tools/code_key.py:
an edit to a tool the fit does not run, such as build_frontend.py, or to a
function it cannot call, changes nothing) and the memmap values it used.
Missing fits run in parallel, one process per core.

The fits travel with their records in data/palette-cache/<game>:
N.json (the fit) and cache.json (format 2: for each floor the sha256 of N.json
and the step record, with stage paths written as @stage/...). A build adopts
a floor's fit from there when its record still holds in the new stage, so a
fresh checkout does not refit. After a build, OUT/<game>/palette-cache holds
the current fits and records; copy it to data/palette-cache/<game> to keep it.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

FORMAT = 2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(floor):
    return [sys.executable, 'tools/build_colors.py', '--floors', str(floor)]


def read_seed(folder):
    try:
        receipt = json.loads((folder/'cache.json').read_text())
    except (OSError, ValueError):
        return {}
    if receipt.get('format') != FORMAT:
        return {}
    return {int(n): row for n, row in receipt['floors'].items()}


def adopt(cache, floor, row, folder, env):
    """Use a seed fit when its record holds in this stage."""
    fit = folder/(str(floor)+'.json')
    if not fit.is_file() or sha(fit) != row['sha']:
        return False
    record = cache.absolute(row['record'])
    target = str(cache.root/'build/palettes'/(str(floor)+'.json'))
    if record.get('outputs', {}).get(target) != row['sha']:
        return False
    cache.keep(fit, row['sha'])
    if cache.why_not(record, env) is not None:
        return False
    cache.save(command(floor), record)
    cache.put_back(record)
    return True


def fit_floors(cache, stage, game, env, log, export):
    """Every floor's palette in build/palettes, fitted only where needed."""
    floors = [command(n) for n in range(game.floors)]
    seed_folder = stage/'data/palette-cache'/game.key
    seed = read_seed(seed_folder)

    def from_seed(step, reason):
        n = int(step[-1])
        return n in seed and adopt(cache, n, seed[n], seed_folder, env)
    cache.parallel(floors, env, log, 'palette fits', adopt=from_seed)
    write_export(cache, game, export)


def write_export(cache, game, export):
    """OUT/<game>/palette-cache: the fits and their records (format 2)."""
    export.mkdir(parents=True, exist_ok=True)
    floors = {}
    for n in range(game.floors):
        record = cache.stored(command(n))
        fit = cache.root/'build/palettes'/(str(n)+'.json')
        record_floor = json.loads(fit.read_text())
        if record_floor['floor'] != n+1:
            raise ValueError('Palette floor identity differs: '+fit.name)
        shutil.copyfile(fit, export/fit.name)
        floors[str(n)] = dict(sha=sha(fit), record=record)
    (export/'cache.json').write_text(json.dumps(dict(format=FORMAT, profile=game.key, floors=floors),
                                                separators=(',', ':'), sort_keys=True)+'\n')


def fit_all(stage, game, env, log, jobs):
    """Without the step cache (WOLF_STEP_CACHE=0): every floor, in parallel."""
    def fit(cmd):
        result = subprocess.run(cmd, cwd=stage, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return cmd, result
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(fit, fit_commands(game.floors,jobs)))
    with log.open('a', encoding='utf-8') as output:
        for cmd, result in results:
            output.write('Build: '+' '.join(cmd)+'\n'+result.stdout.decode(errors='replace'))
    for cmd, result in results:
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout)


def fit_commands(floors,jobs):
    """Reuse decoded source data within each worker, starting from no fits."""
    count=min(floors,jobs)
    return [[sys.executable,'tools/build_colors.py','--floors']+
            [str(n) for n in range(first,floors,count)] for first in range(count)]
