"""Capture a frozen game's music and isolated parts through its native DOC player.

The disk loads the bank normally. The harness disables effect requests and parks
the foreground loop after the automatic demo starts; interrupts keep running.
Part isolation changes only the final DOC volume writes. Original writes must
still match the independent decoder, including those of the muted parts.
"""
import memmap
import argparse
from array import array
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

TOOLS = Path(__file__).resolve().parent
from elf import read as read_elf
from game_profile import read_toml
import lua_guard
from music_pack import inspect_song

sys.path.insert(0, str(TOOLS / 'doccompiler'))
import unit2


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def tree_hashes(path):
    return {str(p.relative_to(path)): digest(p.read_bytes()) for p in sorted(path.rglob('*')) if p.is_file()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


from doc_parts import music_writes, decode_groups, tagged_oracle


SCRIPT = memmap.fill(r'''
local m=manager.machine;local cpu=m.devices[':maincpu'];local s=cpu.spaces.program
local oracleFile=assert(io.open(@ORACLE@,'rb'));local oracle=oracleFile:read('a');oracleFile:close()
local trace=assert(io.open(@OUT@..'/writes.csv','w'))
trace:write('time,register,original,emitted,channel\n')
local started,loopEnd,parked=nil,nil,false
local parkArmed=false
local coldDumped=false;local count=0;local pointer,control,busy=0,0,0
local effectVolumes,speakerAccesses,violations,masked=0,0,0,0
local failure=nil;local done=false;local lastControlVolume=nil
local nonMusicVolumes={}
local nonMusicControls={}
local configured=false
local function now() return m.time:as_double() end
local function dump(name,space,base,length)
 local f=assert(io.open(@OUT@..'/'..name,'wb'));local bytes={}
 for i=0,length-1 do bytes[#bytes+1]=string.char(space:read_u8(base+i)) end
 f:write(table.concat(bytes));f:close()
end
local function fail(message) if not failure then failure=message;print('BENCH_ERROR '..message) end end
local function finish()
 if done then return end;done=true;trace:close()
 local f=assert(io.open(@OUT@..'/native.json','w'))
 f:write(string.format('{"started":%.9f,"loop_end":%.9f,"parked":%s,"writes":%d,"effect_volume_writes":%d,"speaker_accesses":%d,"doc_access_violations":%d,"masked_volume_writes":%d,"failed":%s}',started or -1,loopEnd or -1,tostring(parked),count,effectVolumes,speakerAccesses,violations,masked,tostring(failure~=nil)))
 f:close();print(failure and 'BENCH_FAILED' or 'BENCH_FINISHED');m:exit()
end
-- Returning zero uses both native effect-off paths without changing music gain.
s:install_read_tap(@SFX@,@SFX@+1,'bench-effects-off',function() return 0 end)
-- Choose the system setting once, before the game's sound initialization.
-- Subsequent control/register writes are entirely the production player's.
s:install_read_tap(@INIT@,@INIT@,'bench-system-setting',function()
 if not configured then
  configured=true
  if @CONFIGSYSTEM@ then s:write_u8(@MM:SYSTEM_VOLUME@,@SYSTEM@) end
 end
end)
s:install_read_tap(@MM:SOUNDCTL@,@MM:SOUNDCTL@,'bench-busy',function(a,d) busy=d end)
s:install_write_tap(@MM:SOUNDCTL@,@MM:SOUNDCTL@,'bench-control',function(a,d)
 control=d
 if started then
  if (d&15)~=@SYSTEM@ then fail('system volume changed') end
  lastControlVolume=d&15
 end
end)
s:install_write_tap(@MM:SOUNDADRL@,@MM:SOUNDADRL@,'bench-low',function(a,d) pointer=(pointer&0xff00)|d end)
s:install_write_tap(@MM:SOUNDADRH@,@MM:SOUNDADRH@,'bench-high',function(a,d) pointer=(pointer&0xff)|d<<8 end)
s:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'bench-data-read',function()
 if started and (busy&128~=0 or cpu.state.P.value&4==0) then violations=violations+1 end
 if control&32~=0 then pointer=(pointer+1)&65535 end
end)
s:install_write_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,'bench-data-write',function(a,d)
 local emitted=d
 if control&64==0 and pointer>=0x40 and pointer<0x60 then
  local oscillator=pointer&31
  if oscillator<4 or oscillator>=28 then
   nonMusicVolumes[oscillator]=d
   if started and d~=0 and ((nonMusicControls[oscillator] or 0)&1)==0 then fail('non-music oscillator became audible: '..oscillator) end
  end
  if @SILENCE@ and oscillator>=4 and oscillator<28 then emitted=0 end
 end
 if control&64==0 and pointer>=0xa0 and pointer<0xc0 then
  local oscillator=pointer&31
  if oscillator<4 or oscillator>=28 then
   nonMusicControls[oscillator]=d
   if started and d&1==0 and nonMusicVolumes[oscillator]~=0 then fail('non-music oscillator started: '..oscillator) end
  end
 end
 if started then
  if busy&128~=0 or cpu.state.P.value&4==0 then violations=violations+1 end
  if control&64==0 then
   local reg=pointer&255;local oscillator=reg&31
   if reg>=0x40 and reg<=0x43 and d~=0 then effectVolumes=effectVolumes+1 end
   if oscillator>=4 and oscillator<28 then
    local at=(count*3)%#oracle+1
    local er,ev,ch=oracle:byte(at,at+2)
    if er~=reg or ev~=d then fail(string.format('register %d: expected %02x=%02x, got %02x=%02x',count,er,ev,reg,d)) end
    if @PART@>=0 and ch~=@PART@ and reg>=0x40 and reg<0x60 then
     emitted=0;if d~=0 then masked=masked+1 end
    end
    trace:write(string.format('%.9f,%d,%d,%d,%d\n',now(),reg,d,emitted,ch))
    if count==#oracle//3 and not loopEnd then loopEnd=now() end
    count=count+1
   end
  end
 end
 if control&32~=0 then pointer=(pointer+1)&65535 end
 return emitted
end)
for _,address in ipairs({0xc030,@MM:SPKR@,@MM:SPKR_E1@}) do
 s:install_read_tap(address,address,'bench-speaker-read',function() if started then speakerAccesses=speakerAccesses+1 end end)
 s:install_write_tap(address,address,'bench-speaker-write',function() if started then speakerAccesses=speakerAccesses+1 end end)
end
s:install_read_tap(@START@,@START@,'bench-bank',function()
 if parkArmed and not coldDumped and s:read_u16(@SONG@)==@SONGID@ then
  coldDumped=true;dump('loaded-cold.bin',s,@MM:MUSIC_BASE@,@COLDLEN@)
 end
end)
s:install_read_tap(@WAKE@,@WAKE@,'bench-first-wake',function()
 if coldDumped and not started and s:read_u16(@SONG@)==@SONGID@ then
  started=now()
  dump('loaded-hot.bin',s,@MM:MUSIC_BASE@,@HOTLEN@)
  dump('loaded-doc.bin',m.devices[':doc'].spaces.rom,@DOCBASE@,@DOCLEN@)
  if s:read_u16(@MUSIC@)~=@MASTER@ then fail('music volume differs from profile') end
  if s:read_u8(@MM:SYSTEM_VOLUME@)~=@SYSTEM@ then fail('system volume differs from profile') end
  for _,oscillator in ipairs({0,1,2,3,28,29,30,31}) do
   if nonMusicVolumes[oscillator]~=0 and ((nonMusicControls[oscillator] or 0)&1)==0 then fail('non-music oscillator is not verified silent: '..oscillator) end
  end
  print(string.format('BENCH_START %.9f',started))
 end
end)
-- WAI/BRA idles the foreground CPU while the unchanged IRQ/music code runs.
s:install_read_tap(@PARK@,@PARK@,'bench-park',function()
 if parkArmed and not parked then
  parked=true
  if cpu.state.P.value&4~=0 then fail('foreground parked with IRQ disabled') end
 end
end)
emu.register_frame_done(function()
 if done then return end
 if not parkArmed and s:read_u8(0x3e4)==@PHASE@ and s:read_u16(@ACTIVE@)==1 then
  if s:read_u8(@FRAME@)~=0x22 then fail('frameLoop does not begin with JSL') else
   -- Restart the requested song through the production disk loader/player.
   -- The foreground then idles; music IRQs and all volume writes stay native.
   local code={0x08,0xc2,0x30,0xa9,0xff,0xff,0x8f,@SONG@&255,(@SONG@>>8)&255,(@SONG@>>16)&255,
     0xa9,@SONGID@,0,0x22,@SELECT@&255,(@SELECT@>>8)&255,(@SELECT@>>16)&255,0x28,0xcb,0x80,0xfd}
   for i,v in ipairs(code) do s:write_u8(@PARK@+i-1,v) end
   s:write_u8(@FRAME@,0x5c)
   for i=0,2 do s:write_u8(@FRAME@+1+i,(@PARK@>>(i*8))&255) end
   parkArmed=true
  end
 end
 if started and (s:read_u16(@SONG@)~=@SONGID@ or s:read_u16(@MUSIC@)~=@MASTER@) then fail('song or music volume changed') end
 if failure or (loopEnd and now()>loopEnd+0.5) then finish()
 elseif now()>@LIMIT@ then fail('timed out before a complete music loop');finish() end
end)
''')


def load_profile(path):
    profile = read_toml(path)
    require(profile['format'] == 1, 'unsupported bench profile')
    for key, value in profile['files'].items():
        item = Path(value).expanduser()
        profile['files'][key] = str((path.parent / item).resolve())
    for key, expected in profile['sha256'].items():
        require(digest(Path(profile['files'][key]).read_bytes()) == expected, key + ' hash mismatch')
    for key in ('disk', 'elf', 'emulator', 'bank', 'unit', 'waves', 'notes', 'ledger'):
        require(key in profile['sha256'], key + ' must be pinned by SHA-256')
    if 'disk2' in profile['files']:
        require('disk2' in profile['sha256'], 'disk2 must be pinned by SHA-256')
    return profile


def capture(profile, symbols, checked, oracle, out, part):
    out.mkdir(parents=True)
    files, settings = profile['files'], profile['playback']
    for name in ('cfg', 'nvram'):
        shutil.copytree(files[name], out / name)
        require(tree_hashes(out / name) == profile['seed_sha256'][name], name + ' seed changed')
    for name in ('state', 'snap'):
        (out / name).mkdir()
    shutil.copyfile(files['disk'], out / 'wolf-hd.po')
    if 'disk2' in files:
        shutil.copyfile(files['disk2'], out / 'wolf-hd2.po')
    (out / 'oracle.bin').write_bytes(oracle)
    values = dict(OUT=json.dumps(str(out)), ORACLE=json.dumps(str(out / 'oracle.bin')),
                  SFX=symbols['soundVolume'], MUSIC=symbols['musicVolume'], MASTER=settings['music_volume'],
                  SYSTEM=settings['system_volume'], PART=part, START=symbols['StartMusic'],
                  WAKE=symbols['MusicWake'], SONG=symbols['currentSong'], SONGID=settings['song_id'],
                  COLDLEN=checked['bytes'], HOTLEN=checked['hot_bytes'], DOCBASE=checked['doc_base'],
                  DOCLEN=checked['doc_bytes'], ACTIVE=symbols['musicActive'], FRAME=symbols['frameLoop'],
                  PARK=memmap.REG_ENDPOINT_ORIGINALS, SELECT=symbols['SelectMusic'], PHASE=settings['demo_phase'], LIMIT=settings['timeout_seconds'])
    values.update(INIT=symbols['InitSound'], CONFIGSYSTEM=str(settings.get('configure_system_volume', False)).lower(),
                  SILENCE=str(settings.get('silence_control', False)).lower())
    script = SCRIPT
    for key, value in values.items():
        script = script.replace('@' + key + '@', str(value))
    lua_guard.write(out / 'bench.lua', script)
    command = [files['emulator'], 'apple2gsr1', '-rompath', settings['rompath'], '-ramsize', '4352K',
               '-sl7', 'cffa3000', '-hard1', str(out / 'wolf-hd.po'), '-volume', '0', '-video', 'none', '-sound', 'none',
               '-nothrottle', '-skip_gameinfo', '-seconds_to_run', str(settings['timeout_seconds'] + 5),
               '-autoboot_delay', '0', '-autoboot_script', str(out / 'bench.lua'),
               '-wavwrite', str(out / 'speaker-buses.wav'), '-nonatural', '-noui_active', '-nomouse']
    if 'disk2' in files:
        command += ['-hard2', str(out / 'wolf-hd2.po')]
    for option, directory in (('cfg', 'cfg'), ('nvram', 'nvram'), ('state', 'state'), ('snapshot', 'snap')):
        command += ['-' + option + '_directory', str(out / directory)]
    save_json(out / 'command.json', command)
    with (out / 'mame.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600,
                       env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_MAC_BACKGROUND_APP='1'))
    report = json.loads((out / 'native.json').read_text())
    require(not report['failed'], 'native bench failed; see ' + str(out / 'mame.log'))
    require(report['parked'] and report['loop_end'] > report['started'], 'no complete parked playback')
    for counter in ('effect_volume_writes', 'speaker_accesses', 'doc_access_violations'):
        require(report[counter] == 0, f'{counter}: {report[counter]}')
    require(digest((out / 'loaded-cold.bin').read_bytes()) == profile['sha256']['bank'], 'loaded bank differs')
    require(digest((out / 'loaded-doc.bin').read_bytes()) == checked['wave_sha256'], 'loaded samples differ')
    hot = (out / 'loaded-hot.bin').read_bytes()
    unit = Path(files['unit']).read_bytes()
    initialized = unit2.Player(unit, settings['music_volume']).u
    require(hot[:20] == unit[:20] and hot[0x100:0x500] == initialized[0x100:0x500] and
            hot[0x600:] == unit[0x600:len(hot)], 'initialized native song differs')
    with wave.open(str(out / 'speaker-buses.wav'), 'rb') as source:
        require(source.getsampwidth() == 2, 'expected signed 16-bit MAME audio')
        rate, buses = source.getframerate(), source.getnchannels()
        start = round(report['started'] * rate)
        end = round(report['loop_end'] * rate)
        source.setpos(start)
        data = array('h', source.readframes(end - start))
        if sys.byteorder != 'little':
            data.byteswap()
    # Bus zero is the frozen ROM01 configuration's mono speaker. Other buses
    # include drive sounds; selecting it is routing, not a gain adjustment.
    pcm = data[settings['speaker_bus']::buses]
    require(len(pcm) == end - start, 'truncated recording')
    report.update(frames=len(pcm), sample_rate=rate, source_buses=buses, crop_start_frame=start,
                  peak=max(map(abs, pcm)), clipped_samples=sum(abs(v) >= 32767 for v in pcm),
                  pcm_sha256=digest(pcm.tobytes()), trace_sha256=digest((out / 'writes.csv').read_bytes()))
    if settings.get('silence_control', False):
        require(report['peak'] == 0, 'non-music sound contaminated the capture')
    else:
        require(report['peak'] > 0 and report['clipped_samples'] == 0, 'silent or clipped output')
    with wave.open(str(out / 'music.wav'), 'wb') as target:
        target.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        if sys.byteorder != 'little':
            pcm.byteswap()
        target.writeframes(pcm.tobytes())
        if sys.byteorder != 'little':
            pcm.byteswap()
    report['wav_sha256'] = digest((out / 'music.wav').read_bytes())
    report['raw_buses_sha256'] = digest((out / 'speaker-buses.wav').read_bytes())
    save_json(out / 'validation.json', report)
    if not settings.get('keep_temporary_captures', False):
        # Preserve verified listening audio, hashes, traces and failure evidence.
        removed = []
        for name in ('speaker-buses.wav', 'wolf-hd.po', 'wolf-hd2.po'):
            path = out / name
            if path.exists():
                removed.append(dict(file=name, bytes=path.stat().st_size, sha256=digest(path.read_bytes())))
                path.unlink()
        save_json(out / 'temporary-cleanup.json', removed)
    return report, pcm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='new output directory; never overwritten')
    parser.add_argument('--mix-only', action='store_true', help='repeat the mix, without rendering isolated parts')
    args = parser.parse_args()
    profile = load_profile(args.profile.resolve())
    out = args.out.resolve()
    require(not out.exists(), 'output directory already exists')
    files = profile['files']
    profile['seed_sha256'] = {name: tree_hashes(Path(files[name])) for name in ('cfg', 'nvram')}
    bank, unit = Path(files['bank']).read_bytes(), Path(files['unit']).read_bytes()
    checked = inspect_song(bank)
    require(digest(unit[:checked['hot_bytes']]) == checked['hot_sha256'], 'unit is not the pinned bank')
    require(digest(Path(files['waves']).read_bytes()) == checked['wave_sha256'], 'waves are not the pinned bank')
    require(any(bank in Path(files[k]).read_bytes() for k in ('disk','disk2') if k in files), 'pinned bank is absent from disk')
    _, symbols = read_elf(Path(files['elf']))
    oracle, channels = tagged_oracle(unit, Path(files['ledger']), Path(files['notes']), profile['playback']['music_volume'])
    out.mkdir(parents=True)
    shutil.copyfile(args.profile, out / 'profile.toml')
    save_json(out / 'identity.json', dict(profile=profile, bank=checked, music_writes_per_loop=len(oracle)//3,
              channels=channels, harness='native disk load; effect-off read gate; WAI foreground; DOC volume-only part gate',
              normalization=False, music_bank_injection=False))
    reports = {}
    print('Rendering full music, first pass', flush=True)
    reports['mix'], mix = capture(profile, symbols, checked, oracle, out / 'mix', -1)
    print('Rendering full music, repeatability pass', flush=True)
    reports['repeat'], repeat = capture(profile, symbols, checked, oracle, out / 'repeat', -1)
    require(mix == repeat and reports['mix']['trace_sha256'] == reports['repeat']['trace_sha256'],
            'fresh identical runs produced different audio or register timing')
    if not args.mix_only:
        total = [0] * len(mix)
        for channel in channels:
            name = f'ch{channel:02d}'
            print('Rendering isolated ' + name, flush=True)
            report, pcm = capture(profile, symbols, checked, oracle, out / name, channel)
            require(report['crop_start_frame'] == reports['mix']['crop_start_frame'] and len(pcm) == len(mix),
                    name + ' timing differs')
            # Part isolation must not affect any native command or its timing.
            def original_trace(path):
                return [row.split(',')[:3] for row in path.read_text().splitlines()[1:]]
            require(original_trace(out / name / 'writes.csv') == original_trace(out / 'mix/writes.csv'),
                    name + ' changed original native music writes')
            reports[name] = report
            for i, sample in enumerate(pcm):
                total[i] += sample
        error = max(abs(a - b) for a, b in zip(total, mix))
        save_json(out / 'stem-sum.json', dict(max_error_lsb=error, tolerance_lsb=len(channels)))
        require(error <= len(channels), 'isolated parts do not sum to the native full mix')
    save_json(out / 'PASS.json', dict(repeatable=True, isolated_parts=not args.mix_only, runs=reports))
    print('PASS: ' + str(out / 'mix/music.wav'), flush=True)


if __name__ == '__main__':
    main()
