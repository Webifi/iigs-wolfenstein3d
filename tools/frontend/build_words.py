"""Resident masked word blocks, drawn with the approved candidate-A pixels."""
import json,re,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import memmap
sys.path.insert(0,str(ROOT/'tools/frontend/lettering'))
from build_frontend import prepare
from render import Face,Screen,blank

FAST=(memmap.MENU_CACHE_5,memmap.MENU_CACHE_5)
SLOW=(memmap.MENU_CACHE_2,memmap.MENU_CACHE_2)


def block(rows,phase):
    # A record is screen offset + byte count + opaque native words, or
    # offset|$8000 + preserve mask + ink. $FFFF ends the word. Odd x has
    # its own record; runtime never shifts or shades individual pixels.
    out=bytearray()
    for y,row in enumerate(rows):
        v=[None]*phase+row
        v+= [None]*(-len(v)%4)
        words=[]
        for x in range(0,len(v),4):
            mask=ink=0
            for c in v[x:x+4]:
                mask=mask*16+(15 if c is None else 0)
                ink=ink*16+(0 if c is None else c)
            # SHR bytes hold the leftmost nibble first; 65816 words are little endian.
            mask=(mask>>8)|((mask&255)<<8);ink=(ink>>8)|((ink&255)<<8)
            words.append((mask,ink))
        x=0
        while x<len(words):
            mask,ink=words[x]
            if mask==65535:x+=1;continue
            offset=y*160+x*2
            if mask:
                out+=struct.pack('<HHH',offset|0x8000,mask,ink);x+=1
            else:
                start=x
                while x<len(words) and words[x][0]==0:x+=1
                out+=struct.pack('<HH',offset,(x-start)*2)
                out+=struct.pack('<'+'H'*(x-start),*(v for m,v in words[start:x]))
    out+=b'\xff\xff'
    return out


def dense(rows,phase):
    width=(len(rows[0])+phase+3)//4
    out=bytearray(struct.pack('<HHH',0xfffe,width*2,len(rows)))
    for row in rows:
        v=[None]*phase+row
        v += [None]*(width*4-len(v))
        for x in range(0,len(v),4):
            mask=ink=0
            for c in v[x:x+4]:
                mask=(mask<<4)|(15 if c is None else 0)
                ink=(ink<<4)|(0 if c is None else c)
            out+=struct.pack('>HH',mask,ink)
    return out


def compiled(rows,phase):
    """Whole native rows: opaque stores or immediate masked stores, no pixel decoder."""
    code=[]
    for row in rows:
        v=[None]*phase+row
        v+=[None]*(-len(v)%4)
        program=bytearray();previous=None
        for x in range(0,len(v),4):
            mask=ink=0
            for c in v[x:x+4]:
                mask=(mask<<4)|(15 if c is None else 0)
                ink=(ink<<4)|(0 if c is None else c)
            mask=(mask>>8)|((mask&255)<<8);ink=(ink>>8)|((ink&255)<<8)
            if mask==65535:continue
            if mask:
                program+=bytes([0xb9])+struct.pack('<H',x//2)
                program+=bytes([0x29])+struct.pack('<H',mask)
                if ink:program+=bytes([0x09])+struct.pack('<H',ink)
                previous=None
            elif previous!=ink:
                program+=bytes([0xa9])+struct.pack('<H',ink);previous=ink
            program+=bytes([0x99])+struct.pack('<H',x//2)
        program+=bytes([0x6b]);code.append(program)
    out=bytearray(struct.pack('<HH',0xfffd,len(code)))
    offset=2*len(code)
    for program in code:
        out+=struct.pack('<H',offset);offset+=len(program)-2
    for program in code:out+=program
    return out


def build():
    from frontend.gray_curve import index_light
    out=ROOT/'build/assets'
    entries=json.loads((out/'native-words.json').read_text())
    lines=['              .public wordDirectory','wordDirectory:']
    for i,e in enumerate(entries):
        raw=e['text'].encode();tag=int.from_bytes(raw[:2],'little');a=e['address']
        low=str(a&65535) if a else '.word0 (wordPixels%d)'%i
        bank=a>>16 if a else 0x41
        lines.append(f'              .word {tag}, .word0 (wordName{i}), {low}, {(len(raw)<<8)|bank}, {e["advance"]}')
    lines+=['              .word 0']
    for i,e in enumerate(entries):
        lines += [f'wordName{i}:','              .byte '+','.join(map(str,e['text'].encode()+b'\0'))]
        if not e['address']:
            lines += [f'wordPixels{i}:']
            data=e['data']
            lines += ['              .byte '+','.join(map(str,data[j:j+32])) for j in range(0,len(data),32)]
    lines += ['              .public grayLuma','grayLuma:']
    curve=[index_light(light) for light in range(151)]
    lines += ['              .byte '+','.join(map(str,curve[j:j+32])) for j in range(0,len(curve),32)]
    (ROOT/'build/gen/ui-words.inc').write_text('\n'.join(lines)+'\n')
    stage=bytearray(32000)
    cache=json.loads((out/'menu-cache.json').read_text())
    for r in cache['regions']:
        if r['start']>=memmap.SLOW_RAM:
            data=(out/r['file']).read_bytes();offset=r['start']-memmap.MENU_CACHE_2
            assert 0<=offset and offset+len(data)<=len(stage)
            stage[offset:offset+len(data)]=data
    (out/'ui-words-0.bin').write_bytes(b'')
    (out/'ui-words-1.bin').write_bytes(stage)
    (out/'ui-word-loads.txt').write_text(memmap.fill('build/assets/ui-words-1.bin@@MM:SNAP_PIX@\n'))
    (out/'ui-words.json').write_text(json.dumps(dict(entries=entries,regions=[]),indent=2)+'\n')
    print('native main words',sum(len(e['data']) for e in entries),'bytes')

if __name__=='__main__':build()
