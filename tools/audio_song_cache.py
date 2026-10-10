"""Shared per-song conversion; pack validation and provenance stay with the caller."""
import json
import os
from pathlib import Path
from source_identity import source_bytes
import shutil
import subprocess
import sys

from step_cache import StepCache,clone


def update(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.is_file() or path.read_bytes()!=data:path.write_bytes(data)


def compile_song(args,recipe,package,licensed,out):
    from audio_compile import ROOT,compiler_sources
    from audio_provenance import recipe_paths,snapshot,complete
    from game_profile import read_toml
    name=read_toml(recipe)["name"]
    if name in ('.','..') or Path(name).name!=name:raise ValueError('invalid song name')
    pack=out.parent.parent
    root=pack.parent/'.song-cache'/pack.name/name
    source=root/'input';generated=root/'build/audio/music'
    root.mkdir(parents=True,exist_ok=True)
    if not (root/'tools').exists():(root/'tools').symlink_to(ROOT/'tools',target_is_directory=True)
    inputs={source/'intermediate.toml':b'format = 2\n',source/'licensed.imf':licensed,
            source/'songs'/recipe.name:recipe.read_bytes()}
    for path in (package/'inputs'/name).rglob('*'):
        if path.is_file():inputs[source/path.relative_to(package)]=path.read_bytes()
    # Explicit prepared WAV overrides can name additional package files.
    for path in recipe_paths(recipe,offline=True):
        path=Path(path)
        if path.is_file() and path.is_relative_to(package):inputs[source/path.relative_to(package)]=path.read_bytes()
    for path,data in inputs.items():update(path,data)
    for path in source.rglob('*'):
        if path.is_file() and path not in inputs:path.unlink()
    command=[sys.executable,str(ROOT/'tools/audio_song.py'),str(source/'songs'/recipe.name),
        '--preserved-samples',str(source),'--licensed-imf',str(source/'licensed.imf'),'--out',str(generated)]
    if args.settings:command+=['--settings',str(args.settings.resolve())]
    if args.require_identical:command+=['--require-identical']
    if args.model_diagnostics:command+=['--model-diagnostics']
    env=dict(os.environ,WOLF_AUDIO_POOL=args.worker_pool,WOLF_AUDIO_WORKERS=str(args.worker_count))
    cache=None
    if os.environ.get('WOLF_STEP_CACHE','1')!='0':cache=StepCache(root,source_root=ROOT,log=lambda line:None)
    try:
        with (root/'run.log').open('w') as log:
            if cache:ran=cache.python(command,env,log)
            else:
                subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
                ran=True
    except subprocess.CalledProcessError:
        out.mkdir(parents=True,exist_ok=True)
        logs=[p.read_text() for p in (root/'run.log',generated/'compiler.log') if p.is_file()]
        (out/'build.log').write_text('\n'.join(logs))
        raise ValueError(name+' failed; see '+str(out/'build.log')) from None
    finally:
        if cache:cache.finish()
    out.mkdir(parents=True,exist_ok=True)
    replacements=[(str(generated),str(out)),(str(source),str(package))]
    for path in generated.rglob('*'):
        if not path.is_file() or path.name=='compiler.log':continue
        target=out/path.relative_to(generated);target.parent.mkdir(parents=True,exist_ok=True)
        if path.suffix=='.json':
            data=path.read_bytes()
            for before,after in replacements:data=data.replace(before.encode(),after.encode())
            target.write_bytes(data)
        else:clone(path,target)
    info=json.loads((out/'info.json').read_text())
    info['compiler_sources']=compiler_sources()
    from audio_recipes import sha
    info['build_sources']={str(p):sha(source_bytes(p)) for p in (ROOT/'tools/doccompiler').glob('*.py')}
    (out/'info.json').write_text(json.dumps(info,indent=2)+'\n')
    paths=[recipe,package/'inputs'/name,source/'licensed.imf']
    if args.settings:paths.append(args.settings)
    identity=snapshot('music',args.profile,paths)
    receipt=complete(out,identity)
    log=(generated/'compiler.log').read_text()
    for before,after in replacements:log=log.replace(before,after)
    (out/'build.log').write_text(log+json.dumps(dict(info,audio_build_identity=receipt['identity']),indent=2)+'\n')
    return info,ran
