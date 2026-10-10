"""Read and validate prepared audio without MIDI, synthesis or DOC compiler imports."""
import hashlib
import json
from pathlib import Path, PurePosixPath

from game_profile import read_toml


def sha(data):
    return hashlib.sha256(data).hexdigest()



def quote(value):
    return json.dumps(value, ensure_ascii=False)



def checked(path, expected):
    data = Path(path).read_bytes()
    if sha(data) != expected:
        raise ValueError(str(path)+': SHA-256 differs from the recipe')
    return data



def write_toml(path, data, comment=''):
    """Write ordinary tables and arrays of tables, with readable scalar values."""
    lines=[comment] if comment else []
    def table(value, names=(), header=False, repeated=False):
        if header:
            title='.'.join(quote(n) for n in names)
            lines.extend(['',('[['+title+']]') if repeated else '['+title+']'])
        for key,v in value.items():
            if not isinstance(v,dict) and not (isinstance(v,list) and v and isinstance(v[0],dict)):
                lines.append(quote(key)+' = '+quote(v))
        for key,v in value.items():
            if isinstance(v,dict):table(v,names+(key,),True)
            elif isinstance(v,list) and v and isinstance(v[0],dict):
                for row in v:table(row,names+(key,),True,True)
    table(data)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')



def contained(root, name):
    name=PurePosixPath(name)
    if name.is_absolute() or '..' in name.parts or '\\' in str(name) or ':' in str(name):
        raise ValueError('intermediate file must be a relative package path')
    path=root.joinpath(*name.parts).resolve()
    if root.resolve() not in path.parents:
        raise ValueError('intermediate file escapes its package')
    return path



def validate_dos(package,game,data,shared=None,source=None):
    from dos_data import DosData
    if not data and source is None:raise ValueError('preserved music requires --data with the matching licensed DOS files')
    manifest=read_toml(package/'intermediate.toml')
    if manifest['format']!=2:raise ValueError('unsupported intermediate package')
    if manifest['profile']!=game.key and not (manifest['profile']=='spear' and game.spear):
        raise ValueError('intermediate package belongs to a different game profile')
    songs={r['id']:r['name'] for r in manifest['songs']}
    if songs!=game.required_music:raise ValueError('intermediate package does not cover the complete profile')
    if source is not None and source.profile.key!=game.key:raise ValueError('resolved DOS source belongs to a different profile')
    chunks=(source if source is not None else DosData(data,game.key,shared)).audio()
    for sid,name in songs.items():
        expected=read_toml(package/'inputs'/name/'inputs.toml')['original_sha256']
        if sha(chunks[game.sounds*3+sid])!=expected:
            raise ValueError('AdLib source does not match the preserved arrangement: '+name)
    return {name:chunks[game.sounds*3+sid] for sid,name in songs.items()}



def validate_effects(package,game,data,shared=None,source=None):
    from dos_data import DosData
    validate_dos(package,game,data,shared,source=source)
    chunks=(source if source is not None else DosData(data,game.key,shared)).audio()
    root=package/'effects/ym3812'
    document=read_toml(root/'samples.toml')
    if document['format']!=1:raise ValueError('unsupported effect intermediates')
    rows=document['samples']
    if not rows:raise ValueError('missing preserved effects')
    for row in rows:
        checked(contained(root,row['file']),row['sha256'])
        if sha(chunks[game.sounds+row['id']])!=row['original_sha256']:
            raise ValueError('AdLib effect differs from the preserved source: '+str(row['id']))
    return root
