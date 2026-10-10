"""One engine recipe, with source identity and boot art supplied by the profile."""
import hashlib
from pathlib import Path

from game_profile import fields, integer, read_toml


def paths(root, key):
    folder = Path(root) / 'profiles/native'
    return folder / 'engine.toml', folder / (key + '.toml')


def load(root, key):
    common, selected = paths(root, key)
    recipe = read_toml(common)
    content = read_toml(selected)
    fields(content, ('format', 'game', 'boot_picture', 'content'), str(selected))
    if content['format'] != recipe['format'] or content['game'] != key:
        raise ValueError('Native content profile disagrees with its engine recipe')
    data = content['content']
    fields(data, ('wall_pages', 'save_blocks'), str(selected) + '.content')
    integer(data['wall_pages'], 1, 134, 'content.wall_pages')
    integer(data['save_blocks'], 1, 27, 'content.save_blocks')
    return dict(recipe, **content)


def digest(root, key):
    value = hashlib.sha256()
    for path in paths(root, key):
        value.update(path.read_text().replace('\r\n', '\n').encode())
        value.update(b'\0')
    return value.hexdigest()
