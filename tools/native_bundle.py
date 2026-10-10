"""Export and verify the exact current engine and its generated assembly inputs."""
import hashlib
import json
from pathlib import Path
import re
import shutil

from audio_package import write_toml
from game_profile import read_toml
from native_pipeline import text_hash
from native_recipe import load as load_native_recipe, digest as recipe_digest

ADAPTER_ID = 'wolf-current-v1'
GENERATED = re.compile(r'^\s*#\s*include\s+["<]([^">]+)[">]', re.M)


def assembly_inputs(root, recipe):
    """Resolve the complete textual include graph for every linked object."""
    pending = [root/('build/gen/'+Path(obj).stem+'.s' if Path(obj).stem in ('scalers', 'ray_programs')
                     else 'src/iigs/'+Path(obj).stem+'.s') for obj in recipe['objects']]
    pending += [root/'src/iigs/boot.s', root/'src/iigs/loader.s']
    found = {}
    while pending:
        path = pending.pop()
        key = path.relative_to(root).as_posix()
        if key in found:
            continue
        text = path.read_text()
        found[key] = text_hash(path)
        for include in GENERATED.findall(text):
            choices = [path.parent/include, root/'build/gen'/include, root/'src/iigs'/include]
            target = next((p for p in choices if p.is_file()), None)
            if target is None:
                # Conditional includes can be absent in a successful compile.
                # Their absence is part of the binding.
                found['build/gen/'+include] = None
            else:
                pending.append(target)
    for name in (recipe['settings']['linker'], 'src/iigs/boot.scm', 'src/iigs/loader.scm'):
        found[name] = text_hash(root/name)
    return dict(sorted(found.items()))


def export_bundle(root, game, campaign, out):
    """Export only an already linked/checked tree; source inputs stay identified."""
    recipe = load_native_recipe(root, game.key)
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for role, src, name in (('engine', 'build/wolf.elf', 'engine.elf'),
                            ('boot', 'build/boot/boot.raw', 'boot.raw'),
                            ('loader', 'build/boot/loader.raw', 'loader.raw'),
                            ('loader_symbols', 'build/boot/loader.elf', 'loader.elf')):
        shutil.copy2(root/src, out/name)
        files[role] = name
    elf_hash = hashlib.sha256((out/'engine.elf').read_bytes()).hexdigest()
    engine_id = 'wolf-'+game.key+'-'+elf_hash[:16]
    # The capability declaration is bounded to the selected source profile.
    # It does not assert emulator or physical-hardware acceptance.
    capabilities = dict(format=1, engine_id=engine_id, save_abi='spear-current-save-v1' if game.spear else 'wolf-current-save-v1',
                        capabilities=campaign['required_capabilities'], limits=campaign['required_limits'])
    write_toml(out/'capabilities.toml', capabilities)
    files['capabilities'] = 'capabilities.toml'
    inputs = assembly_inputs(root, recipe)
    bindings = dict(format=1, adapter=ADAPTER_ID, engine_id=engine_id, profile=game.key,
                    objects=recipe['objects'], generated_inputs={p:h for p,h in inputs.items() if p.startswith('build/')},
                    source_inputs={p:h for p,h in inputs.items() if not p.startswith('build/')},
                    recipe_sha256=recipe_digest(root, game.key),
                    audio_banks={str(s['id']):s['sha256'] for s in json.loads((root/'build/gen/audio-input.json').read_text())['songs']})
    # Native layout and source identities are receipts, not converted game assets.
    (out/'bindings.json').write_text(json.dumps(bindings, indent=2)+'\n')
    files['bindings'] = 'bindings.json'
    allocation = dict(format=1, minimum_machine='ROM00/01 + 4 MiB expansion',
                      source_content_sha256=campaign['source_content_sha256'],
                      save_content_sha256=campaign['save_content_sha256'],
                      source_files=campaign['source_files'],
                      linker_sha256=inputs[recipe['settings']['linker']],
                      runtime_verified=False)
    (out/'allocation.json').write_text(json.dumps(allocation, indent=2)+'\n')
    files['allocation'] = 'allocation.json'
    write_toml(out/'media.toml', recipe)
    files['media'] = 'media.toml'
    doc = dict(format=1, engine_id=engine_id, save_abi='spear-current-save-v1' if game.spear else 'wolf-current-save-v1',
               asset_abi='wolf-ep08', adapter=ADAPTER_ID,
               verified_profiles=[game.key], files={role:dict(path=name,sha256=hashlib.sha256((out/name).read_bytes()).hexdigest())
                                                    for role,name in files.items()})
    write_toml(out/'engine-bundle.toml', doc)
    return out/'engine-bundle.toml'


def install_engine(stage, bundle):
    _doc, files = bundle
    for role, target in (('engine','build/wolf.elf'),('boot','build/boot/boot.raw'),('loader','build/boot/loader.raw'),
                         ('loader_symbols','build/boot/loader.elf')):
        shutil.copy2(files[role], stage/target)


def verify_generated_bindings(stage, bundle):
    doc, files = bundle
    bindings = json.loads(files['bindings'].read_text())
    recipe = load_native_recipe(stage, bindings['profile'])
    actual = assembly_inputs(stage, recipe)
    expected = dict(bindings['source_inputs'], **bindings['generated_inputs'])
    changed = sorted(p for p in set(actual)|set(expected) if actual.get(p)!=expected.get(p))
    if changed:
        raise ValueError('Generated engine bindings differ; rebuild with --from-source --calypsi PATH. Changed: '+', '.join(changed))
    audio=json.loads((stage/'build/gen/audio-input.json').read_text())
    if {str(s['id']):s['sha256'] for s in audio['songs']} != bindings['audio_banks']:
        raise ValueError('Music differs from the bundled engine reference; use an explicitly selected source build to validate changed audio')
    if recipe_digest(stage, bindings['profile']) != bindings['recipe_sha256']:
        raise ValueError('Engine build recipe changed; export a new bundle from source')


class CurrentEngineAdapter:
    def check_bindings(self, doc, files, campaign):
        if 'loader_symbols' not in files:
            raise ValueError('Current bundle requires loader_symbols to regenerate loader bindings')
        root = Path(__file__).resolve().parents[1]
        binding = json.loads(files['bindings'].read_text())
        game = campaign['campaign']['profile_id']
        if binding.get('format')!=1 or binding.get('adapter')!=ADAPTER_ID or binding.get('engine_id')!=doc['engine_id'] or binding.get('profile')!=game:
            raise ValueError('Engine binding identity disagrees with its bundle/profile')
        recipe = load_native_recipe(root, game)
        if binding['objects'] != recipe['objects'] or len(binding['objects']) != len(recipe['objects']):
            raise ValueError('Engine bundle does not contain the current complete link recipe')
        from audio_package import contained
        for name, digest in binding['source_inputs'].items():
            if not name.startswith('src/iigs/'):
                raise ValueError('Unexpected engine source binding: '+name)
            path = contained(root,name)
            if not path.is_file() or text_hash(path)!=digest:
                raise ValueError('Engine source changed since bundle export: '+name)
        if recipe_digest(root, game)!=binding['recipe_sha256']:
            raise ValueError('Engine recipe changed since bundle export')
        media = read_toml(files['media'])
        if media != recipe:
            raise ValueError('Bundle media recipe differs from current source')
        allocation = json.loads(files['allocation'].read_text())
        if allocation['linker_sha256'] != binding['source_inputs'][recipe['settings']['linker']]:
            raise ValueError('Bundle memory allocation disagrees with its linker input')

    def build(self, doc, files, campaign, source, music, destination, **options):
        from native_pipeline import build_images
        return build_images(Path(__file__).resolve().parents[1], campaign, source, music, destination,
                            bundle=(doc, files), **options)
