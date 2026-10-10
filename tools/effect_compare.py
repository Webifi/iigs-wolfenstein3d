"""Developer effect baselines from licensed DOS PCM or Sound Blaster FM."""
import array
import json
import math
from pathlib import Path
import struct
import sys
import wave

from audio_build_cache import digest, inputs, stage
from audio_compare import copy_wav
from effect_sources import source_effects

TOOLS = Path(__file__).resolve().parent


def effect_imf(raw, tail_seconds):
    """Replay SDL_AlSetFXInst/SDL_ALSoundService writes on channel zero.

    Instrument data is not mapped to MIDI. Each original contour byte is
    serviced every fifth 700 Hz interrupt, including the final key-off.
    """
    size = struct.unpack_from('<I', raw)[0]
    instrument, block, contour = raw[6:22], ((raw[22]&7)<<2)|0x20, raw[23:23+size]
    if len(contour) != size or not size:
        raise ValueError('Missing original AdLib effect contour')
    registers = [(0x20,0),(0x40,2),(0x60,4),(0x80,6),(0xe0,8),
                 (0x23,1),(0x43,3),(0x63,5),(0x83,7),(0xe3,9)]
    records = [(0xb0,0,0)]
    for values in (bytes(16), instrument):
        records.extend((reg,values[index],0) for reg,index in registers)
        # Wolf deliberately uses connection zero, ignoring the MUSE nConn.
        records.append((0xc0,0,0))
    records.append((0xbd,0,5))
    for index,value in enumerate(contour):
        delay = 5 if index+1<size else 0
        if value:
            records.extend([(0xa0,value,0),(0xb0,block,delay)])
        else:
            records.append((0xb0,0,delay))
    records.extend([(0xb0,0,round(tail_seconds*1193182/1702)),(0x00,0,0)])
    payload = b''.join(struct.pack('<BBH',*row) for row in records)
    return struct.pack('<H',len(payload))+payload


def render_reference(effect, executable, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if effect['pcm'] is not None:
        source = out/'original.u8'
        source.write_bytes(effect['pcm'])
        pcm = array.array('h', ((value-128)*256 for value in effect['pcm']))
        if sys.byteorder != 'little':
            pcm.byteswap()
        target = out/'reference.wav'
        with wave.open(str(target),'wb') as stream:
            stream.setparams((1,2,effect['source_rate'],0,'NONE','not compressed'))
            stream.writeframes(pcm.tobytes())
        receipt = dict(kind='original-dos-digitized', source_sha256=digest(source),
                       rate=effect['source_rate'], unchanged_unsigned_pcm=True)
    else:
        from sb_reference import render
        original = out/'original.adlib'
        original.write_bytes(effect['adlib'])
        for tail in (1,2,4,8,16,30):
            source = out/f'contour-{tail}.imf'
            source.write_bytes(effect_imf(effect['adlib'],tail))
            take, metadata = render(source, executable, out/f'take-{tail}', digest(source))
            with wave.open(str(take),'rb') as stream:
                stream.setpos(max(0,stream.getnframes()-round(stream.getframerate()*.1)))
                values = array.array('h',stream.readframes(stream.getnframes()))
                if sys.byteorder != 'little':
                    values.byteswap()
            dc = sum(values)/max(1,len(values))
            # The emulated card can retain a few PCM codes of DC at silence.
            # Measure the tail around that DC; never alter the recording.
            rms = math.sqrt(sum((v-dc)**2 for v in values)/max(1,len(values)))
            if rms <= max(2,metadata['peak']*.001):
                break
        else:
            raise ValueError('Original FM effect remains audible after 30 seconds: '+effect['name'])
        target = out/'reference.wav'
        copy_wav(take,target)
        receipt = dict(metadata,kind='original-adlib-effect-soundblaster-emulation',
                       original_adlib_sha256=digest(original), tail_seconds=tail,
                       tail_ac_rms_pcm=rms, tail_dc_pcm=dc, tail_verified=True)
    receipt.update(effect_id=effect['id'], name=effect['name'], wav_sha256=digest(target),
                   developer_only=True, used_for_doc_conversion=False,
                   normalization=False, added_gain_db=0)
    (out/'reference.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return target


def source_stage(root, source, effect, executable):
    # Source identity is per effect; changing one baseline does not invalidate
    # any DOC bank or other effects. No comparison WAV enters game packing.
    import hashlib
    dependencies = inputs([Path(__file__),TOOLS/'sb_reference.py',TOOLS/'sb_imf_player.com',
                           TOOLS/'sb_imf_player.s',executable],
        effect_id=effect['id'], source_rate=effect['source_rate'],
        adlib_sha256=hashlib.sha256(effect['adlib']).hexdigest(),
        pcm_sha256=hashlib.sha256(effect['pcm']).hexdigest() if effect['pcm'] is not None else None)
    target,_ = stage(root,'source-effect-%02d'%effect['id'],dependencies,
                     lambda out:render_reference(effect,executable,out))
    return target
