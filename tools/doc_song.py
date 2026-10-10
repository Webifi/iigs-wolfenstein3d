"""Source-independent DOC events and sampled-wave bank (standard library only).

A MIDI producer supplies absolute 700 Hz event times and DOC register writes.
Samples may contain real attacks, one-shots or loops of any DOC table size;
paired oscillators and output-channel bits are ordinary event data.
"""
import math
import struct
from wolfaudio import DOC_RATE

MUSIC_START=0x200
MUSIC_FIRST_VOICE=4
MUSIC_VOICES=24
ALARM_SERVICE_SECONDS=0.000105


def encode_song(blocks,doc,ticks,doc_base=0x4000):
    if not blocks or blocks[0][0]!=0 or blocks[-1][0]!=ticks:
        raise ValueError('song needs a first block at zero and a final loop block')
    if any(a[0]>=b[0] for a,b in zip(blocks,blocks[1:])):
        raise ValueError('song times must increase')
    if doc_base%256 or doc_base<0x4000 or doc_base+len(doc)>0xf400:
        raise ValueError('song wave image overlaps effect slots or game clock')
    for _,commands in blocks:
        for reg,value in commands:
            if not 4<=reg&31<=27 or reg&0xe0 not in (0,0x20,0x40,0x80,0xa0,0xc0):
                raise ValueError('event writes outside music voices')
            if not 0<=value<=255:
                raise ValueError('DOC value or canonical volume out of range')
            if reg&0xe0==0xa0 and value&8:
                raise ValueError('only the shared music alarm may request an IRQ')
    stream=bytearray();nominal=0.;max_error=0.;writes=0;previous_alarm=0
    checkpoints=bytearray();volumes=bytearray(24);canonical=bytearray()
    for index,(t,commands) in enumerate(blocks):
        if index%32==0:checkpoints+=struct.pack('<H',MUSIC_START+len(stream))+volumes
        for reg,value in commands:
            if 0x44<=reg<=0x5b:
                volumes[reg-0x44]=value;canonical.append(value)
        delay=(blocks[index+1][0]-t) if index+1<len(blocks) else 0
        if len(commands)>255:raise ValueError('event block too large')
        if delay:
            target=(t+delay)/700
            service=ALARM_SERVICE_SECONDS if index else 0
            remaining=max(1/DOC_RATE,target-nominal-service)
            phase=max(1,131072-previous_alarm*DOC_RATE*service)
            alarm=max(1,min(65535,round(phase/(DOC_RATE*remaining))))
            nominal+=math.ceil(phase/alarm)/DOC_RATE+service
            previous_alarm=alarm
            max_error=max(max_error,abs(nominal-target))
        else:alarm=0
        stream+=struct.pack('<HB',alarm,len(commands))
        stream+=bytes(v for pair in commands for v in pair);writes+=len(commands)
    image=bytearray(MUSIC_START)
    if len(stream)+len(doc)+len(image)+len(checkpoints)+len(canonical)>65536:
        raise ValueError(f'music bank overflow: stream {len(stream)}, waves {len(doc)}, blocks {len(blocks)}, writes {writes}')
    image[:16]=struct.pack('<4sHHHHI',b'WDC2',len(stream),len(doc),MUSIC_START+len(stream),len(blocks),ticks)
    struct.pack_into('<HH',image,16,MUSIC_START+len(stream)+len(doc),len(checkpoints)//26)
    struct.pack_into('<HH',image,20,MUSIC_START+len(stream)+len(doc)+len(checkpoints),len(canonical))
    struct.pack_into('<HBBH',image,24,doc_base,4,24,1)
    image+=stream+doc+checkpoints+canonical
    if len(image)>65536:raise ValueError('music bank overflow')
    return bytes(image),dict(bytes=len(image),checkpoint_bytes=len(checkpoints),
        canonical_bytes=len(canonical),stream_bytes=len(stream),doc_bytes=len(doc),
        blocks=len(blocks),wakes_per_second=len(blocks)*700/ticks,
        register_writes=writes,writes_per_second=writes*700/ticks,
        alarm_service_us=ALARM_SERVICE_SECONDS*1e6,nominal_alarm_error_ms=max_error*1000)
