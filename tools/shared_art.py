"""Prepare shared indexed art and exact floor-local placement programs."""
import memmap
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct

import lz16
from native_map_format import wall_material
from wolfdata import ROOT, PROFILE, maps, vswap

SOURCE_ADDRESS=memmap.SHARED_SOURCE
PLAN_ADDRESS=memmap.SHARED_PLAN
MAX_RECORDS=790


def mapped(raw, colors):
    return b''.join(bytes(colors[c]) for c in raw)


def source_atlas():
    pages,base,_=vswap()
    pieces=defaultdict(set)
    for floor in range(PROFILE.floors):
        sprites=json.loads((ROOT/f'build/levels/{floor}/sprites.json').read_text())
        for shape,frame in sprites.items():
            if frame['weapon']:continue
            for column in frame['columns']:
                for a,b,raw in column:
                    if a<200:pieces[int(shape)].add(bytes(raw))
    resources={('wall',p):bytes(pages[p]) for p in range(base) if len(pages[p])==4096}
    for shape,runs in pieces.items():
        data=bytearray()
        for raw in sorted(runs,key=lambda b:(-len(b),b)):
            if raw not in data:data.extend(raw)
        resources['sprite',shape]=bytes(data)
    banks=[];locations=defaultdict(list)
    for key,raw in sorted(resources.items()):
        start=0
        while start<len(raw):
            stop=min(len(raw),start+16384);piece=raw[start:stop]
            if not banks or banks[-1]['kind']!=key[0] or len(banks[-1]['raw'])+len(piece)>16384:
                banks.append(dict(kind=key[0],raw=bytearray()))
            bank=banks[-1]
            locations[key].append((start,stop,len(banks)-1,len(bank['raw'])))
            bank['raw'].extend(piece)
            if stop==len(raw):break
            start=stop-63
    folder=ROOT/'build/shared-art';folder.mkdir(exist_ok=True)
    for i,bank in enumerate(banks):
        raw=struct.pack('<%dH'%len(bank['raw']),*(c*2 for c in bank['raw']))
        raw+=bytes(-len(raw)%512)
        path=folder/f'source-{i:02}.bin';path.write_bytes(raw)
        bank.update(file=str(path.relative_to(ROOT)),data=raw)
    return resources,locations,banks


def floor_pieces(floor):
    folder=ROOT/f'build/levels/{floor}'
    rows=json.loads((folder/'registered-art-loads.json').read_text())
    memory=bytearray(memmap.FAST_RAM_END)
    for row in rows:
        raw=(folder/row['file']).read_bytes();memory[row['address']:row['address']+len(raw)]=raw
    palette=json.loads((ROOT/f'build/palettes/{floor}.json').read_text())
    palette['sprite_lights']=json.loads((folder/'pool-colors.json').read_text())
    pages,base,_=vswap();level=maps()[floor]
    tiles={m for t in level['planes'][0] if (m:=wall_material(t)) is not None}
    if 21 in tiles:tiles.add(22)
    wallpages=sorted({p for t in tiles for p in (2*(t-1),2*(t-1)+1)}|set(range(base-8,base)))
    originals={}
    for p in wallpages:
        if len(pages[p])!=4096:continue
        for u in range(0,4096,64):originals.setdefault(bytes(pages[p][u:u+64]),p)
    pieces=[]
    for i,raw in enumerate(sorted(originals)):
        for light in range(4):
            address=struct.unpack_from('<I',memory,0xa0000+i*16+light*4)[0]
            pieces.append((address,raw,('wall',originals[raw]),light))
    frames=(folder/'spriteFrame.bin').read_bytes()
    sprites=json.loads((folder/'sprites.json').read_text())
    for shape,frame in sprites.items():
        if frame['weapon']:continue
        shape=int(shape);header=memmap.SPRITE_CMDS+struct.unpack_from('<H',frames,shape*2)[0]
        command_bank=struct.unpack_from('<H',memory,header+196)[0]
        banks=memory[header+198:header+202]
        for x,column in enumerate(frame['columns']):
            cmd=(command_bank<<16)+struct.unpack_from('<H',memory,header+x*2)[0]
            for a,b,values in sorted(column,reverse=True):
                assert struct.unpack_from('<H',memory,cmd)[0]==a|(b<<8)
                if a>=200:
                    cmd+=10
                    continue
                raw=bytes(values)
                for light in range(4):
                    offset=struct.unpack_from('<H',memory,cmd+2+light*2)[0]
                    address=(banks[light]<<16)+offset+(a*2 if a<200 else 0)
                    pieces.append((address,raw,('sprite',shape),light))
                cmd+=10
    for address,raw,key,light in pieces:
        expected=mapped(raw,palette[key[0]+'_lights'][light])
        assert memory[address:address+len(expected)]==expected,(floor,address,key,light)
        assert address>>16==(address+len(expected)-1)>>16
    return memory,palette,pieces,rows


def make_floor(floor,resources,locations,banks,excluded=()):
    memory,palette,pieces,rows=floor_pieces(floor)
    cover=bytearray(len(memory));programs=defaultdict(list)
    grouped={}
    for address,raw,key,light in pieces:
        if address>>16==0x1d:continue
        grouped.setdefault((key,raw),[set() for _ in range(4)])[light].add(address)
    candidates=[]
    for (key,raw),destinations in grouped.items():
        lists=[sorted(d) for d in destinations]
        for i in range(max(map(len,lists))):
            dest=[d[i] if i<len(d) else None for d in lists]
            candidates.append((key,raw,dest))
    for key,raw,dest in sorted(candidates,key=lambda p:(-len(p[1]),p[0],p[1])):
        n=len(raw)*2
        if all(a is None or all(cover[a:a+n]) for a in dest):continue
        source=resources[key].find(raw)
        assert source>=0
        chunk,source_end,bank,offset=next(c for c in locations[key] if c[0]<=source and source+len(raw)<=c[1])
        if bank in excluded:continue
        source=0x8000+(offset+source-chunk)*2
        addresses=[];record=bytearray(struct.pack('<H',source));written=0
        for a in dest:
            if a is not None and all(cover[a:a+n]):a=None
            addresses.append(a)
            if a is not None:cover[a:a+n]=bytes([1])*n;written+=n
            bias=((a if a is not None else 0x1d0000)-source)&0xffffff
            record.extend(bias.to_bytes(3,'little'))
        entry=(-len(raw))%2;loops=(len(raw)+1)//2
        record.extend(struct.pack('<BBH',entry,0,loops))
        programs[bank].append((bytes(record),written,addresses))
    folder=ROOT/f'build/shared-art/floor-{floor:02}';folder.mkdir(exist_ok=True)
    sparse=[];omitted=0;masked=0;omitted_files=[]
    for row in rows:
        start=row['address'];raw=bytes(memory[start:start+row['bytes']]);mask=cover[start:start+len(raw)]
        masked+=sum(mask)
        if all(mask):
            omitted+=1;omitted_files.append(row['file']);continue
        if not any(mask):continue
        data=bytearray();at=0;copies=0;commands=0
        while at<len(raw):
            skip=mask[at];stop=at+1
            while stop<len(raw) and mask[stop]==skip:stop+=1
            if skip:
                length=stop-at
                while length:
                    n=min(length,32767);data.append(n if n<128 else 0)
                    if n>=128:data.extend(struct.pack('<H',n))
                    data.extend(b'\0\0');length-=n;commands+=1
            else:
                packed,stats=lz16.compress(raw[at:stop]);data.extend(packed)
                copies+=stop-at;commands+=stats['commands']
            at=stop
        path=folder/(row['file']+'.sparse')
        payload=struct.pack('<H',len(raw)&65535)+b'\2'+data
        if len(payload)>65536:raise ValueError('Sparse art exceeds staging bank')
        path.write_bytes(payload)
        sparse.append(dict(file=row['file'],address=start,bytes=len(raw),payload=str(path.relative_to(ROOT)),copied_bytes=copies,commands=commands))
    plans=[];reconstructed=bytearray(memory)
    for i,v in enumerate(cover):
        if v:reconstructed[i]=0xa5
    for bank,commands in sorted(programs.items()):
        for part in range(0,len(commands),MAX_RECORDS):
            selected=commands[part:part+MAX_RECORDS];kind=banks[bank]['kind']
            table=palette[kind+'_lights']
            plan=bytearray(bytes(v for light in table for pair in light for v in pair))
            total=sum(r[1] for r in selected)
            plan.extend(struct.pack('<HH',len(selected),total//512))
            for record,n,addresses in selected:
                plan.extend(record)
                source=struct.unpack_from('<H',record)[0]
                entry,_,loops=struct.unpack_from('<BBH',record,14)
                length=loops*2-entry
                values=struct.unpack_from('<%dH'%length,banks[bank]['data'],source-0x8000)
                for light,address in enumerate(addresses):
                    if address is None:continue
                    rebuilt=mapped(bytes(v//2 for v in values),table[light])
                    assert rebuilt==memory[address:address+len(rebuilt)]
                    reconstructed[address:address+len(rebuilt)]=rebuilt
            assert len(plan)<=16384
            packed,stats=lz16.compress(plan)
            payload=struct.pack('<H',len(plan))+b'\1'+packed
            assert len(payload)<=16384
            name=f'bank-{bank:02}-part-{part//MAX_RECORDS:02}'
            (folder/(name+'.bin')).write_bytes(plan)
            (folder/(name+'.lz')).write_bytes(payload)
            plans.append(dict(bank=bank,kind=kind,file=str((folder/(name+'.bin')).relative_to(ROOT)),payload=str((folder/(name+'.lz')).relative_to(ROOT)),output_bytes=total,commands=len(selected),pixel_iterations=sum((struct.unpack_from('<H',r[0],16)[0]*2-r[0][14]) for r in selected),plan_bytes=len(plan),stored_bytes=len(payload),decode_commands=stats['commands']))
    assert reconstructed==memory
    report=dict(floor=floor,covered_bytes=masked,source_banks=len(programs),source_bytes=sum(len(banks[b]['data']) for b in programs),records=sum(len(p) for p in programs.values()),plan_bytes=sum(p['stored_bytes'] for p in plans),plans=plans,sparse=sparse,omitted_files=omitted_files,omitted_rows=omitted,original_rows=len(rows),estimated_load_records=len(rows)-omitted+len(programs)+len(plans))
    # Leave room for floor logic, sound, lookup tables and music in the
    # resident two-page directory. Retain the least productive source group
    # in its existing baked representation when a floor reaches that limit.
    if report['estimated_load_records']>118:
        bank=min(programs,key=lambda b:sum(r[1] for r in programs[b])/(1+(len(programs[b])+MAX_RECORDS-1)//MAX_RECORDS))
        return make_floor(floor,resources,locations,banks,excluded+tuple([bank]))
    report['baked_source_banks']=list(excluded)
    (folder/'plan.json').write_text(json.dumps(report,indent=2)+'\n')
    print('shared floor',floor+1,'covered',masked,'sources',len(programs),'records',report['estimated_load_records'],flush=True)
    return report


def main():
    resources,locations,banks=source_atlas()
    reports=[make_floor(f,resources,locations,banks) for f in range(PROFILE.floors)]
    result=dict(source_banks=[dict(kind=b['kind'],file=b['file'],bytes=len(b['data'])) for b in banks],floors=reports)
    (ROOT/'build/shared-art/manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print('shared sources',sum(len(b['data']) for b in banks),'plan bytes',sum(r['plan_bytes'] for r in reports),'max records',max(r['estimated_load_records'] for r in reports))


if __name__=='__main__':main()


def storage_rows(floor, rows):
    """Replace baked pixel spans, retaining every renderer address and shade."""
    report=json.loads((ROOT/f'build/shared-art/floor-{floor:02}/plan.json').read_text())
    omitted=set(report['omitted_files'])
    sparse={r['file']:r for r in report['sparse']}
    result=[]
    for row in rows:
        name=Path(row['file']).name
        if name in omitted:continue
        row=dict(row)
        if name in sparse:
            item=sparse[name]
            row.update(encoded=item['payload'],codec='sparse',
                       decode_cycles=item['copied_bytes']*7+item['commands']*88)
        result.append(row)
    manifest=json.loads((ROOT/'build/shared-art/manifest.json').read_text())
    plans=defaultdict(list)
    for p in report['plans']:plans[p['bank']].append(p)
    order=0
    for bank,items in sorted(plans.items()):
        result.append(dict(file=manifest['source_banks'][bank]['file'],address=SOURCE_ADDRESS,
                           shared_source=True,sequence=order));order+=1
        for item in items:
            plan=(ROOT/item['file']).read_bytes()
            count,work=struct.unpack_from('<HH',plan,2048)
            assert len(plan)==2052+count*18
            credit=len(plan)//512+work
            cycles=len(plan)*7+item['decode_commands']*88+item['pixel_iterations']*72+item['commands']*240
            result.append(dict(file=item['file'],address=0xff0000|credit,encoded=item['payload'],
                               codec='plan',decode_cycles=cycles,sequence=order));order+=1
    return result
