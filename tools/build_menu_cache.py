"""Pack compressed menu chunks into the available resident cache regions.

menu-resident.json identifies the victory/ending chunks emitted separately
as menu-pages.inc for ending.s. Those chunks must not consume these cache
regions; each packed chunk records its location for CopyMenuBlocks.
"""
import memmap
import hashlib
import json
import struct
from frontend.native_assets import title as native_title, picture as native_picture

import b1
from wolfdata import ROOT, PROFILE

OUT = ROOT/'build/assets'
CHUNK = 4096


def main():
    raw = (OUT/'menu.bin').read_bytes()
    song_id = PROFILE.music_names.index(PROFILE.document['audio']['events']['title']) if PROFILE.spear else 7
    song = (ROOT/f'build/sound/song-{song_id:02}.bin').read_bytes()
    assert song[:4] in (b'WDP2', b'WDP3')
    tail = (len(song) + 511) & ~511
    # The loader has already copied these pixels to SHR. Keep the final
    # kilobyte (SCBs/palettes) for BootRecord and BootPalettes.
    regions = [(memmap.MENU_CACHE_0, memmap.PIC_KEEP), (memmap.TITLE_SONG + tail, memmap.MENU_CACHE_1_END), (memmap.MENU_CACHE_2, (memmap.SLOW_RAM+0x9d00)), (memmap.MENU_CACHE_5_END, memmap.MENU_CACHE_3_END), (memmap.MENU_CACHE_4, memmap.ART_BASE), (memmap.MENU_CACHE_5, memmap.MENU_CACHE_5_END), (memmap.MENU_CACHE_6, memmap.UI_BOXBUF)]
    common_first, common_count, _, _ = struct.unpack_from('<4H', raw, 8)
    common_end = memmap.UI_STAGE + common_count * 512
    assert common_end <= memmap.MENU_CACHE_6
    regions.append((common_end, memmap.MENU_CACHE_6))
    episode_slot = len(regions)
    start = memmap.GRAY_BASE + len((OUT/'graytables.bin').read_bytes())
    regions.append((start,memmap.SPR_RECORDS))
    payloads = [bytearray() for _ in regions]
    layout = json.loads((OUT/'menu-resident.json').read_text())
    resident = layout['first_chunk']
    raw_ids=set()
    # The common heading is staged once at boot. Reserve its occupied range
    # before assigning the remaining menu chunks to cache regions.
    constants = {}
    for line in (ROOT/'build/gen/menu.inc').read_text().splitlines():
        if line.startswith('LUMP_'):
            name, _, number = line.split(); constants[int(number)] = name[5:].lower()
    disk_chunks = set()
    for index, name in constants.items():
        if name.startswith('end'):
            first,count,_,_=struct.unpack_from('<4H',raw,8+index*8)
            disk_chunks.update(range(first//8,(first+count+7)//8))
    chunks=[]
    for i in range(0,len(raw),CHUNK):
        data=raw[i:i+CHUNK].ljust(CHUNK,b'\0')
        chunks.append(b'' if i//CHUNK in disk_chunks else
                      data if i//CHUNK in raw_ids else b1.compress(data,str(ROOT/'build/b1cache')))
    pointers = [0] * len(chunks)
    import re
    picture_block = int(re.search(r'^PSYCHED_BLOCK \.equ (\d+)$',
                                 (ROOT/'build/gen/menu.inc').read_text(), re.M)[1])
    picture_blocks = int(re.search(r'^PSYCHED_BLOCKS \.equ (\d+)$',
                                  (ROOT/'build/gen/menu.inc').read_text(), re.M)[1])
    picture_chunks = set(range(picture_block // 8, (picture_block + picture_blocks) // 8))
    native = {}; cold = set(picture_chunks); native_pointers = [0] * len(constants)
    for index, name in sorted(constants.items()):
        first, count, stage, size = struct.unpack_from('<4H', raw, 8 + index * 8)
        data = raw[first * 512:(first + count) * 512]
        if name in ('common', 'font'):
            (OUT/f'ui-boot-{name}.bin').write_bytes(data)
        elif name.startswith('portrait'):
            native_pointers[index] = memmap.FLOOR_PREVIEWS + (PROFILE.floors+int(name[8:]))*memmap.FLOOR_PREVIEW_BYTES
        elif name in ('title', 'credits', 'pg13', 'tally', 'victory') or name.startswith('end'):
            cold.update(range(first // 8, (first + count + 7) // 8))
            if name.startswith('end'):
                disk_chunks.update(range(first // 8, (first + count + 7) // 8))
        elif name.startswith(('preview', 'portrait', 'episode')):
            native[index] = native_picture(data, scale=2 if name.startswith('episode') else 1)
        else:
            native[index] = native_title(data)
    def place(data, slots):
        if 2 not in slots:
            slots=sorted(slots, key=lambda i: regions[i][1]-regions[i][0]-len(payloads[i]))
        for slot in slots:
            start, end = regions[slot]
            if start + len(payloads[slot]) + len(data) <= end:
                address = start + len(payloads[slot]); payloads[slot].extend(data)
                return address
        raise SystemExit(f'native UI allocation exceeded by record of {len(data)} bytes; used ' + str(list(map(len, payloads))))
    fast = [i for i, (start, end) in enumerate(regions) if start < memmap.SLOW_RAM and (i != episode_slot or PROFILE.spear)]
    episode_ids = {i for i,n in constants.items() if n.startswith('episode')}
    for index in sorted(episode_ids):
        native_pointers[index] = place(native[index],[episode_slot])
    from shared_gray import INK
    from frontend.native_assets import alpha
    from frontend.build_words import compiled
    from build_frontend import prepare
    from render import Face, Screen, blank
    face=Face('BlackOpsOne-Regular.ttf', prepare())
    words=[]
    for text in ('New Game','Load Game','Save Game','Options','High Scores','End Game','Quit'):
        advance=sum(5 if c==' ' else len(face.glyphs[c][0])+face.gap for c in text.upper())
        screen=Screen(blank(320,200,0x111));face.draw(screen,text.upper(),1,1)
        rows=[[None if c==0x111 else INK[c&15] for c in row[:advance]] for row in screen.rows[:face.height+2]]
        data=struct.pack('<2H',4,65535)+(compiled(rows,0) if text in ('New Game','High Scores','Quit') else alpha(rows))
        words.append(dict(text=text,advance=advance,data=list(data),address=0))
    slow_titles={i for i,n in constants.items() if n in ('main','controltop')}
    for index in slow_titles:native_pointers[index]=place(native[index],[2])
    items=[('native',i,data) for i,data in native.items() if i not in slow_titles | episode_ids]
    items += [('word',i,bytes(word['data'])) for i,word in enumerate(words) if word['text']!='Quit']
    items.sort(key=lambda item:-len(item[2]))
    capacity=[regions[i][1]-regions[i][0] for i in fast]
    if sum(len(item[2]) for item in items)>sum(capacity):
        raise SystemExit('native UI records exceed the available region capacity')
    failed=set();chosen=[]
    def fit(at):
        if at==len(items): return True
        key=(at,tuple(sorted(capacity)))
        if key in failed: return False
        size=len(items[at][2]);seen=set()
        for i in sorted(range(len(fast)),key=lambda i:capacity[i]):
            room=capacity[i]
            if room<size or room in seen: continue
            seen.add(room);capacity[i]-=size;chosen.append(fast[i])
            if fit(at+1): return True
            chosen.pop();capacity[i]+=size
        failed.add(key)
        return False
    if not fit(0): raise SystemExit('native UI records do not fit the existing regions')
    for (kind,index,data),slot in zip(items,chosen):
        address=place(data,[slot])
        if kind=='native': native_pointers[index]=address
        else: words[index]['address']=address
    (OUT/'native-words.json').write_text(json.dumps(words)+'\n')
    write_pause_window(constants, native, words, slow_titles)
    # Reserve the slow-only picture before chunks that also fit in fast RAM.
    for index in sorted(picture_chunks):
        pointers[index] = place(chunks[index], [2])
    for index in sorted((i for i in cold if i < resident and i not in picture_chunks), key=lambda i: -len(chunks[i])):
        pointers[index] = place(chunks[index], [2] + fast)
    directory = ['              .public nativeLumps', 'nativeLumps:']
    for pointer in native_pointers:
        directory.append('              .word 0x%04x, 0x%04x' % (pointer & 65535, pointer >> 16))
    (ROOT/'build/gen/menu-native.inc').write_text('\n'.join(directory)+'\n')
    lines = ['              .public menuCacheDirectory']
    lines += ['              .extern pageChunk%d' % i for i in range(resident, len(chunks)) if i not in disk_chunks]
    lines.append('menuCacheDirectory:')
    for index, pointer in enumerate(pointers):
        if index < resident:
            lines.append('              .word 0x%04x, 0x%04x' % (pointer & 65535, (pointer >> 16) | (0x8000 if index in raw_ids else 0)))
        elif index in disk_chunks:
            lines.append('              .long 0')
        else:
            lines.append('              .long pageChunk%d' % index)
    (ROOT/'build/gen/menu-cache.inc').write_text('\n'.join(lines)+'\n')
    pages = []
    for index in range(resident, len(chunks)):
        if index in disk_chunks: continue
        pages += ['              .public pageChunk%d' % index, 'pageChunk%d:' % index]
        pages += ['              .byte ' + ', '.join(str(b) for b in chunks[index][i:i + 16]) for i in range(0, len(chunks[index]), 16)]
    (ROOT/'build/gen/menu-pages.inc').write_text('\n'.join(pages)+'\n')
    loads = [memmap.fill('build/assets/ui-boot-common.bin@@MM:UI_STAGE@'),memmap.fill('build/assets/ui-boot-font.bin@@MM:SLOT_REC@')]
    # Boot needs only these two. The title loads the remaining menu cache
    # from the UI group through EnsureUIAssets.
    (OUT/'menu-boot-loads.txt').write_text('\n'.join(loads)+'\n')
    for slot, ((start, end), data) in enumerate(zip(regions, payloads)):
        name = f'menu-cache-{slot}.bin'
        (OUT/name).write_bytes(data)
        if data and slot and start < memmap.SLOW_RAM:
            loads.append(f'build/assets/{name}@0x{start:06x}')
    (OUT/'menu-cache-loads.txt').write_text('\n'.join(loads)+'\n')
    disk = disk_parts(raw, constants)
    report = dict(raw_bytes=len(raw), packed_bytes=sum(map(len, payloads))+sum(len(chunks[i]) for i in range(resident,len(chunks)) if i not in disk_chunks), chunk_bytes=CHUNK,
                  resident_bytes=sum(len(chunks[i]) for i in range(resident,len(chunks)) if i not in disk_chunks), native_bytes=sum(map(len, native.values())), native_directory=native_pointers, cold_chunks=sorted(cold), disk_chunks=sorted(disk_chunks),
                  disk_page_bytes=len(disk_chunks)*CHUNK, disk_compression='lzsa1', disk_file_bytes=disk,
                  raw_sha256=hashlib.sha256(raw).hexdigest(), raw_chunks=sorted(raw_ids), directory=pointers,
                  regions=[dict(start=start, end=start+len(data), limit=end,
                                file=f'menu-cache-{i}.bin')
                           for i, ((start, end), data) in enumerate(zip(regions, payloads))])
    from frontend.floor_previews import load_regions
    report['regions'] += load_regions()
    (OUT/'menu-cache.json').write_text(json.dumps(report, indent=2)+'\n')
    print('menu cache:', report['raw_bytes'], '->', report['packed_bytes'], 'bytes',
          [(hex(r['start']), hex(r['end'])) for r in report['regions']])


# The in-game pause keeps no menu picture in art RAM. Each page reads its records raw (no
# bank-$1D decode stage) into a bank-0 window that holds no art and is free while the game is
# paused (ui_overlays.s PauseLump). $00:2000-$31FF holds the gray records that the pause makes
# from the palettes on the screen (ui_gray.s PlayGrayTables). A raw unit loads whole blocks,
# so every slot is sized in 512-byte blocks.
PAUSE_HEAD = 0x3200          # the page's heading
PAUSE_PIC = 0x4600           # the page's pictures: all of them, or the one on show
PAUSE_WORDS = 0x3200         # the main page's words (that page has no window heading or picture)
PAUSE_END = 0x5e00           # $00:2000-$5FFF: dead span buffer and deferred paint list
PICTURE_PAGES = ('portrait', 'episode')   # a page's pictures together: one read
PICTURE_SINGLE = ('preview',)      # one read for each picture shown


def write_pause_window(constants, native, words, resident):
    # New Game starts at the title. Its records stay in the title's UI group.
    native = {i: data for i, data in native.items()
              if constants[i] not in ('newgame', 'floors')
              and not constants[i].startswith(('portrait', 'episode', 'preview'))}
    def blocks(n):
        return (n + 511) & ~511
    groups, lumps = [], {}

    def add_group(slot, base, members):
        blob = bytearray()
        for index, data in members:
            if index is not None:
                lumps[index] = (len(groups), base + len(blob), slot)
            blob += data
        limit = PAUSE_PIC if slot == 0 else PAUSE_END
        if base + blocks(len(blob)) > limit:
            raise SystemExit(f'pause window slot {slot} needs {len(blob)} bytes at 0x{base:04x}')
        name = f'window-{len(groups):02d}.bin'
        (OUT/name).write_bytes(bytes(blob))
        groups.append([dict(file='build/assets/'+name, address=base, bytes=len(blob), raw=True)])
    placed = [(i, bytes(w['data'])) for i, w in enumerate(words) if w['address']]
    if [i for i, _ in placed] != list(range(len(placed))):
        raise SystemExit('window words must lead the word directory')
    offsets, blob = {}, bytearray()
    for i, data in placed:
        offsets[i] = PAUSE_WORDS + len(blob)
        blob += data
    add_group(2, PAUSE_WORDS, [(None, bytes(blob))])
    pictures = PICTURE_PAGES + PICTURE_SINGLE
    for index in sorted(native):
        name = constants[index]
        if index not in resident and not name.startswith(pictures):
            add_group(0, PAUSE_HEAD, [(index, native[index])])
    for prefix in PICTURE_PAGES:
        members = [(i, native[i]) for i in sorted(native) if constants[i].startswith(prefix)]
        if members:
            add_group(1, PAUSE_PIC, members)
    for index in sorted(native):
        if constants[index].startswith(PICTURE_SINGLE):
            add_group(1, PAUSE_PIC, [(index, native[index])])
    count = max(constants) + 1
    table = lambda column: [lumps[i][column] if i in lumps else 0xffff for i in range(count)]
    lines = [';;; Generated by tools/build_menu_cache.py. In-game pause: page records read raw',
             ';;; into the bank-0 window (group, address, slot 0 heading / 1 picture).',
             f'PAUSE_GROUPS .equ {len(groups)}', 'PAUSE_GROUP_WORDS .equ 0',
             f'PAUSE_WORD_ENTRIES .equ {len(placed)}',
             f'PAUSE_LUMPS .equ {count}', 'pauseLumpGroup:']
    lines += ['              .word ' + ', '.join(str(v) for v in table(0)[i:i + 16]) for i in range(0, count, 16)]
    lines += ['pauseLumpAddr:']
    lines += ['              .word ' + ', '.join(str(v) for v in table(1)[i:i + 16]) for i in range(0, count, 16)]
    lines += ['pauseLumpSlot:']
    lines += ['              .word ' + ', '.join(str(v) for v in table(2)[i:i + 16]) for i in range(0, count, 16)]
    # wordDirectory record words (tools/frontend/build_words.py): address, then length << 8 | bank.
    lines += ['pauseWordWindow:']
    lines += [f'              .word {offsets[i]}, {len(words[i]["text"].encode()) << 8}' for i, _ in placed]
    lines += ['pauseWordTitle:']
    lines += [f'              .word {words[i]["address"] & 65535}, {(len(words[i]["text"].encode()) << 8) | (words[i]["address"] >> 16)}'
              for i, _ in placed]
    (ROOT/'build/gen/pause-window.inc').write_text('\n'.join(lines) + '\n')
    (OUT/'pause-groups.json').write_text(json.dumps(groups, indent=2) + '\n')
    print('pause window:', len(groups), 'groups,', sum(g[0]['bytes'] for g in groups), 'bytes')


def disk_parts(raw, constants):
    """WOLF.MENU holds only the ending pages. PageShow and PageGray (src/iigs/victory.s) read each page as four block
    ranges: the record's palette block 64, its gray packet 65.., the pixels 0..62 and the palettes 63. Each range is one
    LZSA1 stream; ReadColdMenuBlocks (src/iigs/ui_menu_disk.inc) finds the range in coldParts and decodes it."""
    import lzsa1
    data, table = bytearray(), []
    for index, name in sorted(constants.items()):
        if not name.startswith('end'):
            continue
        first, count, _, _ = struct.unpack_from('<4H', raw, 8 + index * 8)
        assert count > 65, f'{name}: {count} blocks'
        for start, blocks in ((64, 1), (65, count - 65), (0, 63), (63, 1)):
            plain = raw[(first + start) * 512:(first + start + blocks) * 512]
            packed = lzsa1.compress(plain)
            assert lzsa1.decode(packed, len(plain)) == plain
            at = len(data)
            data += packed
            table.append((first + start, blocks, at // 512, at % 512, (len(data) + 511) // 512 - at // 512))
    data += bytes(-len(data) % 512)
    (OUT/'menu-disk.bin').write_bytes(bytes(data))
    lines = ['              .public coldParts', 'coldParts:']
    lines += ['              .word %d, %d, %d, %d, %d' % row for row in table]
    lines.append('              .word 0xffff')
    (ROOT/'build/gen/menu-parts.inc').write_text('\n'.join(lines)+'\n')
    return len(data)


if __name__ == '__main__':
    main()
