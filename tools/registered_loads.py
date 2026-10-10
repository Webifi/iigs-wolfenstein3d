"""Exact live spans and paused-interface overlays for the selected campaign."""
import memmap
import json
from pathlib import Path
from shared_cache import atomic
from wolfdata import ROOT, PROFILE
from buildconfig import config
from registered_art import ENDPOINT_ORIGINALS

ASSETS=ROOT/'build/assets'
AUX_WEIGHTS_BASE=0
AUX_WEAPONS_BASE=4
AUX_UI=AUX_WEAPONS_BASE+PROFILE.floors*4
AUX_GAME_BASE=AUX_UI+1
AUX_DEMOS_BASE=AUX_GAME_BASE+PROFILE.floors
AUX_TALLY=AUX_DEMOS_BASE+4
AUX_PAUSE_BASE=AUX_TALLY+1
RAW_BOOT=memmap.RAW_BOOT


def read_rows(path, relative=None):
    result=[]
    for row in json.loads(Path(path).read_text()):
        p=Path(row['file'])
        if not p.is_absolute():p=(relative or ROOT)/p
        result.append(dict(row,file=str(p.relative_to(ROOT))))
    return result


def art_rows(floor):
    folder=ROOT/f'build/levels/{floor}'
    rows=read_rows(folder/'registered-art-loads.json',folder)
    # B1 input uses bank1D. Restore that whole bank raw, last. A padded raw
    # fragment must never wrap into the following bank's live texels.
    stage=[r for r in rows if r['address']>>16==0x1d]
    if stage:
        blob=bytearray(65536)
        for row in stage:
            raw=(ROOT/row['file']).read_bytes();start=row['address']&65535
            blob[start:start+len(raw)]=raw
        # Parallel checks read this same file; never expose a truncated bank.
        path=folder/'art-stage-bank.bin';atomic(path, blob)
        rows=[r for r in rows if r not in stage]
        rows.append(dict(file=str(path.relative_to(ROOT)),address=memmap.BOOT_STAGE,bytes=len(blob),raw=True))
    return rows


def ui_rows():
    cache=json.loads((ASSETS/'menu-cache.json').read_text())
    result=[dict(file='build/assets/'+r['file'],address=r['start'],bytes=r['end']-r['start'])
            for r in cache['regions'] if r['start']<memmap.SLOW_RAM and r['end']>r['start']]
    gray=json.loads((ASSETS/'gray-local.json').read_text())
    raw=(ASSETS/'graytables.bin').read_bytes()[0x800:gray['shared_bytes']]
    atomic(ASSETS/'gray-shared-body.bin', raw)
    result.append(dict(file='build/assets/gray-shared-body.bin',address=memmap.GRAY_RECS,bytes=len(raw)))
    if gray.get('preview_bytes'):
        result.append(dict(file='build/assets/gray-preview-records.bin',
                           address=gray['preview_address'],bytes=gray['preview_bytes']))
    return result


def restore_ranges():
    """Art that a resumed game must read again. The in-game pause composes its gray page in
    the $3C frame and reads its page records raw into the bank-0 window (src/iigs/ui_overlays.s
    PauseLump); it keeps no colour snapshot and loads no UI group. Every view, weapon and
    compressed read stages in bank $1D (ui_overlays.s EnsureViewAssets, load_fast.inc). A title
    menu also overwrites art with ui_rows and the colour snapshot. Hard disk stores
    have a separate title-only prefix for those bytes (title_restore_rows)."""
    return [(memmap.MENU_FRAME,memmap.FADE_BUFFER),(memmap.BOOT_STAGE,memmap.BOOT_STAGE_END)]


def restored_art(floor):
    ranges=restore_ranges()
    return [row for row in art_rows(floor)
            if any(row['address']<b and a<row['address']+row['bytes'] for a,b in ranges)]


def restore_slices(floor):
    """Only the art bytes inside the paused interface's ranges, one file per slice."""
    folder = ROOT/f'build/levels/{floor}'
    for old in folder.glob('restore-*.bin'):
        old.unlink()
    rows, done = [], set()
    for row in restored_art(floor):
        data = (ROOT/row['file']).read_bytes(); a = row['address']
        for lo, hi in restore_ranges():
            s, e = max(a, lo), min(a + len(data), hi)
            if s < e and (s, e) not in done:
                done.add((s, e))
                path = folder/f'restore-{s:06x}.bin'
                path.write_bytes(data[s - a:e - a])
                rows.append(dict(file=str(path.relative_to(ROOT)), address=s, bytes=e - s))
    return rows


def title_restore_rows(floor):
    """Art covered by the title payloads, colour snapshot and menu frame.

    The ordinary game group restores the decode stage last. These extra rows
    are a prefix used only when restarting a floor retained through the title.
    """
    ranges=[(r['address'],r['address']+((r['bytes']+511)//512)*512) for r in ui_rows()]
    ranges += [(memmap.SNAP_PIX,memmap.SNAP_PIX_END),(memmap.MENU_FRAME,memmap.FADE_BUFFER_END)]
    ranges=sorted((a,b) for a,b in ranges if a<b)
    merged=[]
    for a,b in ranges:
        if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    folder=ROOT/f'build/levels/{floor}'
    result=[]
    for row in art_rows(floor):
        raw=(ROOT/row['file']).read_bytes();base=row['address']
        for lo,hi in merged:
            start,end=max(base,lo),min(base+len(raw),hi)
            if start>=end:continue
            path=folder/f'title-restore-{start:06x}.bin'
            path.write_bytes(raw[start-base:end-base])
            result.append(dict(file=str(path.relative_to(ROOT)),address=start,bytes=end-start,
                               packed=True,title_only=True))
    return result


def tally_rows():
    """The tally lump of the menu file, raw for the page stage (src/iigs/tally_art.s
    TallyStage, which copied it out of the menu caches before; tools/tally_model.py lump):
    a group of its own that plays with the play cache, so the tally after a floor does not
    read the UI group, which only disk 1 holds."""
    from tally_model import lump
    data,_=lump()
    path=ASSETS/'tally-lump.bin'
    path.write_bytes(data)
    return [dict(file=str(path.relative_to(ROOT)),address=memmap.PAGE_STAGE_BANK<<16|memmap.PAGE_STAGE)]


def group_rows():
    weights=json.loads((ASSETS/'view-weight-loads.json').read_text())
    groups=list(weights)
    for floor in range(PROFILE.floors):
        groups.extend(json.loads((ROOT/f'build/levels/{floor}/view-weapon-units.json').read_text()))
    assert len(groups)==AUX_UI
    groups.append(ui_rows())
    for f in range(PROFILE.floors):
        # A loaded group needs at least one record. The floor's weapon table: every view's
        # weapon group loads it into bank $1D, which holds no art of this floor, so loading
        # it again changes nothing, and its block is on the floor's disks already.
        table = [dict(r) for r in groups[AUX_WEAPONS_BASE+f*4] if r['file'].endswith('/weapon-table.bin')]
        assert len(table)==1,(f,table)
        group = restore_slices(f) or table
        groups.append(group)
    assert len(groups)==AUX_DEMOS_BASE
    groups += json.loads((ASSETS/'demo-loads.json').read_text())
    assert len(groups)==AUX_TALLY
    groups.append(tally_rows())
    assert len(groups)==AUX_PAUSE_BASE
    # In-game pause page records, raw into the bank-0 window (tools/build_menu_cache.py).
    groups += json.loads((ASSETS/'pause-groups.json').read_text())
    return groups


def frame_art_floors():
    """1 for each floor with art in the in-game pause's $3C frame (its resume reads AUX_GAME)."""
    flags=[]
    for floor in range(PROFILE.floors):
        try:
            rows=read_rows(ROOT/f'build/levels/{floor}/registered-art-loads.json',ROOT/f'build/levels/{floor}')
        except FileNotFoundError:
            flags.append(1);continue
        flags.append(int(any(r['address']<memmap.FADE_BUFFER and memmap.SPR_RECORDS<r['address']+len((ROOT/r['file']).read_bytes()) for r in rows)))
    return flags


def include():
    constants=dict(AUX_WEIGHTS_BASE=AUX_WEIGHTS_BASE,AUX_WEAPONS_BASE=AUX_WEAPONS_BASE,
                   AUX_UI=AUX_UI,AUX_GAME_BASE=AUX_GAME_BASE,AUX_DEMOS_BASE=AUX_DEMOS_BASE,
                   AUX_TALLY=AUX_TALLY,AUX_PAUSE_BASE=AUX_PAUSE_BASE)
    (ROOT/'build/gen/overlay_groups.inc').write_text(''.join(f'{k} .equ {v}\n' for k,v in constants.items()))
    flags=frame_art_floors()
    (ROOT/'build/gen/pause-floors.inc').write_text(
        ';;; Generated by tools/registered_loads.py: 1 when the floor has art in the $3C frame.\n'
        'pauseFrameArt:\n'+''.join('              .byte '+', '.join(map(str,flags[i:i+20]))+'\n' for i in range(0,len(flags),20)))


# The sounds of the title and the menus (src/iigs/ui_main.s, ui_options.s, ui_controls.s,
# ui_bench.s). The boot loads only these effects.
MENU_SOUNDS=('SELECTITEMSND','MOVEGUN1SND','MOVEGUN2SND','NOWAYSND','SHOOTSND','ESCPRESSEDSND')


def sound_ids():
    ids={}
    for line in (ROOT/'build/gen/sound_ids.inc').read_text().splitlines():
        part=line.split()
        if len(part)==3 and part[1]=='.equ':ids[part[0]]=int(part[2],0)
    return ids


def menu_effects(floor):
    """The effect image of the title and the menus: the floor's descriptors and plan
    record, only the menu sounds resident, their samples packed after the plan, no
    pinned effect (src/iigs/sound_cache.s CacheFloorEffects). The floor load reads the
    floor's whole image over it (lglue.s LoadFloorAssets); an effect id has the same
    samples on every floor (tools/build_sound.py effect_image)."""
    import struct
    rows=read_rows(ROOT/f'build/sound/effects-floor-{floor:02}-loads.json',ROOT/'build/sound')
    spans=[(r['address'],(ROOT/r['file']).read_bytes()) for r in rows]
    def read(address,length):
        for start,data in spans:
            if start<=address and address+length<=start+len(data):
                return data[address-start:address+length-start]
        raise ValueError(f'effect samples at ${address:06X} are not in the floor {floor+1} image')
    count=(memmap.SFX_PLAN-memmap.SFX_BASE)//16
    plan=memmap.SFX_PLAN-memmap.SFX_BASE
    image=bytearray(read(memmap.SFX_BASE,plan+memmap.SFX_PLAN_SIZE))
    image[plan+1]=0                         # the plan pins nothing
    ids=sound_ids()
    menu={ids[n] for n in MENU_SOUNDS if n in ids}
    samples=bytearray()
    for i in range(count):
        address,length=struct.unpack_from('<IH',image,16*i)
        if i in menu and address:
            struct.pack_into('<I',image,16*i,memmap.SFX_BASE+len(image)+len(samples))
            samples+=read(address,length)
        else:
            priority=struct.unpack_from('<H',image,16*i+6)[0]
            image[16*i:16*i+16]=bytes(16)    # not resident, as build_sound.py writes it
            struct.pack_into('<H',image,16*i+6,priority)
    path=ASSETS/'effects-menu.bin'
    path.write_bytes(bytes(image+samples))
    return path


def boot_built():
    """The tables the registered boot builds instead of loading (src/iigs/boot_tables.inc,
    from BuildRayPartial): (address, the file the tools write) for the memory checks
    (check_registered_assets.py) and the byte check (check_boot_tables.py). rowcode.bin
    left the data list of profiles/native/wolf3d.toml."""
    return [(memmap.ROWCODE,ASSETS/'rowcode.bin'),(memmap.RAY_LOGIC_SETUP,ASSETS/'ray-logic-setup.bin'),
            (memmap.RAY_MIDPOINT,ASSETS/'ray-midpoint.bin'),(memmap.THRUST_INDEX,ASSETS/'thrust-index.bin'),
            (memmap.THRUST_MAIN,ASSETS/'thrust-vectors.bin'),(memmap.THRUST_EXTRA,ASSETS/'thrust-extra.bin'),
            (memmap.HORIZONTAL,ASSETS/'horizontal.bin'),(memmap.RAY_FIXED,ASSETS/'ray-fixed.bin'),
            (memmap.ENDPOINTS,ASSETS/'sprite-endpoints.bin')]


SEED_ANGLES=257             # a quarter of the 1024 ray-setup angles, both ends


def boot_seeds():
    """The data the boot table builders cannot compute, loaded at BOOT_TABLE_SEEDS: the DX
    word of ray-setup angles 0..256 and the ray-partial row of each (gen_ray_tables.py: the
    rest of ray-setup.bin follows from them, src/iigs/boot_tables.inc BuildRayFixed), then
    the 16 pool endpoint bytes (+200) of each sprite endpoint page (gen_scalers.py). The
    offsets go to build/gen/boot_seeds.inc."""
    import struct
    setup=(ASSETS/'ray-setup.bin').read_bytes()
    pages=(ASSETS/'sprite-endpoints.bin').read_bytes()
    dx=[struct.unpack_from('<H',setup,16*a)[0] for a in range(SEED_ANGLES)]
    rows=[(struct.unpack_from('<H',setup,16*a+8)[0]-(memmap.RAY_PARTIAL>>8))//2 for a in range(SEED_ANGLES)]
    assert all(0<=r<256 for r in rows)
    seed=bytearray(struct.pack('<%dH'%SEED_ANGLES,*dx)+bytes(rows))
    seed+=bytes(len(seed)&1)
    pools=len(seed)
    for n in range(len(pages)//256):
        seed+=pages[256*n+200:256*n+216]
    assert len(seed)<=memmap.BOOT_TABLE_SEEDS_SIZE
    path=ASSETS/'boot-table-seeds.bin'
    path.write_bytes(bytes(seed))
    from viewgeometry import SIZES
    (ROOT/'build/gen/boot_seeds.inc').write_text(
        ';;; Generated by tools/registered_loads.py boot_seeds.\n'
        f'SEED_ANGLES .equ {SEED_ANGLES}\nSEED_ROWS .equ {2*SEED_ANGLES}\nSEED_POOLS .equ {pools}\n'
        'viewSizes:    .word '+', '.join(map(str,SIZES))+'\n')
    return path


def boot_rows():
    """No floor art, song or effect set: the first floor loads from the store like every
    other floor (src/iigs/lglue.s floorReady). The UI loads from the store at the title
    (ui_overlays.s EnsureUIAssets); the view weights load with the first view
    (EnsureViewAssets). word-products, ray-partial and the boot_built() tables are built at
    boot (src/iigs/wolf.s productRow, ui_overlays.s BuildRayPartial, boot_tables.inc).

    wolf.s still calls CacheFloorMusic at boot, which marks the floor song as read. No
    floor song plays on that mark: the title song (ui_title.s BootPicture) clears it
    (music_flow.s PrepareMusic), and a start without the title loads floor 1 with its
    song (wolf.s UiStartGame, lglue.s LoadFloorAssets)."""
    import memmap
    floor=config()['floor']-1
    result=[]
    names=((RAW_BOOT,'source-planes.bin'),(ENDPOINT_ORIGINALS,'registered-endpoints.bin'),
           (memmap.SHADING,'shading.bin'),(memmap.TINTS,'tints.bin'),
           (memmap.QUIT_TEXT,'quit-text.bin'),
           (memmap.RAY_PRODUCTS_DIRECTORY,'ray-products-directory.bin'),(memmap.RAY_FOCAL,'ray-focal.bin'))
    result += [(address,ASSETS/name) for address,name in names]
    # The gray catalog without its shared records: the UI group loads those
    # (ui_rows, gray-shared-body.bin).
    gray=json.loads((ASSETS/'gray-local.json').read_text())
    raw=(ASSETS/'graytables.bin').read_bytes()
    head,tail=ASSETS/'gray-boot-head.bin',ASSETS/'gray-boot-tail.bin'
    head.write_bytes(raw[:memmap.GRAY_RECS-memmap.GRAY_BASE])
    tail.write_bytes(raw[gray['shared_bytes']:])
    result += [(memmap.GRAY_BASE,head),(memmap.GRAY_BASE+gray['shared_bytes'],tail)]
    result.append((memmap.SFX_BASE,menu_effects(floor)))
    result.append((memmap.BOOT_TABLE_SEEDS,boot_seeds()))
    include()
    return result
