"""Keep Make and the source pipeline on the same engine and media layout."""
from pathlib import Path
import re
import shlex

from native_recipe import load

ROOT = Path(__file__).resolve().parents[1]


def check():
    make = (ROOT / 'Makefile').read_text()
    link = next(line for line in make.splitlines() if line.startswith('build/wolf.elf:'))
    objects = re.findall(r'build/obj/[\w-]+\.o', link)
    assert len(objects) == len(set(objects))
    assert '$(WOLF_LINKER)' in link
    command = next(line for line in make.splitlines() if 'tools/mkdisk.py --boot' in line)
    variables = dict(re.findall(r'(?m)^([A-Z_]+) := (.*)$', make))
    for key in ('STORE_ADDRESS', 'MEDIA_EXTRA'):
        command = command.replace('$(' + key + ')', variables[key])
    argv = shlex.split(command)
    flags = {'--compress', '--hd-only', '--no-readme'}
    values = {}
    for index, arg in enumerate(argv):
        if arg.startswith('--') and arg not in flags:
            values.setdefault(arg, []).append(argv[index + 1])
    common = None
    profiles = ('shareware', 'wolf3d', 'spear', 'spear-mission2', 'spear-mission3')
    for key in profiles:
        recipe = load(ROOT, key)
        assert recipe['format'] == 2 and recipe['game'] == key
        assert recipe['objects'] == objects
        assert recipe['settings']['linker'] == variables['WOLF_LINKER']
        media = recipe['media']
        for name in ('boot', 'loader', 'elf', 'store', 'picture_file', 'menu'):
            assert [media[name]] == values['--' + name.replace('_', '-')], (key, name)
        for name, flag in (('data', '--data'), ('data_lists', '--data-list')):
            assert sorted(media[name]) == sorted(values[flag]), (key, name)
        assert media['hd_only'] == ('--hd-only' in argv)
        assert recipe['settings']['entry'] == values['--entry'][0]
        engine = {k: v for k, v in recipe.items() if k not in ('game', 'boot_picture', 'content')}
        assert common is None or common == engine
        common = engine
        steps = [row['arguments'][0] for row in recipe['asset_step']]
        assert len(steps) == len(set(steps))
    print(f'All {len(profiles)} profiles share {len(objects)} objects, {len(steps)} generators, linker and media layout.')


if __name__ == '__main__':
    check()
