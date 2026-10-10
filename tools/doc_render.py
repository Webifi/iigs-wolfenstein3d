"""Render a compiled Wolf DOC bank with Python's standard library.

The supplied engine ELF runs its own StartMusic and music IRQ routines in the
routine interpreter. Only the DOC interface is modeled; no machine ROM, disk
boot, synthesizer, reference recording, or third-party Python package is used.
CPU timing is a nominal stock-machine model, not a physical hardware capture.
The DOC slot equations follow the corrected ES5503 model used for validation.
"""
import memmap
from array import array
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import wave

from doc_output import Output
from elf import read as read_elf
from emu816 import Emu
from music_pack import decode_lz, inspect_song

CLOCK = 7159090
SCAN = 34 * 8
RATE = 48000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack(data):
    meta = inspect_song(data)
    if data[:4] == b'WDP2':
        packed = struct.unpack_from('<H', data, 10)[0]
        waves = data[32:32 + meta['doc_bytes']]
    else:
        block, packed = struct.unpack_from('<2H', data, 18)
        delta = bytearray()
        pos = struct.unpack_from('<H', data, 8)[0]
        while len(delta) < meta['doc_bytes']:
            part, pos = decode_lz(data, pos, packed, min(block, meta['doc_bytes'] - len(delta)),
                                  preserve_until=len(data))
            delta.extend(part)
        waves = bytearray()
        previous = 0
        for value in delta:
            previous = (previous + value) & 255
            waves.append(previous)
    hot, _ = decode_lz(data, packed, len(data), meta['hot_bytes'], relocated=65536 - len(data))
    ram = bytearray(65536)
    ram[meta['doc_base']:meta['doc_base'] + len(waves)] = waves
    ram[0xff00:] = bytes([128]) * 256
    return hot, ram, meta


class Player(Emu):
    """Execute the shipped music code and record serialized DOC register writes."""
    def __init__(self, engine, hot, music_volume=15, system_volume=15):
        super().__init__()
        segments, self.symbols = read_elf(engine)
        for name in ('StartMusic', 'MusicWake', 'inputIrq', 'inputIrqEnd', 'musicVolume', 'musicLoaded'):
            if name not in self.symbols:
                raise ValueError('engine ELF lacks music symbol ' + name)
        for segment in segments:
            self.load(segment['address'], segment['data'])
        self.load(memmap.MUSIC_BASE, hot)
        self.wr16(self.symbols['musicVolume'], music_volume)
        self.wr16(self.symbols['musicLoaded'], 1)
        self.m[memmap.SYSTEM_VOLUME] = system_volume
        # The routine interpreter supplies a subroutine return frame. The IRQ
        # restores all registers before this exit; replace only RTI with RTL.
        end = self.symbols['inputIrqEnd']
        if self.m[end] != 0x40:
            raise ValueError('unsupported music IRQ return contract')
        self.m[end] = 0x6b
        self.pointer = 0
        self.control = 0x20 | system_volume
        self.latch = 0x80
        self.registers = bytearray(256)
        self.registers[0xa0:0xc0] = bytes([3]) * 32
        self.writes = []
        self.origin = self.io_accesses = self.busy = 0
        self.irq = False
        self.deadline = self.started = None
        self.wakes = 0

    def tick(self):
        # Fast CPU accesses take five 14M clocks; an I/O access takes fourteen.
        # Integer half-DOC clocks avoid floating-point drift at service edges.
        return self.origin + (5 * self.cycles + 9 * self.io_accesses) // 2

    def rd8(self, address):
        if memmap.SOUNDCTL <= address <= memmap.SOUNDADRH:
            self.io_accesses += 1
        if address == memmap.SOUNDCTL:
            return self.control | (128 if self.tick() < self.busy else 0)
        if address == memmap.SOUNDDATA:
            old = self.latch
            if self.pointer == 0xe0:
                self.latch = 0x3b if self.irq else 0xff
            elif self.pointer == 0xe1:
                self.latch = 0xff
                self.irq = False
            else:
                self.latch = self.registers[self.pointer & 255]
            if self.control & 32:
                self.pointer = (self.pointer + 1) & 65535
            self.busy = self.tick() + 8
            return old
        return super().rd8(address)

    def wr8(self, address, value):
        value &= 255
        if memmap.SOUNDCTL <= address <= memmap.SOUNDADRH:
            self.io_accesses += 1
        if address == memmap.SOUNDCTL:
            self.control = value
        elif address == memmap.SOUNDADRL:
            self.pointer = (self.pointer & 0xff00) | value
        elif address == memmap.SOUNDADRH:
            self.pointer = (self.pointer & 255) | (value << 8)
        elif address == memmap.SOUNDDATA:
            if self.control & 64:
                raise ValueError('unexpected DOC RAM upload during cached music playback')
            register = self.pointer & 255
            tick = ((self.tick() + 7) // 8) * 8
            self.registers[register] = value
            self.writes.append((tick, register, value))
            if register == 0xbd and not value & 1:
                frequency = self.registers[29] | self.registers[61] << 8
                if not frequency or self.registers[0xdd] & 63 or self.registers[0x9d] != 255:
                    raise ValueError('unsupported music timer configuration')
                scans = (131072 + frequency - 1) // frequency
                first = ((tick - 232 + SCAN - 1) // SCAN) * SCAN + 232
                self.deadline = first + (scans - 1) * SCAN + 4
            if self.control & 32:
                self.pointer = (self.pointer + 1) & 65535
            self.busy = tick + 8
        else:
            super().wr8(address, value)

    def step(self):
        if self.started is None and (self.pb << 16 | self.pc) == self.symbols['MusicWake']:
            self.started = self.tick()
        super().step()

    def routine(self, name):
        address = self.symbols[name]
        self.call(address >> 16, address & 65535, long_return=True)

    def run(self):
        self.routine('StartMusic')
        if self.started is None or self.deadline is None:
            raise ValueError('music did not start')
        self.wakes = 1
        while self.rd16((memmap.MUSIC_BASE+0x20)):
            if self.wakes >= 100000 or self.tick() > CLOCK * 1800:
                raise ValueError('music has no bounded loop')
            if self.tick() >= self.deadline:
                raise ValueError('music handler overran its next timer event')
            # Nominal IRQ entry delay; run the actual save/acknowledge/dispatch
            # code after this. Foreground load and disk stalls are excluded.
            self.origin = self.deadline + 20
            self.cycles = self.io_accesses = 0
            self.irq = True
            self.routine('inputIrq')
            self.wakes += 1
        return self.writes, self.started, self.deadline


def synthesize(ram, writes, start, end, rate=RATE, system_volume=15, part_tags=None, parts=()):
    """Time-average the multiplexed DOC DAC, with no song-dependent gain.

    A sample advances the complete N-byte table. Reset occurs at the voice's
    service slot, not immediately on a CPU write. One-shot wrap emits silence.
    Both stereo routes feed the stock mono output. Silent refresh slots retain
    oscillator 31's zero level, as in the game's 32-oscillator configuration.
    """
    output = Output(CLOCK, rate, end)
    stems = {channel: Output(CLOCK, rate, end) for channel in parts}
    volume_owner = [0] * 32
    if stems and (part_tags is None or len(part_tags) != len(writes)):
        raise ValueError('instrument rendering needs one authenticated label per write')
    regs = [bytearray(32) for _ in range(7)]
    regs[5][:] = bytes([3]) * 32
    frequency = [0] * 32
    phase = [0] * 32
    pointer = [0] * 32
    masks = [255] * 32
    shifts = [9] * 32
    cycles = [131071] * 32
    pos = 0
    writes = list(writes) + [(end + SCAN, 0, 0)]
    for scan in range(0, end + SCAN, SCAN):
        for voice in range(32):
            tick = scan + voice * 8
            if tick >= end:
                break
            while writes[pos][0] <= tick:
                _, register, value = writes[pos]
                channel = part_tags[pos] if part_tags is not None else 0
                pos += 1
                if register >= 0xe0:
                    if register == 0xe1 and ((value >> 1) & 31) != 31:
                        raise ValueError('preview requires the game\'s 32-oscillator DOC configuration')
                    continue
                v = register & 31
                kind = register >> 5
                regs[kind][v] = value
                if kind == 2 and stems:
                    if value and 4 <= v < 28 and channel not in stems:
                        raise ValueError('audible volume has no instrument output')
                    volume_owner[v] = channel
                if kind < 2:
                    frequency[v] = regs[0][v] | regs[1][v] << 8
                elif kind in (4, 6):
                    size = (regs[6][v] >> 3) & 7
                    resolution = regs[6][v] & 7
                    masks[v] = (1 << (8 + size)) - 1
                    shifts[v] = 9 + resolution - size
                    cycles[v] = (1 << (17 + resolution)) - 1
                    pointer[v] = ((regs[4][v] << 8) | ((regs[6][v] & 64) << 10)) & ~masks[v]
            control = regs[5][voice]
            if control & 3 == 3:
                phase[voice] = 0
            if control & 1:
                continue
            freq = frequency[voice]
            carry = (phase[voice] & cycles[voice]) + freq > cycles[voice]
            phase[voice] = (phase[voice] + freq) & 0xffffff
            address = pointer[voice] | ((phase[voice] >> shifts[voice]) & masks[voice])
            if address >= len(ram):
                raise ValueError('DOC voice addressed outside IIgs wave RAM')
            sample = ram[address]
            regs[3][voice] = sample
            mode = (control >> 1) & 3
            if stems and mode == 2 and 4 <= voice < 28:
                raise ValueError('instrument isolation does not support DOC AM music')
            if not sample or carry:
                if mode == 2 and not voice & 1:
                    phase[voice] = phase[voice + 1] = 0
                if not sample or mode in (1, 3):
                    regs[5][voice] |= 1
                if regs[5][voice] & 3 == 3:
                    phase[voice] = 0
                if mode == 3:
                    regs[5][voice ^ 1] &= ~1
            if not sample or regs[5][voice] & 1 or mode == 2 and voice & 1:
                continue
            volume = regs[2][voice]
            if voice and not voice & 1 and ((regs[5][voice - 1] >> 1) & 3) == 2:
                volume = regs[3][voice - 1]
            product = (sample - 128) * volume
            if not product:
                continue
            output.add(product, tick + 4, min(tick + 12, end))
            if stems and volume_owner[voice] in stems:
                stems[volume_owner[voice]].add(product, tick + 4, min(tick + 12, end))
    mixed = output.finish(start, system_volume)
    if not stems:
        return mixed
    return dict(mix=mixed, **{f'ch{ch:02}': stem.finish(start, system_volume)
                            for ch, stem in stems.items()})


def write_wave(path, samples, rate=RATE):
    """PCM at the modeled system output level; only the final DAC range clips."""
    pcm = array('h')
    peak = square = 0.0
    clipped = 0
    for value in samples:
        peak = max(peak, abs(value))
        square += value * value
        integer = round(value * 32768)
        clipped += int(integer < -32768 or integer > 32767)
        pcm.append(max(-32768, min(32767, integer)))
    if sys.byteorder != 'little':
        pcm.byteswap()
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, rate, len(pcm), 'NONE', 'not compressed'))
        output.writeframes(pcm.tobytes())
    return dict(frames=len(pcm), sample_rate=rate, peak=peak,
                rms=(square / max(1, len(pcm))) ** .5, clipped_samples=clipped,
                sha256=sha(Path(path).read_bytes()))


def render(bank_path, engine_path, output_wav, music_volume=15, system_volume=15, parts=None):
    if not 1 <= music_volume <= 15 or not 0 <= system_volume <= 15:
        raise ValueError('music volume must be 1..15 and system volume 0..15')
    bank_path, engine_path, output_wav = map(Path, (bank_path, engine_path, output_wav))
    data = bank_path.read_bytes()
    engine_sha = sha(engine_path.read_bytes())
    hot, ram, meta = unpack(data)
    player = Player(engine_path, hot, music_volume, system_volume)
    writes, start, end = player.run()
    labels, channels, part_inputs = None, [], {}
    if parts is not None:
        from doc_parts import trace_labels
        paths = {name: Path(parts)/name for name in ('unit.bin', 'notes.json', 'stereo.txt')}
        unit = paths['unit.bin'].read_bytes()
        if sha(unit[:meta['hot_bytes']]) != meta['hot_sha256']:
            raise ValueError('instrument unit does not match the compiled bank')
        labels, channels = trace_labels(writes, start, unit, paths['stereo.txt'],
                                        paths['notes.json'], music_volume)
        part_inputs = {str(path.resolve()): sha(path.read_bytes()) for path in paths.values()}
    samples = synthesize(ram, writes, start, end, system_volume=system_volume,
                         part_tags=labels, parts=channels)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_wav.with_name(output_wav.name + '.partial')
    if channels:
        mixes = samples
        samples = mixes['mix']
    result = write_wave(temporary, samples)
    temporary.replace(output_wav)
    music_writes = [(register, value) for _, register, value in writes if 4 <= register % 32 < 28]
    report = dict(format=1, renderer='compiled-doc-python', bank_sha256=sha(data), engine_sha256=engine_sha,
                hot_sha256=meta['hot_sha256'], wave_sha256=meta['wave_sha256'],
                music_volume=music_volume, system_volume=system_volume, route='stock-mono', output_filter='ROM01 board circuit',
                gain=1.0, normalization=False, native_capture=False, hardware_capture=False,
                timing='nominal stock CPU, serialized DOC interface, 32 oscillator slots',
                sound_effects=False, speaker=False, wakes=player.wakes,
                register_writes=len(music_writes), register_sha256=sha(bytes(v for row in music_writes for v in row)),
                duration=(end - start) / CLOCK, output=result)
    if channels:
        report['part_inputs'] = part_inputs
        report['channels'] = channels
        for channel in channels:
            key = f'ch{channel:02}'
            target = output_wav.with_name(key+'.wav')
            temporary = target.with_name(target.name+'.partial')
            part_result = write_wave(temporary, mixes[key])
            temporary.replace(target)
            part_report = dict(report, part=channel, output=part_result)
            target.with_suffix('.json').write_text(json.dumps(part_report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bank', type=Path)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--parts', type=Path, help='compiled song details for authenticated instrument WAVs')
    args = parser.parse_args()
    receipt = args.out.with_suffix('.json')
    receipt.unlink(missing_ok=True)
    try:
        result = render(args.bank, args.engine, args.out, parts=args.parts)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
