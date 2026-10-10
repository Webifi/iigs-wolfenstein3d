"""Build floor-local, already-lit art and source weapon oracles."""
import memmap
import bisect
import hashlib
import json
import os
import struct
from pathlib import Path
from source_identity import source_bytes

from assetspace import Space
from buildconfig import config
from registered_art import pack_floor, layout_include, ENDPOINT_ORIGINALS
import fixed_art
from wolfdata import ROOT, PROFILE, maps, vswap, sprite
from wolf_source import sprite_ids
import pool_cover

ASSETS=ROOT/'build/assets'
GEN=ROOT/'build/gen'


def segments(records, folder, prefix):
    parts=[]
    for address,raw in sorted(records):
        if not raw: continue
        if parts and parts[-1][0]+len(parts[-1][1])==address and parts[-1][0]>>16==(address+len(raw)-1)>>16:
            parts[-1][1].extend(raw)
        else:
            parts.append([address,bytearray(raw)])
    result=[]
    for n,(address,raw) in enumerate(parts):
        assert address>>16==(address+len(raw)-1)>>16
        name=f'{prefix}-{n:02}.bin'
        (folder/name).write_bytes(raw)
        result.append(dict(file=name,address=address,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    return result


def weapon_oracle(folder, color):
    """Original six-byte runs for host projection, never resident in the game."""
    ids=sprite_ids();pages,base,_=vswap()
    shapes=range(ids['SPR_KNIFEREADY'],ids['SPR_CHAINREADY']+5)
    commands=bytearray(260*20)
    frame_base=[0]*len(ids)
    storage=Space(((memmap.WEAPON_PIXELS,memmap.WEAPON_PIXELS_END),))
    pixels=[];unique={};records={}
    for n,shape in enumerate(shapes):
        art=sprite(pages[base+shape]);columns=[[] for _ in range(64)]
        for x,col in enumerate(art['columns'],art['left']):
            columns[x]=[(a,b,bytes(raw)) for a,b,raw in col]
        frame=n*260;frame_base[shape]=frame
        for x,col in enumerate(columns):
            key=tuple(col)
            if key not in unique:
                unique[key]=memmap.SPRITE_CMDS+len(commands)
                for a,b,raw in sorted(col,reverse=True):
                    ab=bytes(v for c in raw for v in color['sprite_lights'][-1][c])
                    address=storage.allocate(len(ab),a*2)
                    pixels.append((address,ab))
                    source=address-a*2
                    commands.extend(struct.pack('<3H',a|b<<8,source&65535,source>>16))
                commands.extend(b'\0\0')
            pointer=unique[key]
            struct.pack_into('<H',commands,frame+x*2,pointer&65535)
            commands[frame+128+x]=pointer>>16
        records[shape]=dict(left=art['left'],right=art['right'],weapon=True,
                           columns=[[(a,b,list(raw)) for a,b,raw in c] for c in columns])
    rows=segments(pixels,folder,'weapon-pixels')
    assert len(rows)==1 and rows[0]['address']==memmap.WEAPON_PIXELS
    (folder/'weapon-sourcecmd.bin').write_bytes(commands)
    (folder/'weapon-sourceframes.json').write_text(json.dumps(frame_base)+'\n')
    return records


def endpoints():
    data=(ASSETS/'sprite-endpoints.bin').read_bytes()
    count=len(pool_cover.feature_starts())*2
    originals=bytes(data[page+tex] for page in range(0,len(data),256)
                    for tex in (*range(65),*range(200,200+count)))
    from viewgeometry import SIZES
    plans=bytearray()
    for view in SIZES:
        top=(160-view)//2;bottom=top+view
        for page in range(0,len(data),256):
            rows=data[page:page+65]
            lo=bisect.bisect_left(rows,top);hi=bisect.bisect_right(rows,bottom)
            assert hi>lo
            plans.extend((lo,hi-lo))
    assert len(originals)==200*(65+count) and len(plans)==1600
    (ASSETS/'registered-endpoints.bin').write_bytes(originals+plans)
    assert ENDPOINT_ORIGINALS+len(originals)+len(plans)<=memmap.RAW_BOOT


def build_floor(floor, code_digest, sound, reuse=True):
    ids=sprite_ids()
    folder=ROOT/f'build/levels/{floor}';folder.mkdir(parents=True,exist_ok=True)
    color=(ROOT/f'build/palettes/{floor}.json').read_bytes()
    fingerprint=hashlib.sha256(code_digest);fingerprint.update(color)
    effect=sound/f'effects-floor-{floor:02}-loads.json'
    if not effect.exists():raise ValueError(f'Generate floor effects before art packing: {effect}')
    fingerprint.update(effect.read_bytes());digest=fingerprint.hexdigest()
    stats=folder/'registered-art.json'
    previous=json.loads(stats.read_text()) if stats.exists() else {}
    if previous.get('input_sha256')!=digest or not reuse:
        for stale in ('fixed-program.bin','fixed-weaponhdr.bin','fixed-wallptrs.bin','fixed.json','registered-art-baked.json','sprite-quality-loads.json'):
            (folder/stale).unlink(missing_ok=True)
        try:
            rows,offsets,frames,receipt,report=fixed_art.pack_floor(floor,ROOT/'build/palettes')
        except ValueError as error:
            raise ValueError(f'floor {floor+1}: both sprite modes must fit the fixed layout') from error
        if report.get('layout')=='fixed':
            quality = segments(fixed_art.LAST_PROGRAM['quality_records'], folder, 'sprite-quality')
            (folder/'sprite-quality-loads.json').write_text(json.dumps(quality, indent=2)+'\n')
            import fixed_store,fixed_units
            program=fixed_store.floor_program(floor,fixed_art.LAST_PROGRAM,report['wall_columns'])
            shapes=[s for s,_,_,_ in frames]
            unit=fixed_units.program_unit(program,receipt,report['wall_pages'],shapes,report['headers_bytes'])
            (folder/'fixed-program.bin').write_bytes(unit)
            weapon_at=memmap.SPRITE_CMDS+len(shapes)*202
            (folder/'fixed-weaponhdr.bin').write_bytes(dict(rows)[memmap.SPRITE_CMDS][len(shapes)*202:])
            strip_files=[]
            for g,gid in enumerate(program['groups']):
                strip_blob=program['strips'][g][0]
                name=None
                if strip_blob:
                    name=f'strip-{gid:02}-{hashlib.sha256(strip_blob).hexdigest()[:12]}.bin'
                    (ROOT/'build/fixed/strips').mkdir(parents=True,exist_ok=True)
                    (ROOT/'build/fixed/strips'/name).write_bytes(strip_blob)
                    # After the doubled blob (an empty blob's unit is a 2-byte dummy).
                    name=[name,fixed_units.SRC+2*len(fixed_art.groups()[gid][1])]
                strip_files.append(name)
            packed=program['wall_ranges'] is None
            if packed:
                (folder/'fixed-wallptrs.bin').write_bytes(dict(rows)[fixed_art.WALL_POINTERS])
            (folder/'fixed.json').write_text(json.dumps(dict(groups=program['groups'],weapon_header_address=weapon_at,
                sight_rows=report.get('sight_rows'),wall_pointers=packed,strips=strip_files,
                quality='sprite-quality-loads.json',
                program_bytes=len(unit),wall_ranges=None if packed else len(program['wall_ranges']),
                wall_aliases=len(program['wall_aliases']),wall_pages=report['wall_pages']))+'\n')
        if report.get('layout')!='fixed':
            # Per-floor packing: the generator still writes the walls (packed, from the shared
            # column chunks and a loaded pointer table); only the rest of the art is stored.
            import fixed_units
            walls=set(report['wall_records'])
            prog=dict(groups=[],areas={},strip_at={},strips=[],commands={},wall_ranges=None,wall_aliases=[],
                      wall_count=report['wall_columns'],sight=None)
            unit=fixed_units.program_unit(prog,receipt,fixed_art.wall_pages(floor,all_doors=not PROFILE.spear),[],report['headers_bytes'])
            (folder/'fixed-program.bin').write_bytes(unit)
            (folder/'fixed-wallptrs.bin').write_bytes(dict(rows)[fixed_art.WALL_POINTERS])
            baked=[(a,raw) for a,raw in rows if a not in walls and a not in (fixed_art.WALL_POINTERS,memmap.WALL_COLUMNS)]
            (folder/'registered-art-baked.json').write_text(json.dumps(segments(baked,folder,'registered-art-baked'),indent=2)+'\n')
            (folder/'fixed.json').write_text(json.dumps(dict(groups=[],weapon_header_address=None,sight_rows=None,
                wall_pointers=True,baked='registered-art-baked.json',program_bytes=len(unit),wall_ranges=None,wall_aliases=0,
                wall_pages=fixed_art.wall_pages(floor,all_doors=not PROFILE.spear)))+'\n')
        loads=segments(rows,folder,'registered-art')
        (folder/'registered-art-loads.json').write_text(json.dumps(loads,indent=2)+'\n')
        frame_base=[offsets.get(i,0) for i in range(len(ids) + 1)]
        (folder/'spriteFrame.bin').write_bytes(struct.pack('<%dH'%len(frame_base),*frame_base))
        records={shape:dict(left=art['left'],right=art['right'],weapon=False,
                           columns=[[(a,b,list(raw)) for a,b,raw in col] for col in columns])
                 for shape,art,columns,_ in frames}
        mirrored = report.get('mirrored_shape')
        if mirrored is not None:
            records[len(ids)] = dict(records[mirrored], mirror_of=mirrored)
        records.update(weapon_oracle(folder,receipt))
        (folder/'sprites.json').write_text(json.dumps(records,separators=(',',':'))+'\n')
        (folder/'pool-colors.json').write_text(json.dumps(receipt['sprite_lights'])+'\n')
        report.update(input_sha256=digest,units=len(loads))
        stats.write_text(json.dumps(report,indent=2)+'\n')
    else:report=previous
    print(f'floor {floor+1}: {report["frames"]} world frames, {report["units"]} art units, {report["free_bytes"]} free art bytes',flush=True)
    return floor, report


def main():
    import argparse
    from concurrent.futures import ProcessPoolExecutor
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs",type=int,default=min(4, os.cpu_count() or 1))
    # tools/native_pipeline.py runs one cached step per floor (tools/step_cache.py
    # keys each on what that floor read), then --finish.
    parser.add_argument("--floor",type=int,help="build only this zero-based floor, always from its inputs")
    parser.add_argument("--finish",action="store_true",help="only the outputs shared by all floors (after every --floor)")
    # fixed_art.groups() takes about 25 s and is the same for every floor: one step
    # writes it, each --floor step reads it instead of computing it again.
    parser.add_argument("--save-groups",type=Path,help="only write fixed_art.groups() to this file")
    parser.add_argument("--groups",type=Path,help="with --floor: fixed_art.groups() as written by --save-groups")
    args=parser.parse_args()
    if args.save_groups:
        args.save_groups.write_text(json.dumps([[list(members),blob.hex()] for members,blob in fixed_art.groups()])+'\n')
        return
    if args.groups:
        saved=tuple((tuple(members),bytes.fromhex(blob)) for members,blob in json.loads(args.groups.read_text()))
        fixed_art.groups=lambda:saved
    if not 1<=args.jobs<=8:parser.error("jobs must be1through8")
    if args.floor is not None and not 0<=args.floor<PROFILE.floors:parser.error("floor outside the game")
    ids=sprite_ids();selected=config()['floor']-1
    if not args.finish:
        code=hashlib.sha256()
        for name in ('native_host.py','host_kernels.c','build_registered_sprites.py','registered_art.py','sprite_simplify.py','fixed_art.py','fixed_store.py','fixed_units.py','sight_rooms.py','grow_rooms.py','line_proofs.py','line_regions.py','probe_art_overlap.py','pool_cover.py','floor_art.py','native_actors.py'):
            code.update(source_bytes(ROOT/'tools'/name))
        pages,_,_=vswap()
        code.update(b''.join(pages))
        code.update(json.dumps(maps(),sort_keys=True).encode())
        code.update(json.dumps([[list(members), blob.hex()] for members, blob in fixed_art.groups()]).encode())
        sound=Path(os.environ.get('WOLF_FLOOR_EFFECTS', ROOT/'build/sound'))
        if args.floor is not None:
            build_floor(args.floor,code.digest(),sound,reuse=False)
            return
        from itertools import repeat
        if args.jobs==1:
            for floor in range(PROFILE.floors):build_floor(floor,code.digest(),sound)
        else:
            with ProcessPoolExecutor(max_workers=args.jobs) as executor:
                for _ in executor.map(build_floor,range(PROFILE.floors),repeat(code.digest()),repeat(sound)):pass
    folder=ROOT/f'build/levels/{selected}'
    for name in ('sprites.json','spriteFrame.bin','weapon-sourcecmd.bin','weapon-sourceframes.json','weapon-pixels-00.bin','pool-colors.json'):
        (ASSETS/name).write_bytes((folder/name).read_bytes())
    frames=struct.unpack('<%dH'%(len(ids)+1),(folder/'spriteFrame.bin').read_bytes())
    lines=[' .section gamedata, data, root','spriteFrame: .word '+','.join(map(str,frames))]
    constants=[name+' .equ '+str(i) for name,i in ids.items()]
    from sprite_simplify import mirror_shape
    mirrored = mirror_shape()
    constants += [f'SPR_MIRROR_SOURCE .equ {mirrored if mirrored is not None else 65534}',
                  f'SPR_MIRROR_SHAPE .equ {len(ids)}']
    (GEN/'sprites.inc').write_text('\n'.join(lines+constants)+'\n')
    (GEN/'sprite_ids.inc').write_text('\n'.join(constants)+'\n')
    endpoints();layout_include()

if __name__=='__main__':main()
