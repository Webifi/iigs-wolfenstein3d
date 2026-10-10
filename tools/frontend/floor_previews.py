"""Render floor starts with the linked 65816 engine, without MAME or a ROM.

Firmware, progress and disk callbacks are omitted. The same assembled setup,
visibility, wall cast, sprite projection and painter run on the generated floor
assets. The preview excludes the HUD and weapon and averages native color pairs
before fitting its two menu palettes.
"""
import base64
import hashlib
import json
import struct
import zlib
from pathlib import Path

import memmap
from wolfdata import ROOT, PROFILE
from elf import read
from emu816 import Emu
from registered_loads import art_rows, boot_built
from build_registered_episode import logic_rows, hole_art
from frontend.native_assets import picture
from frontend.preview_art import picture_record
from frontend.gray_pair import pair_table, preview_bytes

ASSETS=ROOT/'build/assets'
OUT=ASSETS/'floor-previews'


def load_regions():
    size=(PROFILE.floors+4)*memmap.FLOOR_PREVIEW_BYTES
    if size>memmap.FLOOR_PREVIEWS_SIZE: raise ValueError('Floor preview pool is too small')
    return [dict(start=memmap.FLOOR_PREVIEWS+offset,
                 end=memmap.FLOOR_PREVIEWS+min(offset+65536,size),
                 limit=memmap.FLOOR_PREVIEWS+offset+65536,
                 file=f'floor-previews-{offset//65536}.bin') for offset in range(0,size,65536)]


class Renderer:
    def __init__(self):
        self.segments,self.symbols=read(ROOT/'build/wolf.elf')
        self.loaded=[]
        for address,path in boot_built(): self.add(address,path)
        for name,address in (
            ('word-products',memmap.WORD_PRODUCTS),('tables',memmap.TABLES),
            ('ray-partial',memmap.RAY_PARTIAL),('ray-products-directory',memmap.RAY_PRODUCTS_DIRECTORY),
            ('registered-endpoints',memmap.REG_ENDPOINT_ORIGINALS),('ray-focal',memmap.RAY_FOCAL),
            ('view-height',memmap.VIEW_HEIGHT),('shading',memmap.SHADING),('clips',memmap.CLIPS),
            ('ui',memmap.UI),('weapon-mask',memmap.WEAPON_RUNS)):
            self.add(address,ASSETS/(name+'.bin'))
        for row in json.loads((ASSETS/'view-weight-loads.json').read_text())[1]:
            self.add(row['address'],ROOT/row['file'])
        code=hashlib.sha256((ROOT/'build/wolf.elf').read_bytes())
        for _,data in self.loaded: code.update(data)
        code.update(Path(__file__).read_bytes())
        self.identity=code.hexdigest()

    def add(self,address,path): self.loaded.append((address,Path(path).read_bytes()))

    def floor_inputs(self,floor):
        folder=ROOT/f'build/levels/{floor}'
        rows=[(r['address'],(ROOT/r['file']).read_bytes()) for r in art_rows(floor)]
        paths=['logic.bin','source-planes.bin','spriteFrame.bin','map.json','fixed.json']
        data={n:(folder/n).read_bytes() for n in paths}
        fixed=json.loads(data['fixed.json'])
        if fixed.get('sight_rows') is not None:
            for name in ('fixed-program.bin','sight-rooms.bin','sight-lower.bin'):
                data[name]=(folder/name).read_bytes()
            data['sight_gen.raw']=(ROOT/'build/boot/sight_gen.raw').read_bytes()
        data['tints.bin']=(ROOT/f'build/palettes/tints-{floor+1}.bin').read_bytes()
        key=hashlib.sha256(bytes.fromhex(self.identity)+floor.to_bytes(2,'little'))
        for address,raw in rows:key.update(address.to_bytes(3,'little'));key.update(raw)
        for name,raw in sorted(data.items()):key.update(name.encode());key.update(raw)
        return rows,data,key.hexdigest()

    def render(self,floor,rows,data):
        e=Emu();s=self.symbols
        for segment in self.segments:e.load(segment['address'],segment['data'])
        for address,raw in self.loaded+rows:e.load(address,raw)
        def call(name,a=0,x=0,long=False,logic=False):
            address=s[name] if isinstance(name,str) else name
            e.d,e.db,e.mf,e.xf,e.s=(s['LOGICDP'],memmap.LOGIC_BASE>>16,0,0,0x1fff) if logic else (memmap.GAME_DP,2,0,0,0x1fff)
            e.a,e.x,e.y=a,x,0
            e.call(address>>16,address&65535,long_return=long,limit=4_000_000)
        extra=[];fixed=json.loads(data['fixed.json'])
        if fixed.get('sight_rows') is not None:
            at=struct.unpack_from('<H',data['fixed-program.bin'],12)[0]
            params=data['fixed-program.bin'][at:at+7]+b'\0'
            for address,raw in ((memmap.SIGHT_PARAMS,params+data['sight-rooms.bin']),
                                (fixed['sight_rows'],data['sight-lower.bin']),
                                (memmap.SIGHT_GEN,data['sight_gen.raw'])):
                e.load(address,raw)
                if address!=memmap.SIGHT_GEN:extra.append(dict(address=address,bytes=len(raw)))
            call(memmap.SIGHT_GEN,long=True)
        for row in logic_rows(floor,data['logic.bin'],hole_art(floor,extra)):
            e.load(row['address'],row['data'])
        e.load(memmap.RAW_PLANES,data['source-planes.bin'])
        e.load(s['spriteFrame'],data['spriteFrame.bin'])
        e.load(memmap.TINTS,data['tints.bin'])
        meta=json.loads(data['map.json'])
        for name,address in s.items():
            if name.startswith(('flat_floor_','flat_ceiling_')):
                e.wr8(address+int(name.split('_')[-2]),17*meta[name.split('_')[1]])
        # Rendering needs no disk, clock, saved-game baseline or progress display.
        for name in ('Progress1','Progress2','Progress26','gsCapture','EnsureGameplayAssets','EnsureViewAssets','I_GetTime'):
            e.wr8(s[name],0x6b)
        e.wr16(s['screenHold'],1)
        call('LogicNewGame',2,floor,long=True)
        call('ApplyLevel')
        call('setView',1)
        call('refreshView',logic=True)
        call('castFrame')
        e.wr16(s['levelState'],1)  # PrepareSprites omits only the weapon in this state.
        call('PrepareSprites')
        call('paintFrame')
        left,top=e.rd16(s['viewLeft'])*2,e.rd16(s['viewTop'])
        width,height=214,107
        colors=struct.unpack_from('<16H',data['tints.bin'])
        pixels=[colors[(e.rd8(memmap.SHR+(top+y)*160+(left+x)//2)>>(0 if (left+x)&1 else 4))&15]
                for y in range(height) for x in range(width)]
        return struct.pack('<%dH'%len(pixels),*pixels)


def shrink(raw):
    pixels=struct.unpack('<%dH'%(214*107),raw);result=[]
    for y in range(53):
        row=[]
        for x in range(106):
            cells=[pixels[yy*214+xx] for yy in range(y*107//53,(y+1)*107//53)
                   for xx in range(x*214//106,(x+1)*214//106)]
            row.append(sum(round(sum((c>>shift)&15 for c in cells)/len(cells))<<shift for shift in (8,4,0)))
        result.append(row)
    return result


def encode(raw):
    return slot(picture(picture_record(shrink(raw),107,42,40)))


def slot(record):
    if len(record)>memmap.FLOOR_PREVIEW_GRAY: raise ValueError('Floor picture exceeds its native slot')
    gray=b''
    for i in range(2):
        pal=struct.unpack_from('<16H',record,10+32*i)
        gray+=pair_table(pal)+preview_bytes(pal)
    result=record.ljust(memmap.FLOOR_PREVIEW_GRAY,b'\0')+gray
    assert len(result)==memmap.FLOOR_PREVIEW_BYTES
    return result


def build(export_shareware=False):
    OUT.mkdir(parents=True,exist_ok=True)
    renderer=Renderer();records=[];receipt=[]
    if export_shareware and PROFILE.key!='shareware': raise ValueError('Only shareware captures may be exported as repo assets')
    for floor in range(PROFILE.floors):
        rows,data,identity=renderer.floor_inputs(floor)
        cache=OUT/f'floor-{floor+1:02d}.json'
        shipped=ROOT/'data/frontend-previews/shareware'/cache.name
        old={}
        for path in (cache,shipped) if PROFILE.key=='shareware' else (cache,):
            if path.exists():
                doc=json.loads(path.read_text())
                if doc.get('identity')==identity:old=doc;break
        if old:
            raw=zlib.decompress(base64.b85decode(old['rgb12_z85']))
        else:
            raw=renderer.render(floor,rows,data)
            old=dict(profile=PROFILE.key,floor=floor,identity=identity,
                     renderer_sha256=renderer.identity,crop=[52,26,214,107],difficulty=2,weapon=False,
                     rgb12_sha256=hashlib.sha256(raw).hexdigest(),rgb12_z85=base64.b85encode(zlib.compress(raw,9)).decode())
        assert len(raw)==214*107*2 and hashlib.sha256(raw).hexdigest()==old['rgb12_sha256']
        text=json.dumps(old,indent=2)+'\n';cache.write_text(text)
        if export_shareware:shipped.parent.mkdir(parents=True,exist_ok=True);shipped.write_text(text)
        record=encode(raw);records.append(record)
        receipt.append(dict(floor=floor,identity=identity,rgb12_sha256=old['rgb12_sha256'],record_sha256=hashlib.sha256(record).hexdigest()))
        print(f'Native floor preview {floor+1}/{PROFILE.floors}: {len(record)} bytes',flush=True)
    from frontend.preview_art import portrait_paths
    for path in portrait_paths():records.append(slot(picture(path.read_bytes())))
    blob=b''.join(records)
    for region in load_regions():
        at=region['start']-memmap.FLOOR_PREVIEWS
        (ASSETS/region['file']).write_bytes(blob[at:at+region['end']-region['start']])
    (ASSETS/'floor-previews.json').write_text(json.dumps(dict(profile=PROFILE.key,renderer_sha256=renderer.identity,
        bytes=len(blob),regions=load_regions(),floors=receipt),indent=2)+'\n')
