"""Gray catalog: shared UI plus fixed current-floor/page windows.

All tables are generated offline. Floor packets describe three load segments;
ending packets follow the 64 SHR blocks inside their existing WOLF.MENU lump.
No extra palette colors are reserved or imposed by this storage layout.
"""
import memmap
import json
import struct
from gray_pair import pair_table, preview_bytes, words_of


def build_local(g, found, pages):
    from buildconfig import config
    selected = config()['floor']-1
    root = g.ROOT
    out = root/'build/assets/gray-local'; out.mkdir(parents=True, exist_ok=True)
    # The first ten tint entries are the current floor. Everything else is shared.
    picture_names = {f'{p.name}[{i}]' for p in g.episode_preview_paths() for i in range(2)}
    picture_palettes = [(n,c) for n,c in found if n in picture_names]
    shared = [(n,c) for n,c in found if n not in {f'tint[{i}]' for i in range(10)} | picture_names]
    blob = bytearray(g.RECS)
    blob[g.OVERLAY_AT:g.OVERLAY_AT+len(g.OVERLAY_PAIRS)] = g.OVERLAY_PAIRS
    addresses, records, names = {}, {}, {}
    for name, colors in shared:
        record = pair_table(colors)+preview_bytes(colors)
        if record not in records:
            records[record] = len(blob)
            blob.extend(record)
        address = g.GRAY_BASE+records[record]
        addresses[colors] = address
        names[name] = address
    def pointers(at, labels):
        for i,n in enumerate(labels): struct.pack_into('<I',blob,at+i*4,names[n])
    pointers(g.TINT_AT+40,[f'tint[{i}]' for i in range(10,130)])
    pointers(g.BOOT_AT,[f'boot[{i}]' for i in range(16)])
    pointers(g.PIC_AT,[f'{n}[{i}]' for n in g.PAGE_NAMES[:4] for i in range(16)])
    pointers(g.STEEL_AT,['menuSteel']); pointers(g.BLACK_AT,['black'])
    pointers(g.TALLY_AT,[f'tally[{i}]' for i in range(3)])
    # Boot art may change the shared record count. Keep floor/page packets at
    # their memory-map windows so a new picture cannot relocate runtime data.
    floor_at = memmap.GRAY_FLOOR - g.GRAY_BASE
    floor_bytes = memmap.GRAY_FLOOR_SIZE
    page_at = memmap.GRAY_PAGE_DATA - g.GRAY_BASE
    page_bytes = memmap.GRAY_PAGE_DATA_SIZE
    if len(blob) > floor_at:
        raise SystemExit(f'shared gray records need {len(blob)} bytes, limit {floor_at}')
    if floor_at + floor_bytes > page_at or 10*g.REC_SIZE > floor_bytes or 16*g.REC_SIZE > page_bytes:
        raise SystemExit('gray packets exceed their memory-map windows')
    blob.extend(bytes(floor_at-len(blob))); shared_bytes=len(blob)
    page_end=page_at+page_bytes
    blob.extend(bytes(page_end-len(blob)))
    # Keep the existing current-floor and ending windows fixed. Additional
    # menu palettes share the art overlay above $3B:DC00 while paused.
    if picture_palettes:
        blob.extend(bytes(max(0,memmap.GRAY_BASE_SIZE-len(blob))))
    preview_at=len(blob)
    for name,colors in picture_palettes:
        record=pair_table(colors)+preview_bytes(colors)
        if record not in records:
            records[record]=len(blob);blob.extend(record)
        address=g.GRAY_BASE+records[record]
        addresses[colors]=address;names[name]=address
    preview_bytes_count=len(blob)-preview_at
    (root/'build/assets/gray-preview-records.bin').write_bytes(blob[preview_at:])
    assert g.EPISODE_PREV_AT+8*len(g.episode_preview_paths())<=g.RECS
    pointers(g.EPISODE_PREV_AT,[f'{p.name}[{i}]' for p in g.episode_preview_paths() for i in range(2)])
    if len(blob)>g.CATALOG_LIMIT:
        raise SystemExit(f'local gray catalog needs {len(blob)} bytes, limit {g.CATALOG_LIMIT}')
    def packet(colors, at, size):
        ptr=bytearray(); data=bytearray(size)
        for i,pal in enumerate(colors):
            g.check(pal,'local gray packet')
            ptr+=struct.pack('<I',g.GRAY_BASE+at+i*g.REC_SIZE)
            record=pair_table(pal)+preview_bytes(pal)
            data[i*g.REC_SIZE:(i+1)*g.REC_SIZE]=record
        return bytes(ptr),bytes(data)
    meta=json.loads((root/'build/gen/campaign.json').read_text())
    floors=[]
    for floor in meta['floors']:
        n=floor['index']; tints=(root/f'build/palettes/tints-{n+1}.bin').read_bytes()
        ptr,data=packet([words_of(tints[i:i+32]) for i in range(0,320,32)],floor_at,floor_bytes)
        # First block: raw tints [0,320), gray directory [320,360), padding.
        raw=tints+ptr+bytes(512-360)+data
        name=f'floor-{n:02d}.bin'; (out/name).write_bytes(raw)
        segments = [
            (f'floor-{n:02d}-tints.bin', tints, memmap.TINTS),
            (f'floor-{n:02d}-index.bin', ptr, g.GRAY_BASE+g.TINT_AT),
            (f'floor-{n:02d}-records.bin', data, g.GRAY_BASE+floor_at)]
        for filename, content, address in segments: (out/filename).write_bytes(content)
        loads=[dict(file='build/assets/gray-local/'+filename,address=address,bytes=len(content))
               for filename,content,address in segments]
        (out/f'floor-{n:02d}-loads.json').write_text(json.dumps(loads,indent=2)+'\n')
        floors.append(dict(source_floor=n,loads=loads,file='gray-local/'+name,bytes=len(raw),segments=[
            dict(offset=0,bytes=320,address=memmap.TINTS),
            dict(offset=320,bytes=40,address=g.GRAY_BASE+g.TINT_AT),
            dict(offset=512,bytes=floor_bytes,address=g.GRAY_BASE+floor_at)]))
        if n==selected:
            blob[g.TINT_AT:g.TINT_AT+40]=ptr
            blob[floor_at:floor_at+floor_bytes]=data
    for n in range(meta['ending_pages']):
        name=f'end{n+1}'
        art=g.picture((pages/f'{name}.bin').read_bytes())
        colors=[words_of(art[32256+i*32:32256+(i+1)*32]) for i in range(16)]
        ptr,data=packet(colors,page_at,page_bytes)
        (out/f'{name}.bin').write_bytes(ptr+bytes(512-len(ptr))+data)
    (root/'build/assets/graytables.bin').write_bytes(blob)
    gen=root/'build/gen'; g._write_inc(gen/'gray.inc'); g._write_unroll(gen/'gray-unroll.inc')
    with (gen/'gray.inc').open('a') as f:
        f.write(f'GRAY_PAGE_DATA .equ 0x{g.GRAY_BASE+page_at:06x}\nGRAY_PAGE_BLOCKS .equ {page_bytes//512}\n')
    report=dict(schema=1,base=g.GRAY_BASE,resident_bytes=len(blob),limit=g.CATALOG_LIMIT,
                gameplay_end=g.GRAY_BASE+floor_at+floor_bytes, page_end=g.GRAY_BASE+page_end,
                shared_bytes=shared_bytes,floor_address=g.GRAY_BASE+floor_at,floor_bytes=floor_bytes,
                preview_address=g.GRAY_BASE+preview_at,preview_bytes=preview_bytes_count,
                page_address=g.GRAY_BASE+page_at,page_bytes=page_bytes,floors=floors,
                ending_packet_bytes=512+page_bytes,native_verified=False)
    (root/'build/assets/gray-local.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'local gray catalog: {shared_bytes} shared + {floor_bytes} floor + {page_bytes} page = {len(blob)} bytes')
    return addresses
