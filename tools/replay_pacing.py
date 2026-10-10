"""Replay frozen input with frame phases and optional wall-art isolation.

The observer reads only fast RAM. It captures no video RAM, so screenshot
reads cannot change the emulated bus timing. Wall substitution is diagnostic
only: once, at the first live floor-zero frame. Later floor reloads may
restore the disk's artwork. No code or game state is replaced.
"""
import memmap
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

from elf import read
import lua_guard
import mame_kit
from replay_input import LUA
import logic_observer


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session', type=Path)
    ap.add_argument('--elf', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--wall-palette', type=Path)
    ap.add_argument('--wall-assets', type=Path, default=Path('build/levels/0'))
    ap.add_argument('--seconds', type=int, default=480)
    args = ap.parse_args()
    running = subprocess.run(['pgrep', '-fl', '/iigs.app/Contents/MacOS/iigs'],
                             capture_output=True, text=True).stdout
    root = Path(__file__).resolve().parents[1]
    if str(root/'build/tests') in running:
        raise SystemExit('Another test MAME for this checkout is running')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    work = out/'session'
    shutil.copytree(args.session, work)
    for name in ('cfg', 'nvram', 'state', 'snap'):
        (work/name).mkdir(exist_ok=True)
    _, symbols = read(args.elf)
    names = ('buildNext', 'ticCount', 'ticCommands', 'inputUntil',
             'heldCommand', 'demoMode', 'viewWidth', 'levelIndex',
             'levelState', 'doorPosition', 'doorOrient', 'pwallPosition')
    script = LUA.replace('@SYMBOLS@', '{'+','.join(f'{n}={symbols[n]}' for n in names)+'}')
    script = script.replace('@TAPS@', logic_observer.taps(symbols, 'logic', 'tic', handle='replayTic'))
    extra = memmap.fill(r'''
local world=assert(io.open(@WORLD@,"wb"))
local worldRow=0
local phaseStart={}
local phaseTimes={}
local previousPose=nil
for _,name in ipairs({"a2_config","bus_timing","ram_start"}) do
 local port=manager.machine.ioport.ports[":"..name]
 if port then print("PACING_SETTING "..name.." "..port:read()) end
end
local function bytes(base,n)
 local b={};for i=0,n-1 do b[#b+1]=string.char(s:read_u8(base+i)) end
 return table.concat(b)
end
local function phaseTap(address,name)
 return s:install_write_tap(address,address,name,function(a,d,m)
  if d==1 then phaseStart[name]=now()
  elseif d==2 and phaseStart[name] then phaseTimes[name]=now()-phaseStart[name] end
 end)
end
pacingPaint=phaseTap(0x3f3,"paint")
pacingCast=phaseTap(0x3f2,"cast")
pacingFrame=s:install_write_tap(0x3f0,0x3f0,"pacing",function(a,d,m)
 if d==1 then phaseTimes={};@REPLACE@
 elseif d==2 and started then
  local px,py,angle=s:read_u16(0x1000),s:read_u16(0x1002),s:read_u16(0x1004)
  local key=string.format("%d/%d/%d/%d",px,py,angle,s:read_u16(S.viewWidth))
  if live() and s:read_u16(S.levelState)==0 and key~=previousPose then
   worldRow=worldRow+1
   world:write(bytes(0x1000,256)..bytes(@MM:ART_FULL+0x32000@,8192)..bytes(S.doorPosition,128)..bytes(S.doorOrient,128)..bytes(S.pwallPosition,2))
   print(string.format('PACING_WORLD {"row":%d,"time":%.9f,"frame":%d,"width":%d,"floor":%d,"x":%d,"y":%d,"angle":%d}',worldRow,now(),frame,2*s:read_u16(S.viewWidth),s:read_u16(S.levelIndex),px,py,angle))
   previousPose=key
  end
  print(string.format('PACING_PHASE {"time":%.9f,"frame":%d,"paint":%.9f,"cast":%.9f}',now(),frame,phaseTimes.paint or 0,phaseTimes.cast or 0))
 end
end)
pacingStop=emu.add_machine_stop_notifier(function() world:close() end)
''')
    replacement = ''
    if args.wall_palette:
        palette = json.loads(args.wall_palette.read_text())
        units = struct.unpack_from('<H', (args.wall_assets/'art-tables.bin').read_bytes())[0]
        indices = (args.wall_assets/'art-index.bin').read_bytes()[:units*64]
        replacement = 'if not wallsReplaced and live() and s:read_u16(S.levelIndex)==0 then\n'
        for light in range(3):
            path = out/f'wall-light-{light}.bin'
            path.write_bytes(b''.join(bytes(palette['wall_lights'][light][c]) for c in indices))
            replacement += ('local f=assert(io.open('+json.dumps(str(path))+',"rb"));'
                            'local data=f:read("*a");f:close();'
                            f'for i=1,#data,2 do s:write_u16({memmap.ART_BASE+light*memmap.ART_BYTES}+i-1,string.unpack("<I2",data,i)) end\n')
        replacement += 'wallsReplaced=true;print("PACING_WALLS_REPLACED "..now()) end'
        extra = 'local wallsReplaced=false\n'+extra
    script += extra.replace('@WORLD@', json.dumps(str(out/'world.bin'))).replace('@REPLACE@', replacement)
    lua_guard.write(out/'observe.lua', script)
    command = ['nice', '-n', '20', mame_kit.BINARY, 'apple2gsr1', '-rompath',
               mame_kit.ROMPATH,
               '-ramsize', '4352K', '-sl7', 'cffa3000', '-hard1', str(work/'wolf-hd.po'),
               '-video', 'none', '-sound', 'none', '-nothrottle', '-skip_gameinfo',
               '-input_directory', str(work), '-playback', 'session.inp', '-exit_after_playback',
               '-seconds_to_run', str(args.seconds), '-autoboot_delay', '0',
               '-autoboot_script', str(out/'observe.lua')]
    for flag, directory in (('cfg', 'cfg'), ('nvram', 'nvram'), ('state', 'state'), ('snapshot', 'snap')):
        command += ['-'+flag+'_directory', str(work/directory)]
    (out/'command.json').write_text(json.dumps(command, indent=2)+'\n')
    inputs = [args.elf, args.session/'session.inp', args.session/'wolf-hd.po', Path(mame_kit.BINARY)]
    inputs += sorted((args.session/'cfg').glob('*'))
    if args.wall_palette:
        inputs += [args.wall_palette, args.wall_assets/'art-index.bin', args.wall_assets/'art-tables.bin']
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    env = dict(os.environ, SDL_MAC_BACKGROUND_APP='1', SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
    with (out/'mame.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
        try:
            code = process.wait(timeout=600)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert code == 0, code
    log = (out/'mame.log').read_text()
    assert 'CAPTURE_ERROR' not in log and 'Lua error' not in log and '[LUA ERROR]' not in log
    assert 'PACING_PHASE' in log and 'Total playback frames:' in log, log[-3000:]
    (out/'receipt.json').write_text(json.dumps(dict(hashes=hashes, world_records=(out/'world.bin').stat().st_size//8706), indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
