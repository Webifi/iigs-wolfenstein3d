"""Selected DOS graphics and palette for the chrome lettering generator."""
import os
import sys
from pathlib import Path
from functools import lru_cache

_root = Path(os.environ.get('WOLF_FRONTEND_ROOT', str(Path(__file__).resolve().parents[3])))
sys.path.insert(0, str(_root/'tools'))
from wolfdata import source_data, palette as source_palette

@lru_cache(maxsize=1)
def source():
    data=source_data()
    chunks=data.graphics()
    return chunks,data.graphics_layout['roles']

@lru_cache(maxsize=1)
def graphics():
    return source()[0]

@lru_cache(maxsize=1)
def palette():
    return source_palette()

# Logical reference IDs retain the approved crop/kerning definitions.
_ROLES={23:'menu_cursor1',24:'menu_cursor2',22:'menu_options',38:'menu_control',39:'menu_customize',40:'menu_load',
        41:'menu_save',102:'menu_scores',146:'menu_getpsyched',13:'menu_logo'}

def picture_index(reference):
    role=_ROLES.get(reference)
    if role is None: raise ValueError('unknown lettering picture reference: '+str(reference))
    if role not in source()[1]: raise ValueError('selected source has no '+role+' picture')
    return source()[1][role]

def has_logo():
    return 'menu_logo' in source()[1]
