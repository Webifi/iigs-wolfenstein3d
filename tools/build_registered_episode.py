"""Campaign floors and cold groups in a lossless shared-art EP08 store."""
import memmap
import argparse
import hashlib
import json
import os
import struct
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import b1
import hlz
import storage_codec
import episode_directory as directory
from elf import read
from registered_loads import (art_rows, group_rows, read_rows, include, title_restore_rows, AUX_WEIGHTS_BASE, AUX_WEAPONS_BASE, AUX_UI,
                              AUX_GAME_BASE, AUX_DEMOS_BASE, AUX_TALLY, AUX_PAUSE_BASE)
from wolfdata import ROOT, PROFILE
from build_logic import RAW_PLANES_ADDRESS, LAYOUT


def cache_piece(piece):
    packed = b1.compress(piece, ROOT/'build/b1cache')
    return len(piece), len(packed)


def precache(rows, jobs):
    """Independent host compression; native data and decoder stay unchanged."""
    import shared_cache
    jobs = min(jobs, int(os.environ.get('WOLF_JOBS') or jobs))
    pieces = {}
    cache = ROOT/'build/b1cache'
    for row in rows:
        if row.get('raw', False) or 'encoded' in row:
            continue
        raw = bytes(row['data']) if 'data' in row else (ROOT/row['file']).read_bytes()
        at = 0
        while at < len(raw):
            address = row['address'] + at
            size = min(len(raw)-at, 65536-(address & 65535))
            piece = raw[at:at+size]
            at += size
            if address >> 16 == 0x1d:
                continue
            key = hashlib.sha1(b'B1v1'+piece).hexdigest()
            path = shared_cache.codec_path('b1', b1.cache_identity(), piece) or cache/key[:2]/(key+'.b1')
            if not path.exists():
                pieces[key] = piece
    print(f'Compression cache: {len(pieces)} independent units, {jobs} host workers', flush=True)
    if jobs == 1:
        for piece in pieces.values():
            cache_piece(piece)
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for i, _ in enumerate(pool.map(cache_piece, pieces.values()), 1):
                if i % 50 == 0 or i == len(pieces):
                    print(f'Compressed {i}/{len(pieces)} units', flush=True)


class Store:
    def __init__(self, groups, medium="hd"):
        self.settings=storage_codec.policy(ROOT,medium)
        self.data=directory.create(PROFILE.floors,groups,record_pages=2,wide_blocks=True,fast_codecs=3,compact=True)
        self.cache={};self.manifest=[];self.links=[];self.lists=[];self.splits={};self.title_prefix={}

    def units(self, rows, label):
        records=[]
        floor=label.startswith('floor/')
        if floor:
            # Two runs (floor_rows): the episode-disk run, then the floor-disk run. The loader
            # reads either one first (src/iigs/leveldirectory.s planRuns). Rows keep their order
            # inside a slot; the effects go shared first, then the floor's own, by address.
            rows=sorted(rows,key=lambda r:(r['run'],r['slot'],int(not r.get('shared')) if r.get('by_share') else 0,
                                           r['address'] if r.get('by_share') else 0))
            if len(rows)>128:
                rows=join_effect_rows(rows)
                rows=join_logic_rows(rows)
            self.splits[label]=0
        else:
            rows=sorted(rows,key=lambda r:(1 if 'sequence' in r else 2 if r['address']>>16==0x1d else 0,r.get('sequence',r['address'])))
        for row in rows:
            raw=bytes(row['data']) if 'data' in row else (ROOT/row['file']).read_bytes()
            base=row['address'];at=0
            while at<len(raw):
                address=base+at;size=min(len(raw)-at,65536-(address&65535))
                # A whole bank $1D (a pause restore) decodes in place in its own stage
                # bank (src/iigs/levelio.s); its last block loads raw after it.
                in_place=(not floor and address==memmap.BOOT_STAGE and size==65536
                          and not row.get('raw') and not row.get('shared_source'))
                if in_place:size=IN_PLACE_BYTES
                piece=raw[at:at+size]
                digest=hashlib.sha256(piece).hexdigest()
                force_raw=row.get('raw',False) or (not floor and address>>16==0x1d and not row.get('shared_source') and not in_place)
                run=row.get('run',0)
                stage=row['stage'] if floor else (memmap.BOOT_STAGE,memmap.BOOT_STAGE_END)
                key=(digest,force_raw,bool(row.get('shared_source')),floor,bool(row.get('packed')))
                if self.settings[0]=='floppy' and not force_raw and not row.get('shared_source'):
                    # HLZ is offered only where the loader can decode it (hlz_fits).
                    key+=('hlz' if hlz_fits(address,len(piece),stage) else 'no hlz',)
                if in_place:
                    key=(digest,'in place')
                    if key not in self.cache:
                        options=[o for o in storage_codec.candidates(piece,ROOT/'build/b1cache',self.settings,False,b1_allowed=False)
                                 if o['codec'] in ('raw','lzsa1')]
                        packed=[o for o in options if o['codec']=='lzsa1']
                        if not packed or not in_place_safe(packed[0]['payload'],len(piece)):
                            raise ValueError(f'{label}: {row.get("file")} cannot decode in place')
                        self.cache[key]=dict(options=options,selected=storage_codec.choose(options,self.settings[0]))
                if 'encoded' in row:
                    payload=(ROOT/row['encoded']).read_bytes()
                    key=(hashlib.sha256(payload).hexdigest(),row['codec'])
                    blocks=(len(payload)+511)//512
                    option=dict(codec=row['codec'],payload=payload,blocks=blocks,
                                estimated_cycles=row['decode_cycles']+blocks*self.settings[1]['block_cycles'])
                    self.cache.setdefault(key,dict(options=[option],selected=option))
                if key not in self.cache:
                    try:
                        options=storage_codec.candidates(piece,ROOT/'build/b1cache',self.settings,force_raw,b1_allowed=False)
                    except storage_codec.NoBankSafeEncoding:
                        # An incompressible unaligned tail can exceed the input
                        # bank. Its sector-sized prefix can always be stored raw.
                        size=(size//512)*512
                        if not size:raise
                        piece=raw[at:at+size]
                        digest=hashlib.sha256(piece).hexdigest();key=(digest,force_raw,bool(row.get('shared_source')))
                        options=storage_codec.candidates(piece,ROOT/'build/b1cache',self.settings,force_raw,b1_allowed=False)
                    if row.get('shared_source'):
                        options=[o for o in options if o['blocks']*512<=32768]
                    if row.get('packed'):
                        # A title slice can end beside live art: write its exact length.
                        options=[o for o in options if o['codec']!='raw']
                    if floor:
                        # The boot B1 decoder reads bank $1D; packed input must fit the row's stage.
                        options=[o for o in options if o['codec']=='raw' or (o['codec']!='b1' and o['blocks']*512<=stage[1]-stage[0])]
                        if not options and (address&0xffff)+(size+511)//512*512<=0x10000:
                            # A unit whose block padding stays inside its own bank (sight
                            # tables, song halves) may load raw.
                            options=storage_codec.candidates(piece,ROOT/'build/b1cache',self.settings,True,b1_allowed=False)
                        if not options:raise ValueError(f'{label}: no floor-stage encoding for {row.get("file","data")}')
                    if self.settings[0]=='floppy':
                        # Floppy stores take the smallest encoding, HLZ where it fits.
                        if not force_raw and not row.get('shared_source') and hlz_fits(address,len(piece),stage):
                            option=hlz_option(piece,self.settings,stage[1]-stage[0])
                            if option:options.append(option)
                        selected=smallest(options)
                    else:
                        selected=storage_codec.choose([o for o in options if o['codec']!='lz16'],self.settings[0])
                    self.cache[key]=dict(options=options,selected=selected)
                at+=size
                record=[address&65535,address>>16,0,0]
                item=dict(group=label,asset=row.get('file','linked logic'),address=address,bytes=size,sha256=digest)
                if row.get('title_only'):item['title_only']=True
                if floor:
                    item['run']=('episode','floor')[run]
                    item['stage']=stage[0]>>16
                    if not run:self.splits[label]+=1
                if 'encoded' in row:item['encoded']=row['encoded']
                if in_place:item['in_place']=True
                records.append(record);self.manifest.append(item)
                self.links.append((key,record,item))
        return records

    def compact_loads(self, entries):
        """Spend part of the new decoder's gain on smaller data, load by load.

        Shared units charge every affected load. Retain the profile's fraction of the achievable
        estimated gain as a margin; no load may exceed its previous policy.
        """
        import collections
        import heapq
        users={key:collections.Counter() for key in self.cache}
        for key,record,item in self.links:users[key][item['group']]+=1
        budgets=collections.Counter();costs=collections.Counter()
        for key,row in self.cache.items():
            old=row['selected'];new=storage_codec.choose(row['options'],self.settings[0]);row['selected']=new
            for group,n in users[key].items():
                budgets[group]+=old['estimated_cycles']*n
                costs[group]+=new['estimated_cycles']*n
        original=dict(budgets)
        retain=self.settings[1]['retain_load_gain_percent']
        for group in budgets:budgets[group]-=max(0,(budgets[group]-costs[group])*retain//100)
        keys=list(self.cache);queue=[]
        def alternatives(i):
            row=entries[i];old=row['selected']
            for choice in row['options']:
                saved=old['blocks']-choice['blocks']
                if saved>0:
                    delta=choice['estimated_cycles']-old['estimated_cycles']
                    heapq.heappush(queue,(delta/saved,i,choice['codec'],old['codec']))
        for i in range(len(entries)):alternatives(i)
        while queue:
            _,i,codec,previous=heapq.heappop(queue);row=entries[i]
            if row['selected']['codec']!=previous:continue
            choice=next(x for x in row['options'] if x['codec']==codec)
            delta=choice['estimated_cycles']-row['selected']['estimated_cycles']
            if any(costs[g]+delta*n>budgets[g] for g,n in users[keys[i]].items()):continue
            for group,n in users[keys[i]].items():costs[group]+=delta*n
            row['selected']=choice;alternatives(i)
        self.load_budgets={g:dict(previous_cycles=original[g],limit_cycles=budgets[g],selected_cycles=costs[g]) for g in budgets}
        assert all(costs[g]<=original[g] for g in budgets)

    def play_positions(self):
        """Each floor's place in play order (tools/floppy_layout.py play_order)."""
        if not hasattr(self,'positions'):
            import floppy_layout
            order=floppy_layout.play_order(json.loads((ROOT/'build/gen/campaign.json').read_text()))
            self.positions={f:float(n) for n,f in enumerate(order)}
        return self.positions

    def disk_order(self):
        """Store order for the floppies (tools/floppy_layout.py copies store runs to the disks;
        a disk header lists a limited number of runs). A floor load has an episode-disk part and a
        floor-disk part (floor_rows), and each disk holds consecutive floors in play order. So:
        first the blocks that every data disk holds (the play groups, the shared weapon units,
        their lists); then the episode-disk units by the first floor that loads them in play
        order (among those, the ones more floors load first); then each floor's blocks that both
        of its disks hold (its record lists, its game and weapon groups); then the floor-disk
        units by their first floor; then the rest (the title's blocks)."""
        import collections
        position=self.play_positions()
        users=collections.defaultdict(set)
        events=PROFILE.document['audio']['events']
        tally=f"music/{PROFILE.music_names.index(events['tally'])}"
        for key,record,item in self.links:
            kind,n=item['group'].split('/');n=int(n)
            if kind=='floor':
                users[key].add((item['run'],n))
            elif kind=='aux' and (AUX_WEAPONS_BASE<=n<AUX_UI or AUX_GAME_BASE<=n<AUX_GAME_BASE+PROFILE.floors):
                users[key].add(('both',(n-AUX_WEAPONS_BASE)//4 if n<AUX_UI else n-AUX_GAME_BASE))
            elif (kind=='aux' and (AUX_WEIGHTS_BASE<=n<AUX_WEAPONS_BASE or n==AUX_TALLY or n>=AUX_PAUSE_BASE)) or item['group']==tally:
                users[key].add(('play',-1))
        order={id(row):n for n,row in enumerate(self.cache.values())}
        keys={id(row):key for key,row in self.cache.items()}
        def rank(row):
            used=users[keys[id(row)]];n=order[id(row)]
            kinds={k for k,_ in used};floors={f for _,f in used if f>=0}
            first=min((position[f] for f in floors),default=0.0)
            if 'play' in kinds or (kinds=={'both'} and len(floors)>1):return (0,0.0,0,n)
            if 'episode' in kinds:return (1,first,-len(floors),n)
            if 'both' in kinds:return (2,first,1,n)
            if 'floor' in kinds:return (3,first,-len(floors),n)
            return (4,0.0,0,n)
        return rank

    def plan_lists(self, floor_lists, aux):
        """Record lists as blobs in the store order. Each floor's records, its game group's list
        and its weapon groups' lists form one blob that both of its disks hold (disk_units),
        before the floor's other blocks of that kind; the other lists (play and title groups)
        with the blocks that every data disk holds."""
        game=lambda f:AUX_GAME_BASE+f
        placed=set();position=self.play_positions()
        def blob(rank,parts):
            # parts: ('floor', f) or ('aux', g); each aux list starts 4-aligned.
            size=0;layout=[]
            for kind,n in parts:
                records=floor_lists[n] if kind=='floor' else aux[n]
                length=len(records)*8 if kind=='floor' else 4+len(records)*8
                if kind=='aux' and (size%512)+length>1024:size+=-size%512
                layout.append((kind,n,size));size+=length
            self.lists.append(dict(rank=rank,layout=layout,
                                   selected=dict(payload=bytes(size),blocks=-(-size//512))))
        for f in range(PROFILE.floors):
            groups=[game(f)]+[AUX_WEAPONS_BASE+f*4+v for v in range(4)]
            placed.update(groups)
            blob((2,position[f],0,-1),[('floor',f)]+[('aux',g) for g in groups])
        blob((0,0.0,0,-1),[('aux',g) for g in range(len(aux)) if g not in placed])

    def write_lists(self, floor_lists, aux):
        """Fill the placed list blobs; return the floor and auxiliary index entries."""
        floors=[None]*len(floor_lists);groups=[None]*len(aux)
        for row in self.lists:
            base=row['block']*512
            for kind,n,offset in row['layout']:
                at=base+offset
                if kind=='floor':
                    assert offset==0
                    for i,record in enumerate(floor_lists[n]):struct.pack_into('<4H',self.data,at+8*i,*record)
                    floors[n]=(row['block'],len(floor_lists[n]))
                else:
                    records=aux[n];struct.pack_into('<2H',self.data,at,len(records),self.title_prefix.get(n,0))
                    for i,record in enumerate(records):struct.pack_into('<4H',self.data,at+4+8*i,*record)
                    inner=offset%512;length=4+8*len(records)
                    groups[n]=(row['block']+offset//512,inner,1 if inner+length<=512 else 2)
        assert None not in floors and None not in groups
        return floors,groups

    def finish_packing(self):
        # Native boot/menu data also occupies the two ProDOS volumes. Reserve
        # six MiB for it; the media builder validates the exact final capacity.
        capacity=self.settings[1]['max_store_mib']*1024*1024//512-len(self.data)//512
        entries=list(self.cache.values())
        blocks=sum(x['selected']['blocks'] for x in entries)
        if blocks>capacity:
            if self.settings[0] in ('b1','raw','lzsa1'):
                raise ValueError('Requested codec exceeds the two-volume budget; use hd or floppy selection')
            import heapq
            queue=[]
            def alternatives(i):
                row=entries[i];old=row['selected']
                for choice in row['options']:
                    if choice['codec']=='lz16':continue
                    saved=old['blocks']-choice['blocks']
                    if saved>0:
                        penalty=(choice['estimated_cycles']-old['estimated_cycles'])/saved
                        heapq.heappush(queue,(penalty,i,choice['codec'],old['codec']))
            for i in range(len(entries)):alternatives(i)
            while blocks>capacity and queue:
                _,i,codec,previous=heapq.heappop(queue);row=entries[i]
                if row['selected']['codec']!=previous:continue
                choice=next(x for x in row['options'] if x['codec']==codec)
                blocks-=row['selected']['blocks']-choice['blocks']
                row['selected']=choice;alternatives(i)
            if blocks>capacity:raise ValueError('Lossless level store cannot fit the two-volume budget')
        if self.settings[0]=='hd':
            self.compact_loads(entries)
        if sum(r['selected']['blocks'] for r in entries)>capacity:
            raise ValueError('Load-time constrained store exceeds the volume budget')
        rank=self.disk_order()
        for row in sorted(entries+self.lists,key=lambda row:row['rank'] if 'layout' in row else rank(row)):
            row['block']=len(self.data)//512
            payload=row['selected']['payload']
            self.data.extend(payload);self.data.extend(bytes(-len(self.data)%512))
        for key,record,item in self.links:
            selected=self.cache[key]['selected'];block=self.cache[key]['block']
            codec=selected['codec'];size=item['bytes'];address=item['address'];packed=codec!='raw'
            if not packed and address+selected['blocks']*512>(address&~65535)+65536:
                raise ValueError('Raw padding crosses a live bank')
            stage=item['stage'] if item['group'].startswith('floor/') else memmap.BOOT_STAGE>>16
            if packed and address==stage<<16 and not item.get('in_place'):
                raise ValueError(f'{item["group"]}: packed unit at its stage start decodes in place unchecked')
            flags=(address>>16)|(int(packed)<<8)|((((size+2047)//2048)&31)<<9 if packed else 0)
            flags|=(int(codec in ('lzsa1','literal','lz16','sparse','plan','hlz'))<<14)|((block>>16)<<15)
            record[:]=[address&65535,flags,block&65535,selected['blocks']]
            item.update(first_block=block,blocks=selected['blocks'],b1=codec=='b1',codec=codec,
                        estimated_cycles=selected['estimated_cycles'])


def play_groups(aux_groups):
    """The groups that load during play, by part: the view weights, the in-game pause pages
    (and, after them, the play cache's fill groups) and the tally (its song and its lump)."""
    events=PROFILE.document['audio']['events']
    song=PROFILE.music_names.index(events['tally'])
    return dict(weights=[f'aux/{g}' for g in range(AUX_WEIGHTS_BASE,AUX_WEAPONS_BASE)],
                pause=[f'aux/{g}' for g in range(AUX_PAUSE_BASE,aux_groups)],
                tally=[f'music/{song}',f'aux/{AUX_TALLY}'])


def shared_units(store):
    """[[first block, blocks], ...]: the units of the weapon and game groups that more than one
    floor loads (the weapon pictures and masks), not a floor's own weapon table or restores.
    A view change reads them (ui_overlays.s EnsureViewAssets)."""
    import collections
    users=collections.defaultdict(set)
    for item in store.manifest:
        if item.get('title_only'):continue
        kind,n=item['group'].split('/');n=int(n)
        if kind=='aux' and AUX_WEAPONS_BASE<=n<AUX_UI:
            users[(item['first_block'],item['blocks'])].add((n-AUX_WEAPONS_BASE)//4)
        elif kind=='aux' and AUX_GAME_BASE<=n<AUX_GAME_BASE+PROFILE.floors:
            users[(item['first_block'],item['blocks'])].add(n-AUX_GAME_BASE)
    return sorted([list(r) for r,floors in users.items() if len(floors)>1])


def play_parts(store, aux_groups):
    """The store blocks that the loads during play read, by part: the units of the play
    groups (play_groups), the shared weapon units (shared_units) and the record lists of the
    play groups. {part: set of blocks}"""
    span=lambda ranges:{b for first,count in ranges for b in range(first,first+count)}
    groups=play_groups(aux_groups)
    parts={name:span([i['first_block'],i['blocks']] for i in store.manifest if i['group'] in labels)
           for name,labels in groups.items()}
    parts['weapons']=span(shared_units(store))
    labels={g for names in groups.values() for g in names}
    lists=span([row['block'],row['selected']['blocks']] for row in store.lists
               if any(f'{kind}/{n}' in labels for kind,n,_ in row['layout']))
    parts['lists']=lists-set().union(*parts.values())
    return parts


def block_runs(blocks):
    """[[first block, blocks], ...] of a set of blocks."""
    runs=[]
    for b in sorted(blocks):
        if runs and runs[-1][0]+runs[-1][1]==b:
            runs[-1][1]+=1
        else:
            runs.append([b,1])
    return runs


def disk_units(store, aux_groups, assets, play_floors=None):
    """The store blocks of each floor load, of the loads during play and of the title, for
    the floppy layout (tools/floppy_layout.py): units and record lists.

    A floor load has two parts (floor_rows): "shared" goes on an episode disk, "own" on a
    floor disk. The loader reads the part on the disk in the drive first, so a load ends on
    either disk. Both parts hold the floor's record lists and the units of its game group and
    weapon groups that only this floor loads (after a floor load the game reads these groups
    from the disk in the drive, ui_overlays.s EnsureViewAssets); the units that many floors'
    groups share are play data."""
    ranges={};parts={};owners={}
    for item in store.manifest:
        ranges.setdefault(item['group'],[]).append([item['first_block'],item['blocks']])
        if 'run' in item:
            parts.setdefault((item['group'],item['run']),[]).append([item['first_block'],item['blocks']])
        kind,n=item['group'].split('/');n=int(n)
        if kind=='aux' and (AUX_WEAPONS_BASE<=n<AUX_UI or AUX_GAME_BASE<=n<AUX_GAME_BASE+PROFILE.floors):
            owners.setdefault(item['first_block'],set()).add((n-AUX_WEAPONS_BASE)//4 if n<AUX_UI else n-AUX_GAME_BASE)
    for row in store.lists:
        for kind,n,_ in row['layout']:
            ranges.setdefault(f'{kind}/{n}',[]).append([row['block'],row['selected']['blocks']])
            if kind=='floor':
                parts.setdefault((f'floor/{n}','list'),[]).append([row['block'],row['selected']['blocks']])
    # Play (play_parts; on disk 1, which the boot reads them from, and as play_floors says):
    # the view weights, the in-game pause pages, the tally, the weapon units that many floors use.
    # Title data goes on the home disk: the UI group, demo inputs and the songs
    # for the title, scores, victory and Spear ending. A return to the title needs
    # that disk. View weights load after floor assets (ui_overlays.s EnsureViewAssets),
    # with the floor's disk in the drive. SelectMusic does not request the menu song.
    events=PROFILE.document['audio']['events']
    song=lambda event:PROFILE.music_names.index(events[event])
    pick=lambda labels:[r for g in labels for r in ranges.get(g,[])]
    floors=[]
    for f in range(PROFILE.floors):
        own=[r for g in [AUX_GAME_BASE+f]+[AUX_WEAPONS_BASE+f*4+v for v in range(4)]
             for r in ranges.get(f'aux/{g}',[]) if owners.get(r[0],{f})=={f}]
        both=parts.get((f'floor/{f}','list'),[])+own
        floors.append(dict(shared=parts.get((f'floor/{f}','episode'),[])+both,own=parts.get((f'floor/{f}','floor'),[])+both))
    play=block_runs(set().union(*play_parts(store,aux_groups).values()))
    title=pick([f'aux/{AUX_UI}']+[f'aux/{g}' for g in range(AUX_DEMOS_BASE,AUX_TALLY)]
               +[f'music/{song(e)}' for e in (('title','scores','victory','ending') if PROFILE.spear else ('title','scores','victory'))])
    units=dict(floors=floors,play=play,title=title)
    if play_floors is not None:
        units['play_floors']=play_floors
    (assets/'episode-disk.json').write_text(json.dumps(units)+'\n')


PLAY_FILL_RECORDS = 16


def play_limits():
    """The first play cache slot each floor's art writes; the slot count when it writes none
    (tools/fixed_art.py pack_floor puts such art at the top of PLAY_CACHE)."""
    slots=memmap.PLAY_CACHE_SIZE//512
    limits=[]
    for f in range(PROFILE.floors):
        first=slots
        for r in art_rows(f):
            low,high=max(r['address'],memmap.PLAY_CACHE),min(r['address']+r['bytes'],memmap.PLAY_CACHE_END)
            if low<high:
                first=min(first,(low-memmap.PLAY_CACHE)//512)
        limits.append(first)
    return limits


def play_fill_starts(limits):
    """The first slots of the fill groups: 0 (all slots, the title) and each floor limit below
    the slot count (the slots that floor's art took, read back after it)."""
    return sorted({0}|{limit for limit in limits if limit<memmap.PLAY_CACHE_SIZE//512})


def play_cache(store, aux, fills, limits):
    """The play cache (memmap PLAY_CACHE; src/iigs/leveldirectory.s playLookup, ui_overlays.s
    PlayCacheFill): the store blocks of the loads during play (play_parts), as stored, in
    512-byte slots in store order, as many as PLAY_CACHE holds. fills: {first slot: group}
    (play_fill_starts); each group reads the slots from its first one to the last (raw
    records). Returns the root's play table and play_floors.

    The table (root block 1, u16 words): "PC02", fill groups, cached slots, then the offsets
    of the floor limits, of the fill groups, of the runs and of their end. Floor limits: per floor
    the first slot its art writes (play_limits). Fill groups: first slot and group, by first
    slot. Runs: first block, blocks, address, bank and first slot; a run stays in one bank and
    a fill group starts at a run.

    play_floors: {floor: [[first block, count], ...]}, the play blocks a floor's loads read
    from its disks: on a floor whose art takes slots, the blocks of those slots and of the ones
    above, and the same on each floor a route enters from it (its load reads them back); on
    every floor the play blocks that the cache cannot hold."""
    parts=play_parts(store,len(aux))
    blocks=sorted(set().union(*parts.values()))
    slots=memmap.PLAY_CACHE_SIZE//512
    cached=blocks[:slots]
    runs=[]
    for slot,block in enumerate(cached):
        address=memmap.PLAY_CACHE+512*slot
        if (runs and runs[-1][0]+runs[-1][1]==block and runs[-1][2]>>16==address>>16
                and slot not in fills):
            runs[-1][1]+=1
        else:
            runs.append([block,1,address,slot])
    if len(runs)>PLAY_FILL_RECORDS:
        raise ValueError(f'play cache: {len(runs)} runs, a fill group has room for {PLAY_FILL_RECORDS}')
    for first,group in fills.items():
        aux[group][:]=[[address&65535,address>>16,block,count] for block,count,address,slot in runs if slot>=first]
    assert PROFILE.floors==len(limits)
    head=16;fill_at=head+2*len(limits);run_at=fill_at+4*len(fills);end=run_at+10*len(runs)
    table=bytearray(end)
    struct.pack_into('<4s6H',table,0,b'PC02',len(fills),len(cached),head,fill_at,run_at,end)
    struct.pack_into(f'<{len(limits)}H',table,head,*limits)
    for i,(first,group) in enumerate(sorted(fills.items())):
        struct.pack_into('<2H',table,fill_at+4*i,first,group)
    for i,(block,count,address,slot) in enumerate(runs):
        struct.pack_into('<5H',table,run_at+10*i,block,count,address&65535,address>>16,slot)
    assert len(table)<=512,'the play table needs one root block'
    campaign=json.loads((ROOT/'build/gen/campaign.json').read_text())
    routes=[(f['index'],f[key]&0x3fff) for f in campaign['floors']
            for key in ('normal','secret','victory','spear') if f[key]<0xfffe]
    reads={}
    for f,limit in enumerate(limits):
        if limit<len(cached):
            for g in [f]+[b for a,b in routes if a==f]:
                reads.setdefault(g,set()).update(cached[limit:])
    if len(blocks)>slots:
        for f in range(PROFILE.floors):
            reads.setdefault(f,set()).update(blocks[slots:])
    play_floors={str(f):block_runs(b) for f,b in sorted(reads.items())}
    taken={f+1:slots-limit for f,limit in enumerate(limits) if limit<slots}
    print(f'play cache: {len(cached)} of {len(blocks)} play blocks ({slots} slots) in {len(runs)} runs; '
          'parts: '+', '.join(f'{name} {len(part)}' for name,part in parts.items())+'; '
          f'slots the art takes, by floor: {taken}; fill groups from slots {sorted(fills)}; '
          'play blocks read from the disks, by floor: '
          +', '.join(f'{int(f)+1}: {len(reads[int(f)])}' for f in play_floors),flush=True)
    return bytes(table),play_floors


# The stage of each floor row (Store.units, hlz_fits). The episode-disk run stages in
# FLOOR_STAGE until the generator is done, then in EFFECT_STAGE: the effects that end the run
# cover FLOOR_STAGE (src/iigs/load_fast.inc GenHook). The floor-disk run stages in
# FLOOR_PART_STAGE. EFFECT_STAGE and FLOOR_PART_STAGE are in LOGIC_ZERO, which the loader
# zero-fills after the last unit of the load (src/iigs/leveldirectory.s RunEnds).
STAGE_GENERATOR = (memmap.FLOOR_STAGE, memmap.FLOOR_STAGE_END)
STAGE_EFFECTS = (memmap.EFFECT_STAGE, memmap.EFFECT_STAGE_END)
STAGE_FLOOR_PART = (memmap.FLOOR_PART_STAGE, memmap.FLOOR_PART_STAGE_END)
IN_PLACE_BYTES = 0xfe00
HLZ_TABLES = 2 * 1024     # the decoder's lookup tables follow the packed unit in its stage
HLZ_MIN_BYTES = 1024      # the decoder reads the 598 code lengths into the output first
HLZ_IO = ((0x00c000, 0x00d000), (0x01c000, 0x01d000), (0xe0c000, 0xe0d000), (0xe1c000, 0xe1d000))


def hlz_fits(address, size, stage):
    """HLZ's own limits on where a unit goes (src/iigs/hlz.inc): at least HLZ_MIN_BYTES,
    output plus the two bytes after it (saved and put back) off I/O and off its stage
    (start, end): a STAGE_* of floor_rows for floor loads, all of bank BOOT_STAGE for the others."""
    end = address + size + 2
    if size < HLZ_MIN_BYTES or any(address < b and end > a for a, b in HLZ_IO):
        return False
    return not (address < stage[1] and end > stage[0])


def hlz_option(piece, settings, stage_bytes):
    """The HLZ encoding of a unit (cached by content), or None when its packed form and
    the tables do not fit the unit's stage of stage_bytes."""
    payload = hlz_piece(piece)
    stats = {}
    if hlz.decode(payload, len(piece), stats) != piece:
        raise ValueError('HLZ cached unit differs')
    blocks = (len(payload)+511)//512
    if blocks*512+HLZ_TABLES > stage_bytes:
        return None
    return dict(codec='hlz', payload=payload, blocks=blocks,
                estimated_cycles=blocks*settings[1]['block_cycles']+hlz.cycles(stats))


def hlz_piece(piece):
    """One HLZ cache entry (a host worker of hlz_precache)."""
    import shared_cache
    if shared_cache.folder():
        return shared_cache.codec('hlz', hlz.cache_identity(), piece, lambda: hlz.compress(piece))
    path = ROOT/'build/hlzcache'/(hashlib.sha256(hlz.cache_identity()+piece).hexdigest()+'.hlz')
    if not path.exists():
        shared_cache.atomic(path, hlz.compress(piece))
    return path.read_bytes()


def hlz_precache(row_lists, jobs):
    """Fill the cache of hlz_option for every packed unit of a floppy store, in parallel."""
    import shared_cache
    jobs = min(jobs, int(os.environ.get('WOLF_JOBS') or jobs))
    code = hlz.cache_identity()
    folder = ROOT/'build/hlzcache'
    folder.mkdir(parents=True, exist_ok=True)
    pieces = {}
    for rows in row_lists:
        for row in rows:
            if row.get('raw') or 'encoded' in row:
                continue
            raw = bytes(row['data']) if 'data' in row else (ROOT/row['file']).read_bytes()
            at = 0
            while at < len(raw):
                address = row['address']+at
                size = min(len(raw)-at, 65536-(address & 65535))
                piece = raw[at:at+size]
                at += size
                key = hashlib.sha256(code+piece).hexdigest()
                path = shared_cache.codec_path('hlz', code, piece) or folder/(key+'.hlz')
                if size >= HLZ_MIN_BYTES and not path.exists():
                    pieces[key] = piece
    print(f'HLZ cache: {len(pieces)} units to pack, {jobs} host workers', flush=True)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for i, _ in enumerate(pool.map(hlz_piece, pieces.values()), 1):
            if i % 50 == 0 or i == len(pieces):
                print(f'HLZ packed {i}/{len(pieces)} units', flush=True)


def smallest(options):
    """Floppy stores: the fewest blocks, then the fewest estimated cycles."""
    return min(options, key=lambda x: (x['blocks'], x['estimated_cycles']))


def in_place_safe(payload, size):
    """An LZSA1 payload (length word, stream) read into the end of its own bank and decoded
    to the bank start: no write may reach an input byte that is not read yet."""
    start=65536-(len(payload)+511)//512*512+2
    src=payload[2:];at=0;out=0
    def length(n,base,short,long):
        nonlocal at
        if n<base:return n
        x=src[at];at+=1
        if x==short:
            at+=1;return 256+src[at-1]
        if x==long:
            at+=2;return src[at-2]|src[at-1]<<8
        return base+x
    while out<size:
        token=src[at];at+=1
        n=length(token>>4&7,7,250,249)
        if out>start+at:return False
        out+=n;at+=n
        if out>=size:break
        at+=2 if token&128 else 1
        out+=length((token&15)+3,18,239,238)
        if out>start+at:return False
    return out==size
FIXED = ROOT/'build/fixed'


def write_fixed_units():
    """Shared generator units, written once (tools/fixed_units.py)."""
    import fixed_units
    FIXED.mkdir(parents=True, exist_ok=True)
    units = fixed_units.shared_units()
    (FIXED/'pages.bin').write_bytes(units['pages'])
    for k, chunk in enumerate(units['cols']):
        (FIXED/f'cols-{k:02}.bin').write_bytes(chunk)
    for g, (blob, tmpl) in enumerate(zip(units['blobs'], units['tmpls'])):
        (FIXED/f'blob-{g:02}.bin').write_bytes(blob)
        (FIXED/f'tmpl-{g:02}.bin').write_bytes(tmpl)
    (FIXED/'count.json').write_text(json.dumps(dict(chunks=len(units['cols']), groups=len(units['blobs'])))+'\n')


def generation_rows(floor):
    """The episode-disk run of a floor with the loader-built art: its wall pointer table
    (packed walls) and its program, then the page table, the generator, and the group,
    strip, template and column units in the generator's order. The generator finishes
    inside this run (src/iigs/fixed_gen.s); the effects follow it."""
    import fixed_units
    folder = ROOT/f'build/levels/{floor}'
    meta = json.loads((folder/'fixed.json').read_text())
    chunks = json.loads((FIXED/'count.json').read_text())['chunks']
    rel = lambda p: str(p.relative_to(ROOT))
    # The pointer table (packed walls) and the program load before the generator is
    # active and before the raw page table takes the start of the $3A stage.
    order = [dict(file=rel(folder/'fixed-wallptrs.bin'), address=memmap.WALL_LIGHT_POINTERS)] if meta.get('wall_pointers') else []
    order += [dict(file=rel(folder/'fixed-program.bin'), address=fixed_units.PROG),
              dict(file=rel(FIXED/'pages.bin'), address=fixed_units.PAGES, raw=True),
              dict(file='build/boot/fixed_gen.raw', address=fixed_units.GEN, raw=True)]
    for g, gid in enumerate(meta['groups']):
        order.append(dict(file=rel(FIXED/f'blob-{gid:02}.bin'), address=fixed_units.SRC))
        if meta['strips'][g]:
            # The floor's strips of this group, shared by every floor with the same strips.
            name, address = meta['strips'][g]
            order.append(dict(file=rel(FIXED/'strips'/name), address=address))
        order.append(dict(file=rel(FIXED/f'tmpl-{gid:02}.bin'), address=fixed_units.SRC))
    order += [dict(file=rel(FIXED/f'cols-{k:02}.bin'), address=fixed_units.SRC) for k in range(chunks)]
    if meta.get('quality'):
        # These fragments can end beside live art. Packed loads write their
        # exact lengths; raw sector padding would overwrite neighboring data.
        order += [dict(row, late=True, packed=True) for row in read_rows(folder/meta['quality'], folder)]
    if meta.get('baked'):
        # Per-floor packed art other than the walls; it loads after the generator is done.
        order += [dict(row, late=True) for row in read_rows(folder/meta['baked'], folder)]
    return order


def sight_rows(floor):
    """The sight units of the floor-disk run: the sight parameters (from the program) with
    the rooms, the lower matrix half at its rows, then the sight unit (src/iigs/sight_gen.s),
    which the loader calls once: it builds the sight tables and the upper matrix half."""
    folder = ROOT/f'build/levels/{floor}'
    meta = json.loads((folder/'fixed.json').read_text())
    if meta.get('sight_rows') is None:
        return []
    program = (folder/'fixed-program.bin').read_bytes()
    at = struct.unpack_from('<H', program, 12)[0]
    params = program[at:at + 7] + bytes(1)        # addr24 rows, u16 stride, u16 rooms
    rooms = (folder/'sight-rooms.bin').read_bytes()
    assert int.from_bytes(params[:3], 'little') == meta['sight_rows']
    assert len(params) == memmap.SIGHT_PARAMS_SIZE and memmap.SIGHT_PARAMS_END == memmap.SIGHT_ROOMS
    assert len(rooms) <= memmap.SIGHT_ROOMS_SIZE and memmap.SIGHT_ROOMS_END <= memmap.SIGHT_GEN
    rel = lambda p: str(p.relative_to(ROOT))
    return [dict(data=params + rooms, file=rel(folder/'sight-rooms.bin'), address=memmap.SIGHT_PARAMS),
            dict(file=rel(folder/'sight-lower.bin'), address=meta['sight_rows']),
            dict(file='build/boot/sight_gen.raw', address=memmap.SIGHT_GEN, raw=True)]


def logic_rows(floor, logic, keep):
    """The logic image as floor-disk units. LOGIC_ZERO is zero in the image: it stages the
    floor-disk run, and the loader zero-fills it after that run (leveldirectory.s RunEnds).
    The art hole is zero in the image: the generator writes the floor's art there, before or
    after these units, so zero units fill only the hole bytes that are not art (keep). From
    the hole to LEVELBLOCK the image is the same on every floor: the store keeps one copy.
    The part between LOGIC_ZERO and the hole loads after the sight unit (sight_gen.s at
    SIGHT_GEN is in it)."""
    base = memmap.LOGIC_BASE
    zero_end = memmap.LOGIC_ZERO_END - base
    hole, hole_end = memmap.LOGIC_ART_HOLE - base, memmap.LOGIC_ART_HOLE_END - base
    split = LAYOUT['LEVELBLOCK'] & ~0xff
    assert memmap.LOGIC_ZERO == base and zero_end <= hole < hole_end <= split <= len(logic) == memmap.LOGIC_BASE_SIZE
    assert not any(logic[:zero_end]), 'LOGIC_ZERO is not zero in the logic image'
    assert not any(logic[hole:hole_end]), 'the art hole is not zero in the logic image'
    assert memmap.FLOOR_PART_STAGE == base and memmap.FLOOR_PART_STAGE_END <= memmap.SIGHT_PARAMS < memmap.LOGIC_ZERO_END
    assert base + zero_end <= memmap.SIGHT_GEN < memmap.SIGHT_GEN_END <= base + hole
    rows = [dict(data=logic[zero_end:hole], address=base + zero_end),
            dict(data=logic[hole_end:split], address=base + hole_end),
            dict(data=logic[split:], address=base + split)]
    at = hole
    while at < hole_end:
        if keep[at - hole]:
            at += 1
            continue
        end = at
        while end < hole_end and not keep[end - hole]:
            end += 1
        rows.append(dict(data=bytes(end - at), address=base + at))
        at = end
    return rows


def hole_art(floor, extra=()):
    """1 for each byte of the logic image's art hole that the floor's art (or a sight unit)
    covers."""
    lo, hi = memmap.LOGIC_ART_HOLE, memmap.LOGIC_ART_HOLE_END
    keep = bytearray(hi - lo)
    for r in list(art_rows(floor)) + list(extra):
        a, b = max(r['address'], lo), min(r['address'] + r['bytes'], hi)
        if a < b:
            keep[a - lo:b - lo] = b'\1' * (b - a)
    return keep


def effects_padded(row, effects):
    """The row's bytes and its block padding filled with the bytes that the other raw
    effect rows (loaded in address order) leave there."""
    data = bytearray((ROOT/row['file']).read_bytes())
    end = row['address'] + len(data)
    pad = bytearray(-len(data) % 512)
    for other in sorted(effects, key=lambda r: r['address']):
        if other is row or other['address'] >> 16 not in (0x39, 0x3a):
            continue
        body = (ROOT/other['file']).read_bytes()
        for i in range(len(pad)):
            at = end + i - other['address']
            if 0 <= at < len(body):
                pad[i] = body[at]
    return bytes(data + pad)


def floor_rows(floor, symbols):
    """A floor load in two runs. The episode-disk run (run 0): the generator and its units
    (generation_rows), the effects last; the generator finishes before the raw effects cover
    its code, its scratch and the FLOOR_STAGE stage. The floor-disk run (run 1): the sight
    units, the logic image, the map planes, the frame table, the gray records, the weapon
    header and the song; it stages in FLOOR_PART_STAGE, so it works before or after the
    episode-disk run (src/iigs/leveldirectory.s planRuns). slot orders the rows of a run."""
    folder = ROOT/f'build/levels/{floor}'
    logic = bytearray((folder/'logic.bin').read_bytes())
    meta = json.loads((folder/'map.json').read_text())
    sites = sorted((name, address) for name, address in symbols.items()
                   if name.startswith(('flat_floor_', 'flat_ceiling_')))
    patches = bytearray(struct.pack('<H', len(sites)))
    for name, address in sites:
        assert address >> 16 == 2
        offset = int(name.split('_')[-2])
        color = meta[name.split('_')[1]] * 17
        patches.extend(struct.pack('<HB', (address+offset) & 65535, color))
    assert len(patches) <= 512
    logic[LAYOUT['FLOORCONFIG']:LAYOUT['FLOORCONFIG']+len(patches)] = patches
    fixed = (folder/'fixed.json').exists()
    episode = generation_rows(floor) if fixed else art_rows(floor)
    rows = [dict(row, run=0, slot=0, stage=STAGE_EFFECTS if row.pop('late', False) else STAGE_GENERATOR)
            for row in episode]
    # Primary effects ($39:0000-$3A:D7FF) cover the generator's code, its scratch and
    # FLOOR_STAGE, so they end the episode-disk run; packed ones (the floppy store, main)
    # stage in EFFECT_STAGE. The overflow part in bank $10 loads first (raw block padding
    # would cover art). The floor's own effects load after the shared ones; their block
    # padding holds the bytes the other effects put there (main: effects_padded), so the
    # order does not change memory. Without the generator (no fixed layout) nothing moves
    # the stage, so the effects stay raw.
    effects = read_rows(ROOT/f'build/sound/effects-floor-{floor:02}-loads.json', ROOT/'build/sound')
    for row in effects:
        if memmap.SFX_BASE <= row['address'] < memmap.SFX_BASE_END:
            rows.append(dict(row, run=0, slot=2, by_share=True, effects=effects, stage=STAGE_EFFECTS,
                             **(dict(effect_ram=True) if fixed else dict(raw=True))))
        else:
            rows.append(dict(row, run=0, slot=1, by_share=True, stage=STAGE_EFFECTS if fixed else STAGE_GENERATOR))
    sight = sight_rows(floor) if fixed else []
    part = [dict(row, slot=0) for row in sight]
    keep = hole_art(floor, [dict(address=r['address'], bytes=len(r['data']) if 'data' in r else (ROOT/r['file']).stat().st_size)
                            for r in sight if r['address'] != memmap.SIGHT_GEN])
    part += [dict(row, slot=1) for row in logic_rows(floor, logic, keep)]
    part += [dict(file=str((folder/'source-planes.bin').relative_to(ROOT)), address=RAW_PLANES_ADDRESS, slot=2),
             dict(file=str((folder/'spriteFrame.bin').relative_to(ROOT)), address=symbols['spriteFrame'], slot=2)]
    part += [dict(row, slot=2) for row in read_rows(ROOT/f'build/assets/gray-local/floor-{floor:02}-loads.json')]
    meta_fixed = json.loads((folder/'fixed.json').read_text()) if fixed else {}
    if meta_fixed.get('weapon_header_address') is not None:
        # The weapon frames' headers follow the floor's frames; the generator writes only
        # the floor's frames, so this unit may load before or after it.
        part.append(dict(file=str((folder/'fixed-weaponhdr.bin').relative_to(ROOT)),
                         address=meta_fixed['weapon_header_address'], slot=2))
    song = PROFILE.music_names.index(PROFILE.document['audio']['floor_songs'][floor])
    part += song_rows(song, slot=3)
    rows += [dict(row, run=1, stage=STAGE_FLOOR_PART) for row in part]
    return rows


def join_effect_rows(rows):
    """Fit large floor load lists by joining contiguous overflow effects.

    These rows follow generation and have no generator commands. Packed
    loads retain the exact final byte; a joined unit fits the effect stage.
    """
    # Overflow effects occupy disjoint ranges. Keep other rows in their
    # original order, and put these ranges in address order before joining.
    rows=[r for i,r in sorted(enumerate(rows),key=lambda item:
          (item[1]['run'],item[1]['slot'],item[1]['address']
           if item[1]['run']==0 and item[1]['slot']==1 else item[0]))]
    out=[]
    for row in rows:
        previous=out[-1] if out else None
        if (previous and row['run']==previous['run']==0 and row['slot']==previous['slot']==1
                and row.get('by_share') and previous.get('by_share')
                and row['stage']==previous['stage']
                and not any(r.get(k) for r in (row,previous) for k in ('raw','encoded','shared_source'))):
            a=bytes(previous['data']) if 'data' in previous else (ROOT/previous['file']).read_bytes()
            b=bytes(row['data']) if 'data' in row else (ROOT/row['file']).read_bytes()
            end=row['address']+len(b)
            if (previous['address']+len(a)==row['address'] and len(a)+len(b)<=32768
                    and previous['address']>>16==(end-1)>>16):
                out[-1]=dict(previous,data=a+b,file='linked effects',packed=True)
                continue
        out.append(row)
    return out


def join_logic_rows(rows):
    """Keep the load-list limit without changing the floor image or load order.

    Logic normally separates its shared prefix from floor-local state for disk
    deduplication. A full list can join adjacent pieces after the art hole.
    Both pieces use the floor-part stage and follow the sight generator.
    """
    if len(rows)<=128:
        return rows
    out=[]
    for row in rows:
        previous=out[-1] if out else None
        if (previous and row['run']==previous['run']==1 and row['slot']==previous['slot']==1
                and 'data' in row and 'data' in previous and row['stage']==previous['stage']
                and previous['address']+len(previous['data'])==row['address']
                and previous['address']>>16==(row['address']+len(row['data'])-1)>>16
                and len(previous['data'])+len(row['data'])<=32768):
            out[-1]=dict(previous,data=bytes(previous['data'])+bytes(row['data']))
        else:
            out.append(row)
    return out


SONG_HALF = 0x8000


def song_rows(song, **extra):
    """A song as two halves of at most 32 KB, so each half packs into the 28 KB decode
    stage (a whole song does not). They load before the raw effects take the stage."""
    data = (ROOT/f'build/sound/song-{song:02}.bin').read_bytes()
    return [dict(data=data[at:at + SONG_HALF], file=f'build/sound/song-{song:02}.bin',
                 address=memmap.MUSIC_BASE + at, **extra) for at in range(0, len(data), SONG_HALF)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=min(16, os.cpu_count() or 1))
    parser.add_argument('--precache-only', action='store_true')
    parser.add_argument('--groups', type=Path,
                        help='Shared sprite groups produced by this build (build_registered_sprites.py --save-groups).')
    parser.add_argument('--storage',choices=('hd','floppy','b1','raw','lzsa1'),default=os.environ.get('WOLF_STORE_MEDIUM','hd'),
                        help='Select by estimated total load time (hd), or the smallest units with HLZ (floppy; '
                             'environment WOLF_STORE_MEDIUM); explicit codecs require room in the two-volume budget')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 16:
        parser.error('--jobs must be between 1 and 16')
    if args.groups:
        import fixed_art
        saved=tuple((tuple(members),bytes.fromhex(blob)) for members,blob in json.loads(args.groups.read_text()))
        fixed_art.groups=lambda:saved
    from check_palette_bindings import check
    check(ROOT, range(PROFILE.floors))
    from sight_rooms import prepare_all
    from buildconfig import config
    prepare_all(ROOT, PROFILE.floors, config()['floor']-1)
    write_fixed_units()
    groups=group_rows()
    _,symbols=read(ROOT/'build/wolf.elf')
    floors = [floor_rows(floor, symbols) for floor in range(PROFILE.floors)]
    users = {}
    for floor, rows in enumerate(floors):
        for row in rows:
            body = bytes(row['data']) if 'data' in row else (ROOT/row['file']).read_bytes()
            users.setdefault(hashlib.sha256(body).hexdigest(), set()).add(floor)
            row['content'] = hashlib.sha256(body).hexdigest()
    for rows in floors:
        for row in rows:
            row['shared'] = len(users[row.pop('content')]) > 1
            effects = row.pop('effects', None)
            if effects is not None and not row['shared']:
                row['data'] = effects_padded(row, effects)
            if row.pop('effect_ram', False):
                # The primary effects: the hard disk store keeps them raw (its policy weighs
                # load time), the floppy store packs them where that is smaller. A packed unit
                # also writes the zero block padding that the raw one writes (between the
                # clusters the padding is the memory there), so memory stays the same.
                row['raw'] = args.storage != 'floppy'
                if not row['raw']:
                    body = bytes(row['data']) if 'data' in row else (ROOT/row['file']).read_bytes()
                    row['data'] = body + bytes(-len(body) % 512)
    # The store uses only LZ16, LZSA1 and raw: the Python B1 encoder runs at about
    # 9 KB/s (100 times slower than the others) and every load decodes the fast codecs.
    if args.precache_only:
        return
    if args.storage == 'floppy':
        hlz_precache(floors+[song_rows(song) for song in PROFILE.required_music]+list(groups), args.jobs)
    limits=play_limits()
    starts=play_fill_starts(limits)
    store=Store(len(groups)+len(starts),args.storage)    # the last groups: the play cache's fill groups
    floor_records=[];offsets=[];counts=[];music={}
    for floor, units in enumerate(floors):
        song=PROFILE.music_names.index(PROFILE.document['audio']['floor_songs'][floor])
        records=store.units(units,f'floor/{floor}')
        assert len(records)<=128,(floor,len(records))
        music[song]=[r for r in records if r[1]&255==memmap.MUSIC_BASE>>16]
        offsets.append(len(floor_records)*8);counts.append(len(records));floor_records.extend(records)
        print(f'floor {floor+1}: {len(records)} loads, {len(store.cache)} unique units',flush=True)
    for song in PROFILE.required_music:
        if song not in music:
            music[song]=store.units(song_rows(song),f'music/{song}')
    aux=[]
    for i,rows in enumerate(groups):
        records=[]
        if args.storage=='hd' and AUX_GAME_BASE<=i<AUX_GAME_BASE+PROFILE.floors:
            records=store.units(title_restore_rows(i-AUX_GAME_BASE),f'aux/{i}')
            store.title_prefix[i]=len(records)
        records+=store.units(rows,f'aux/{i}')
        assert 0<len(records)<128,(i,len(records))
        aux.append(records)
    # Their records read the play blocks into the play cache; they are known after packing.
    fills={}
    for first in starts:
        fills[first]=len(aux)
        aux.append([[0,0,0,0] for _ in range(PLAY_FILL_RECORDS)])
    floor_lists=[floor_records[offset//8:offset//8+count] for offset,count in zip(offsets,counts)]
    store.plan_lists(floor_lists,aux)
    store.finish_packing()
    play_table,play_floors=play_cache(store,aux,fills,limits)
    floor_index,aux_index=store.write_lists(floor_lists,aux)
    directory.finish_compact(store.data,floor_index,aux_index,len(floor_records))
    if args.storage=='hd':
        assert 12+PROFILE.floors*6 <= memmap.STORE_TITLE_RESTORE_OFFSET < directory.AUX_AT-1
        struct.pack_into('<H',store.data,memmap.STORE_TITLE_RESTORE_OFFSET,1)
    assert not any(store.data[512:1024]),'the play table needs root block 1'
    store.data[512:512+len(play_table)]=play_table
    # The high byte of a floor's third root word: the records of its episode-disk run
    # (src/iigs/leveldirectory.s planRuns). With the floor-disk run first, the loader turns
    # the list around through the 512-byte BOOT_BUF: at most 64 records of floor-disk run.
    for floor in range(PROFILE.floors):
        split=store.splits[f'floor/{floor}'];rest=counts[floor]-split
        assert 0<split<256 and 0<rest<=64,(floor,split,rest)
        block,count,steps=struct.unpack_from('<3H',store.data,12+floor*6)
        assert count==counts[floor] and steps==0,(floor,count,steps)
        struct.pack_into('<H',store.data,12+floor*6+4,split<<8)
    # WOLFMS03: each song has two records (its halves; a zero record when it has one).
    store.data[1024:1032]=b'WOLFMS03'
    assert 1024+64+16*(max(music)+1)<=1536,'music directory outside its root block'
    for song,records in music.items():
        assert 1<=len(records)<=2 and records[0][0]==0,(song,records)
        for i,record in enumerate(records):struct.pack_into('<4H',store.data,1024+64+song*16+8*i,*record)
    assets=ROOT/'build/assets'
    (assets/'episode.bin').write_bytes(store.data)
    # The root: the boot loads it into RAM (src/iigs/leveldirectory.s rootLookup).
    (assets/'episode-root.bin').write_bytes(store.data[:directory.ROOT_BLOCKS*512])
    (assets/'root-loads.txt').write_text('build/assets/episode-root.bin@0x%06x\n' % memmap.STORE_ROOT)
    (assets/'episode.json').write_text(json.dumps(store.manifest,indent=2)+'\n')
    disk_units(store,len(aux),assets,play_floors)
    (assets/'episode-storage.json').write_text(json.dumps(dict(format=1,policy=args.storage,estimates=store.settings[1],store_bytes=len(store.data),unique_units=len(store.cache),load_budgets=getattr(store,'load_budgets',{})),indent=2)+'\n')
    include()
    print('registered store:',len(store.data),'bytes;',len(groups),'cold groups')

if __name__=='__main__':main()
