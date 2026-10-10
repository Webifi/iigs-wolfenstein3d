"""WDM2 command encoding for 24 DOC music oscillators.

Build-time only. Preserve event order and note-off times while scheduling
DOC wakes and oscillator register updates.
"""
import math
import struct

RATE = 894886 / 34
TIC = RATE / 140
# A one-shot pass over the 256-byte table at resolution 0 lasts 2^17 / fc scans: the
# DOC takes all 256 bytes in the loop.
ALARM_CYCLE = 131072
# Estimated scan overhead between alarm completion and re-arm. This is an
# encoder timing adjustment, not a physical-hardware timing guarantee.
REARM = 1.64
VOICES = 24
STREAM = 0x600
LEVEL, CTLH, CTLR, VDESC, VCTL = 0x500, 0x520, 0x540, 0x560, 0x580
WLO, WHI, VSCALE = 0x440, 0x450, 0x480


def volume(k):
    if k >= 128:
        return 0
    return ((round(255 * 256 * 2 ** (-(k & 7) / 8)) >> (k >> 3)) + 128) >> 8


def alarm(n):
    """Frequency word whose pass (ceil of the cycle, half a scan on average) plus the re-arm is n tics."""
    return round(ALARM_CYCLE / (TIC * n - REARM - 0.5))


def command(kind, v, *args):
    assert 0 <= v < VOICES
    return bytes(([0xd0] if v >= 16 else []) + [(kind << 4) | (v & 15), *args])


def encode(wakes, length, pass_tail=REARM):
    """Events use descriptor/pitch/level tuples; source ticks remain in metadata.

    pass_tail is the measured rearm overhead of the shipped player in the kit
    (REARM), not a physical timing assertion. Drift correction
    retains source event ordering and note lengths.
    """
    pitches = []
    def pitch(fc):
        if fc not in pitches:
            pitches.append(fc)
        if len(pitches) > 256:
            raise ValueError('more than 256 pitch words')
        return pitches.index(fc)
    state = [None] * VOICES
    halted = [-1] * VOICES
    out = bytearray()
    prev_alarm = None
    drift = 0.
    times = sorted(wakes)
    assert times and times[0] == 0 and times[-1] < length
    timeline = []
    for i, t in enumerate(times):
        gap = (times[i + 1] if i + 1 < len(times) else length) - t
        n = gap
        if drift > TIC / 2 and n > 1:
            n -= 1
        elif drift < -TIC / 2:
            n += 1
        drift -= gap * TIC
        waits = []
        while n:
            k = min(n, 15)
            fc = alarm(k)
            code = 0xd0 if fc == prev_alarm else 0xf0 if prev_alarm is not None and fc >> 8 == prev_alarm >> 8 else 0xe0
            waits.append(code | k)
            prev_alarm = fc
            drift += math.ceil(ALARM_CYCLE / fc) + pass_tail
            n -= k
        timeline.append((t, len(out)))
        out.append(waits[0])
        for kind, v, val in wakes[t]:
            s = state[v]
            if kind in ('on', 'table'):
                d, fc, lev = val
                assert 0 <= lev < 128 and 0 <= d < 64
                # A table morph preserves phase; otherwise only a prior wake's
                # explicit halt permits omission of the note's reset write.
                a = lev | (128 if kind == 'table' or halted[v] is not None and halted[v] < t else 0)
                if not a & 128:
                    # Silence the DAC before the note command resets phase.
                    out += command(1, v, 127)
                p = pitch(fc)
                if s is None or s[0] != d:
                    out += command(3, v, d, p, a)
                elif s[3] and s[1] == fc:
                    out += command(12, v, a)
                elif s[3]:
                    out += command(7, v, p, a)
                elif s[1] == fc:
                    out += command(10, v, a)
                else:
                    out += command(2, v, p, a)
                state[v] = [d, fc, lev, kind == 'table']
                halted[v] = None
            elif kind == 'off':
                if halted[v] is None:
                    out += command(1, v, 127)
                    out += command(6, v)
                    if s is not None:
                        s[2] = 127
                    halted[v] = t
            elif kind == 'sw':
                out += command(11, v) if v % 16 < 14 else bytes([0xbf, 0x80 | v])
                s[3] = True
            elif kind == 'page':
                out += bytes([0xbe, v, val])
                s[3] = True
            elif kind == 'ctl':
                if val & 1:
                    out += command(1, v, 127)
                    if s is not None:
                        s[2] = 127
                out += bytes([0xbf, v, val])
            elif kind == 'lev':
                assert 0 <= val < 128
                if val != s[2]:
                    step = {4: 0, 8: 8, -4: 9}.get(val - s[2])
                    out += command(step, v) if step is not None else command(1, v, val)
                    s[2] = val
            elif kind == 'fc':
                if val != s[1]:
                    out += command(5 if val >> 8 == s[1] >> 8 else 4, v, pitch(val))
                    s[1] = val
            else:
                raise ValueError(kind)
        out += bytes(waits[1:])
    out.append(0xe0)
    # Exactly at the loop boundary, silence lingering prior-pass voices before
    # the first notes. The initial on commands always reload descriptor/pitch.
    halts = b''.join(command(1, v, 127) + command(6, v)
                     for v in range(VOICES) if halted[v] is None)
    out = out[:1] + halts + out[1:]
    timeline = [(t, off + (len(halts) if off else 0)) for t, off in timeline]
    return bytes(out), pitches, timeline


def size_code(n):
    assert 256 <= n <= 32768 and n & (n - 1) == 0
    s = n.bit_length() - 9
    return s * 9


class HotBankOverflow(ValueError):
    def __init__(self, required_bytes):
        self.required_bytes = required_bytes
        super().__init__(f'hot head needs at least {required_bytes} bytes; the native bank holds 65535')


def image_header(pitches, descriptors, waves, low, length, channels=None, lift=0):
    assert 0 < len(descriptors) <= 64 and 0 < len(pitches) <= 256
    assert len(waves) % 256 == 0 and 64 <= low and low + len(waves) // 256 <= 244
    data = bytearray(STREAM)
    struct.pack_into('<4sHHHHBBBBI', data, 0, b'WDM2', STREAM, 0, 0,
                     len(waves), low, VOICES, len(descriptors), len(pitches) & 255, length)
    data[20] = lift
    channels = channels or [v & 1 for v in range(VOICES)]
    for v in range(VOICES):
        o = v + 4
        data[LEVEL + o] = 127
        data[CTLH + o] = 3 | (channels[v] << 4)
        data[CTLR + o] = channels[v] << 4
    for n in range(1, 16):
        data[WLO + n] = alarm(n) & 255
        data[WHI + n] = alarm(n) >> 8
    for i, fc in enumerate(pitches):
        data[0x100 + i] = fc & 255
        data[0x200 + i] = fc >> 8
    for i, (p, size, mode, lp, ls) in enumerate(descriptors):
        for base, val in zip((0x300, 0x340, 0x380, 0x3c0, 0x400), (p, size_code(size), mode, lp, size_code(ls))):
            data[base + i] = val
    return bytes(data)


def image(stream, pitches, descriptors, waves, low, length, channels=None, lift=0):
    data = bytearray(image_header(pitches, descriptors, waves, low, length, channels, lift))
    wave_offset = STREAM + len(stream)
    if wave_offset > 65535:
        raise HotBankOverflow(wave_offset)
    struct.pack_into('<HH', data, 6, len(stream), wave_offset)
    return bytes(data + stream + waves)


def storage(data):
    """Raw waves upload first; the compact hot head then expands in the same bank.

    Only cold LZ decoding, with a byte-by-byte unread-source overlap proof.
    No DOC RAM reads or runtime decompression during playback.
    """
    import sys
    from pack import compress, expand
    waveoff, wavelen = struct.unpack_from('<HH', data, 8)
    waves = data[waveoff:waveoff+wavelen]
    hot = data[:waveoff]
    packed = compress(hot)
    start = max(32 + len(waves), len(hot) + 1)
    if start + len(packed) > 65536:
        return storage_blocks(data)
    restored, margin = expand(packed, start, len(hot))
    assert restored == hot
    header = bytearray(32)
    struct.pack_into('<4sHHHHHH', header, 0, b'WDP2', data[12]*256, wavelen,
                     32, start, len(packed), len(hot))
    return bytes(header+waves+bytes(start-32-len(waves))+packed), margin


class ColdBankOverflow(ValueError):
    def __init__(self, required_bytes):
        self.required_bytes=required_bytes
        super().__init__(f'DOC bank needs {required_bytes} bytes in the 64 KiB byte-LZ container')


def _storage_blocks_raw(data):
    """Cold WDP3: byte-LZ blocks expand in a reusable 1 or 2 KiB RAM window.

    The window is uploaded before reuse. Hot commands expand only after all
    wave blocks; no DOC reads and no decompression in the music interrupt.
    """
    from pack import compress
    waveoff, wavelen = struct.unpack_from('<HH', data, 8)
    waves, hot = data[waveoff:waveoff+wavelen], data[:waveoff]
    delta = bytes((v-(waves[i-1] if i else 0)) & 255 for i,v in enumerate(waves))
    # Try the supported byte-aligned formats, including their expansion
    # overlap proof. A size failure returns to the sample auto-fit search.
    smallest=None
    for block in (2048,1024):
        pw=b''.join(compress(delta[i:i+block]) for i in range(0,len(delta),block))
        ph=compress(hot)
        start=block
        required=start+len(pw)+len(ph)
        smallest=required if smallest is None else min(smallest,required)
        if start+len(pw)+len(ph)>65536:continue
        memory=bytearray(65536);memory[start:start+len(pw)+len(ph)]=pw+ph
        source=start;restored=bytearray();margin=65536
        for offset in range(0,wavelen,block):
            dest=0;end=min(block,wavelen-offset)
            while dest<end:
                token=memory[source];source+=1
                if token<128:
                    for _ in range(token+1):
                        assert dest<source
                        memory[dest]=memory[source];source+=1;dest+=1; margin=min(margin,source-dest)
                else:
                    distance=struct.unpack_from('<H',memory,source)[0];source+=2
                    assert 0<distance<=dest
                    for _ in range((token&127)+3):
                        assert dest<source
                        memory[dest]=memory[dest-distance];dest+=1;margin=min(margin,source-dest)
                assert dest<=end
            restored.extend(memory[:end])
        assert restored==delta and source==start+len(pw)
        assert memory[source:source+len(ph)]==ph
        from pack import expand
        rebuilt,hotgap=expand(ph,65536-len(ph),len(hot))
        assert rebuilt==hot
        header=bytearray(32)
        struct.pack_into('<4s10H',header,0,b'WDP3',data[12]*256,wavelen,start,len(pw),
                         len(ph),len(hot),0,block,start+len(pw),2)
        return bytes(header+bytes(start-32)+pw+ph),min(margin,hotgap)
    raise ColdBankOverflow(smallest)


def storage_blocks(data):
    """Try the fast byte loader, then lossless Huffman storage before refitting."""
    try:
        return _storage_blocks_raw(data)
    except ColdBankOverflow as error:
        smallest = error.required_bytes
    from cold_huffman import container
    from pack import compress
    waveoff, wavelen = struct.unpack_from('<HH', data, 8)
    choices = []
    for block in (2048, 1024):
        result, required = container(data[:waveoff], data[waveoff:waveoff+wavelen],
                                     data[12]*256, compress, block)
        smallest = min(smallest, required)
        if result is not None:
            choices.append(result)
    if choices:
        return min(choices, key=lambda result: len(result[0]))
    raise ColdBankOverflow(smallest)


def wait_byte(data, cursor):
    if data[31]&16:
        address=struct.unpack_from('<H',data,STREAM+cursor)[0]
        return data[address-1]
    return data[STREAM+cursor]


class Player:
    """Independent execution oracle for the actual assembly register trace."""
    def __init__(self, data, master=15, symbolic=False, prepared=False):
        self.u = bytearray(data)
        self.prepared = prepared
        if prepared:
            assert data[21] & 4 and not symbolic
            from inline_volume import prepare
            self.u = prepare(data, master)
        assert self.u[:4] == b'WDM2'
        shift = round(8 * math.log2(15 / master)) if master else 128
        # Header byte 20: the song's level lift in 1/8-octave steps (src/iigs/music.s
        # ScaleMusicVolume). An exponent under the lift writes register 255.
        lift = self.u[20]
        self.u[VSCALE:VSCALE + 128] = bytes(volume(max(0, k + shift - lift)) for k in range(128))
        self.u[VSCALE + 127] = 0  # Explicit silence, independent of song/master lift.
        if self.u[31]&4:
            for i in range(128):
                self.u[0x200+i]=self.u[VSCALE+self.u[0x100+i]]
                self.u[0x280+i]=self.u[VSCALE+self.u[0x180+i]]
        self.oracle_base = sum(struct.unpack_from('<HH',self.u,8)) if self.u[31]&8 else 0
        self.y = 0
        self.symbolic = symbolic
        self.direct_ops = {}
        if self.u[21] & 128 and not self.u[30]&8:
            vectors,count=struct.unpack_from('<HH',self.u,24)
            self.direct_ops={struct.unpack_from('<H',self.u,vectors+2*i)[0]:2*i for i in range(count)}
            if self.u[30]&1:self.direct_ops.update({struct.unpack_from('<H',self.u,vectors+2*i)[0]-1:2*i+1 for i in range(3,count)})
            if self.u[30]&4:
                defs=self.oracle_base+struct.unpack_from('<H',self.u,22)[0]
                for i in range(3,count):
                    at=self.oracle_base+struct.unpack_from('<H',self.u,defs+i*2)[0]
                    if self.u[at]&128:
                        address=struct.unpack_from('<H',self.u,vectors+i*2)[0]
                        self.direct_ops[address-19]=i*2
                        self.direct_ops[address-16]=i*2+1

    def wake(self):
        if self.u[30] & 32:
            from pair_templates import wake
            return wake(self)
        u, writes = self.u, []
        def get():
            b = u[STREAM + self.y]
            self.y += 1
            return b
        def level(o, lev):
            if not u[31]&4:u[LEVEL + o] = lev
            writes.append((0x40 | o, lev if self.symbolic else u[VSCALE + lev]))
        b = get()
        if u[31]&16:b=u[(b|(get()<<8))-1]
        assert b > 0xd0 and b & 15
        n = b & 15
        if b >= 0xe0:
            writes.append((29, u[WLO + n]))
            if b < 0xf0:
                writes.append((61, u[WHI + n]))
        writes.append((189, 10))
        if u[21]&16:
            defs=self.oracle_base+int.from_bytes(u[22:24],'little')
            while True:
                op=get()
                if u[21]&128 and not u[30]&8:op=self.direct_ops[op | (get()<<8)]
                elif u[21]&64 and op==255:op=get() | (get()<<8)
                ending=bool(u[21]&128 and not u[30]&8 and u[30]&1 and op&1)
                if ending:op&=~1
                assert not op&1
                if u[21]&32:
                    at=self.oracle_base+int.from_bytes(u[defs+op:defs+op+2],'little');groups=u[at];at+=1;private_ending=False;private_loop=False
                    if groups in (253,254):
                        if groups==253:self.y=0
                        return n,writes
                    if groups==255:
                        reg,count=get(),get();values=[get() for _ in range(count)]
                        entries=[(reg,values)]
                    else:
                        private_ending=bool(u[30]&24 and groups&128);private_loop=bool(private_ending and groups&64)
                        groups&=63 if u[30]&24 else 127
                        entries=[]
                        for _ in range(groups):
                            reg,count,fixed=u[at:at+3];at+=3
                            if fixed in (3,4):
                                assert u[31]&4 and reg&224==64
                                values=[];index=None
                                for k in range(count):
                                    if k==0 or (reg+k)&1==0:
                                        if fixed==4:index=u[at];at+=1
                                        else:index=get()
                                        assert index<128
                                        atlevel=LEVEL+((reg+k)&30)
                                        u[atlevel:atlevel+2]=bytes((index,0))
                                    values.append(u[(0x180 if (reg+k)&1 else 0x100)+index])
                            elif fixed==5:
                                assert u[31]&32 and u[31]&4 and reg&224==64 and count<=2
                                left,right=get(),get();assert left<128 and right<128
                                pair=reg&30;u[LEVEL+pair:LEVEL+pair+2]=bytes((left|128,right))
                                values=[(left,right)[(reg+k)&1] for k in range(count)]
                            elif fixed==6:
                                assert u[30]&8 and reg==255 and count==0
                                reg,count=get(),get();assert reg&224!=64
                                values=[get() for _ in range(count)]
                            elif fixed==2:
                                assert reg&224==64
                                values=[get()]*count
                            elif fixed==1:
                                values=u[at:at+count];at+=count
                            else:
                                assert fixed==0
                                values=[get() for _ in range(count)]
                            entries.append((reg,values))
                    for reg,values in entries:
                        for val in values:
                            if reg&224==64:level(reg&31,val)
                            else:writes.append((reg,val))
                            reg+=1
                    if u[30]&24 and private_ending:
                        if private_loop:self.y=0
                        return n,writes
                    if ending:return n,writes
                    continue
                reg,count,a,b=u[defs+op*2:defs+op*2+4]
                if count>=253 and count!=255:
                    if count==253:self.y=0
                    return n,writes
                if count==255:reg,count=get(),get();values=[get() for _ in range(count)]
                elif count==2:values=[get(),get()]
                else:assert count==0;values=[a,b]
                for val in values:
                    if reg&224==64:level(reg&31,val)
                    else:writes.append((reg,val))
                    reg+=1
        if u[21]&1:
            sentinel=bool(u[21]&8)
            left=None if sentinel else get()
            while left is None or left:
                if left is not None:left-=1
                index=get()
                if sentinel:
                    if index in (129,130):
                        if index==130:self.y=0
                        return n,writes
                    if index<128:reg,count=index*2,2
                    else:
                        assert index==128
                        index=get()
                        reg,count=(get(),get()) if index==255 else (u[0x100+index],u[0x200+index])
                elif u[21]&2 and index<224:reg,count=index,2
                else:
                    if u[21]&2:
                        assert index==224
                        index=get()
                    reg,count=(get(),get()) if index==255 else (u[0x100+index],u[0x200+index])
                assert count and 4<=reg&31<28 and (reg&31)+count<=28
                for i in range(count):
                    val=get()
                    if reg&224==64 and not self.prepared:level(reg&31,val)
                    else:writes.append((reg,val))
                    reg+=1
            if u[STREAM+self.y]==0xe0:self.y=0
            return n,writes
        while True:
            c = u[STREAM + self.y]
            if c > 0xd0:
                if c == 0xe0:
                    self.y = 0
                return n, writes
            c = get()
            high = 16 if c == 0xd0 else 0
            if high:
                c = get()
            kind, o = c >> 4, (c & 15) + high + 4
            if kind in (0, 8, 9, 1):
                lev = get() if kind == 1 else u[LEVEL + o] + {0: 4, 8: 8, 9: -4}[kind]
                level(o, lev)
            elif kind == 6:
                writes.append((0xa0 | o, u[CTLH + o]))
            elif kind in (2, 3, 7, 10, 12):
                if kind == 3:
                    u[VDESC + o] = get()
                p = get() if kind in (2, 3, 7) else None
                a = get()
                if not a & 128:
                    writes.append((0xa0 | o, u[CTLH + o]))
                if kind in (3, 7, 12):
                    d = u[VDESC + o]
                    writes += [(0x80 | o, u[0x300 + d]), (0xc0 | o, u[0x340 + d])]
                    u[VCTL + o] = u[0x380 + d] | u[CTLR + o]
                if p is not None:
                    writes += [(o, u[0x100 + p]), (0x20 | o, u[0x200 + p])]
                if a & 127 != u[LEVEL + o]:
                    level(o, a & 127)
                writes.append((0xa0 | o, u[VCTL + o]))
            elif kind in (4, 5):
                p = get()
                writes.append((o, u[0x100 + p]))
                if kind == 4:
                    writes.append((0x20 | o, u[0x200 + p]))
            elif kind == 11:
                if c == 0xbe:
                    o, val = get() + 4, get()
                    writes.append((0x80 | o, val))
                elif c == 0xbf:
                    v = get()
                    if v & 128:
                        o = (v & 31) + 4
                        d = u[VDESC + o]
                        writes += [(0x80 | o, u[0x3c0 + d]), (0xc0 | o, u[0x400 + d])]
                    else:
                        writes.append((0xa4 + v, get()))
                else:
                    d = u[VDESC + o]
                    writes += [(0x80 | o, u[0x3c0 + d]), (0xc0 | o, u[0x400 + d])]
            else:
                raise ValueError(hex(c))
