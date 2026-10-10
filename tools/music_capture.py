"""Read-only song-start and GLU observation for native transition tests."""
import memmap
import json
import re
import struct

from elf import read
from music_pack import inspect_song, decode_lz
from wolfdata import ROOT


def lua():
    _, symbols = read(ROOT/'build/wolf.elf')
    songs = json.loads((ROOT/'build/sound/manifest.json').read_text())['songs']
    headers = {}
    for song in songs:
        bank = (ROOT/f'build/sound/song-{song["id"]:02}.bin').read_bytes()
        checked = inspect_song(bank)
        packed = struct.unpack_from('<H', bank, 10 if bank[:4] == b'WDP2' else 20)[0]
        hot, _ = decode_lz(bank, packed, len(bank), checked['hot_bytes'],
                           relocated=65536-len(bank))
        # Validate the actual prepared header, including imported banks whose
        # compact manifest deliberately omits compiler diagnostic fields.
        headers[song['id']] = list(hot[:20])
    script = memmap.fill(r'''
local musicHeaders=@HEADERS@
local musicBusy,musicReads,musicChecking=0,0,false
local function musicAssert(value,message)
 if not value then
  -- Address-space tap exceptions may otherwise disappear into the emulator.
  print('MUSIC_ERROR '..message);io.stdout:flush();error(message)
 end
 return value
end
musicStartTap=mem:install_write_tap(@ACTIVE@,@ACTIVE@,"song-start",function(a,d,m)
 if d~=1 then return end
 local id=mem:read_u16(@SONG@)
 local expected=musicAssert(musicHeaders[id],"unknown started song "..id)
 for i,v in ipairs(expected) do musicAssert(mem:read_u8(@MM:MUSIC_BASE@+i-1)==v,"wrong hot song header "..id) end
 musicChecking=true
 print(string.format("SONG_PLAY %.9f %d %d %d",manager.machine.time:as_double(),id,mem:read_u8(0x3e4),mem:read_u16(@FLOOR@)))
end)
musicBusyTap=mem:install_read_tap(@MM:SOUNDCTL@,@MM:SOUNDCTL@,"song-busy",function(a,d,m) musicBusy=d end)
musicReadTap=mem:install_read_tap(@MM:SOUNDDATA@,@MM:SOUNDDATA@,"song-read",function(a,d,m)
 if not musicChecking then return end
 musicReads=musicReads+1
 musicAssert(musicBusy&128==0 and cpu.state.P.value&4~=0,"unsafe GLU read")
end)
musicWriteTap=mem:install_write_tap(@MM:SOUNDCTL@,@MM:SOUNDADRH@,"song-write",function(a,d,m)
 if not musicChecking then return end
 if a~=@MM:SOUNDDATA@ then musicAssert(musicReads%2==0,"unpaired GLU read");musicReads=0
 else musicAssert(musicBusy&128==0 and cpu.state.P.value&4~=0,"unsafe GLU write") end
end)
''')
    script = script.replace('@HEADERS@', '{'+','.join(
        '[%d]={%s}' % (n, ','.join(map(str, h))) for n, h in headers.items())+'}')
    for token, name in [('ACTIVE', 'musicActive'), ('SONG', 'currentSong'), ('FLOOR', 'levelIndex')]:
        script = script.replace('@'+token+'@', str(symbols[name]))
    return script


def events(log):
    assert not re.search(r'Lua (?:error|Error)|MUSIC_ERROR|unsafe GLU|unpaired GLU|wrong hot song|unknown started song', log), log[-2500:]
    return [dict(seconds=float(t), song=int(s), page=int(p), floor=int(f))
            for t, s, p, f in re.findall(r'^SONG_PLAY ([\d.]+) (\d+) (\d+) (\d+)$', log, re.M)]


def art_lua():
    sections, symbols = read(ROOT/'build/wolf.elf')
    if 'expanded' not in symbols:
        # An RTS entry means art is already lit. There is no runtime
        # expansion interval in which to require a music wake.
        address = symbols['ExpandArt']
        code = next(s['data'][address-s['address']:address-s['address']+1]
                    for s in sections if s['address'] <= address < s['address']+len(s['data']))
        assert code == b'\x60', 'unrecognized art expansion entry'
        return ''
    script = r'''
local artRun=nil
artStartTap=mem:install_read_tap(@START@,@START@,"art-start",function(a,d,m)
 if cpu.state.PB.value~=2 then return end
 artRun={time=manager.machine.time:as_double(),song=mem:read_u16(@SONG@),
  floor=mem:read_u16(@FLOOR@),active=mem:read_u16(@ACTIVE@),
  enabled=cpu.state.P.value&4==0 and 1 or 0,wakes=0}
end)
artWakeTap=mem:install_read_tap(@WAKE@,@WAKE@,"art-music-wake",function(a,d,m)
 if artRun and cpu.state.PB.value==0x3d and mem:read_u16(@ACTIVE@)==1 then
  artRun.wakes=artRun.wakes+1
 end
end)
artEndTap=mem:install_read_tap(@END@,@END@,"art-end",function(a,d,m)
 if not artRun or cpu.state.PB.value~=2 then return end
 if artRun.active==1 then
  local doc=manager.machine.devices[':doc'].spaces['rom']
  for i=0,255 do assert(doc:read_u8(0xff00+i)==(i==0 and 255 or i),"art load damaged DOC timer ramp") end
 end
 print(string.format("ART_MUSIC %.9f %d %d %d %d %d",
  manager.machine.time:as_double()-artRun.time,artRun.song,artRun.floor,
  artRun.active,artRun.enabled,artRun.wakes))
 artRun=nil
end)
'''
    for token, name in [('START', 'ExpandArt'), ('END', 'expanded'),
                        ('WAKE', 'MusicWake'), ('ACTIVE', 'musicActive'),
                        ('SONG', 'currentSong'), ('FLOOR', 'levelIndex')]:
        script = script.replace('@'+token+'@', str(symbols[name]))
    return script


def art_events(log):
    return [dict(seconds=float(t), song=int(s), floor=int(f), active=int(a),
                 interrupts_enabled=bool(int(i)), music_wakes=int(w))
            for t, s, f, a, i, w in re.findall(
                r'^ART_MUSIC ([\d.]+) (\d+) (\d+) (\d+) (\d+) (\d+)$', log, re.M)]
