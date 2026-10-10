"""Bounded capture of a recorded native MAME input session.

Uses private copies of media/configuration; does not inject game state or
change the recording. Screen, ray arrays and light choices are retained.
An explicit --wall-palette swaps only expanded wall art before the first
game frame, for a controlled same-executable diagnosis (not a media test).
"""
import memmap
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
from elf import read
import lua_guard
import mame_kit
import test_media


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--release',type=Path,required=True)
    ap.add_argument('--inp',type=Path,required=True)
    ap.add_argument('--seconds',type=int,default=120)
    ap.add_argument('--start',type=float,default=0)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--wall-palette',type=Path)
    ap.add_argument('--wall-assets',type=Path,default=Path('build/levels/0'))
    args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    for n in ('cfg','nvram','snap','state'):(out/n).mkdir()
    original_cfg=args.inp.parent/'cfg/apple2gsr1.cfg'
    if original_cfg.exists():shutil.copyfile(original_cfg,out/'cfg/apple2gsr1.cfg')
    shutil.copyfile(args.inp,out/'session.inp')
    media,_=test_media.prepare(args.release/'wolf-hd.po',out)
    _,s=read(args.release/'wolf.elf')
    names=('viewWidth','heightIndex','sourceAddr','sourceBank','hitPlane','lightCB','levelIndex','levelState','castPX','castPY','castAngle','health')
    symbols={n:s[n]for n in names}
    script='local A='+ '{'+','.join(f'{n}={v}'for n,v in symbols.items())+'}\n'
    replacement=''
    if args.wall_palette:
        palette=json.loads(args.wall_palette.read_text())
        units=struct.unpack_from('<H',(args.wall_assets/'art-tables.bin').read_bytes())[0]
        index=(args.wall_assets/'art-index.bin').read_bytes()[:units*64]
        for light in range(3):
            name=f'wall-light-{light}.bin'
            (out/name).write_bytes(b''.join(bytes(palette['wall_lights'][light][c]) for c in index))
            replacement+=f' local f=assert(io.open(output.."/{name}","rb"));local data=f:read("*a");f:close()\n'
            replacement+=f' for i=1,#data,2 do s:write_u16({memmap.ART_BASE+light*memmap.ART_BYTES}+i-1,string.unpack("<I2",data,i))end\n'
    script+=memmap.fill(r'''
local cpu=manager.machine.devices[":maincpu"]
local s=cpu.spaces["program"]
local output=@OUT@
local pixels=assert(io.open(output.."/frames.shr","wb"))
local rays=assert(io.open(output.."/rays.bin","wb"))
local states=assert(io.open(output.."/states.jsonl","w"))
local frame=0
local replacementPending=@REPLACE_PENDING@
local function bytes(base,n)
 local out={};for i=0,n-1,4 do out[#out+1]=string.pack("<I4",s:read_u32(base+i)) end
 return table.concat(out)
end
for _,name in ipairs({"a2_config","bus_timing","ram_start","ram_seed"})do
 local port=manager.machine.ioport.ports[":"..name];if port then print("SETTING "..name.." "..port:read())end
end
frameTap=s:install_write_tap(0x3f0,0x3f0,"capture",function(addr,d,m)
 local time=manager.machine.time:as_double()
 if d==1 and replacementPending then
  assert(s:read_u16(A.levelIndex)==0,"wall replacement requires floor 1")
@REPLACE@
  replacementPending=false;print("WALL_REPLACEMENT "..time)
 end
 if d~=2 or time<@START@ then return end
 frame=frame+1
 pixels:write(bytes(@MM:SHR@,32768))
 local width=s:read_u16(A.viewWidth)
 local rows={}
 for _,n in ipairs({"heightIndex","hitPlane","sourceAddr","sourceBank"})do
  for i=0,159 do rows[#rows+1]=string.pack("<I2",s:read_u16(A[n]+2*i))end
 end
 for i=0,159 do local h=s:read_u16(A.heightIndex+2*i);rows[#rows+1]=string.pack("<I2",s:read_u16(A.lightCB+h))end
 rays:write(table.concat(rows))
 states:write(string.format('{"frame":%d,"time":%.9f,"width":%d,"floor":%d,"level_state":%d,"x":%d,"y":%d,"angle":%d,"health":%d}\n',frame,time,width,s:read_u16(A.levelIndex),s:read_u16(A.levelState),s:read_u16(A.castPX),s:read_u16(A.castPY),s:read_u16(A.castAngle),s:read_u16(A.health)))
 if frame%100==0 then print("CAPTURE "..frame.." "..time);io.stdout:flush();states:flush()end
end)
emu.register_frame_done(function()
 if manager.machine.time:as_double()>=@SECONDS@ then manager.machine:exit()end
end)
captureStop=emu.add_machine_stop_notifier(function()
 pixels:close();rays:close();states:close();print("CAPTURE_DONE "..frame);io.stdout:flush()
end)
''')
    script=script.replace('@OUT@',json.dumps(str(out))).replace('@SECONDS@',str(args.seconds)).replace('@START@',str(args.start))
    script=script.replace('@REPLACE_PENDING@','true' if args.wall_palette else 'false').replace('@REPLACE@',replacement)
    lua_guard.write(out/'capture.lua',script)
    cmd=['nice','-n','20',mame_kit.BINARY,'apple2gsr1','-rompath',mame_kit.ROMPATH,'-ramsize','4352K',*media,'-input_directory',str(out),'-playback','session.inp','-video','none','-sound','none','-nothrottle','-skip_gameinfo','-seconds_to_run',str(args.seconds+2),'-autoboot_delay','0','-autoboot_script',str(out/'capture.lua'),'-cfg_directory',str(out/'cfg'),'-nvram_directory',str(out/'nvram'),'-state_directory',str(out/'state'),'-snapshot_directory',str(out/'snap')]
    (out/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
    env=dict(os.environ,SDL_MAC_BACKGROUND_APP='1',SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy')
    with (out/'mame.log').open('w')as log:
        p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=env)
        try:code=p.wait(timeout=max(90,args.seconds*2))
        finally:
            if p.poll()is None:p.kill();p.wait()
    if code:raise SystemExit(f'MAME exited {code}; see {out}/mame.log')
    inputs=[args.release/'wolf.elf',args.release/'wolf-hd.po',args.inp]
    if args.wall_palette:inputs.extend([args.wall_palette,args.wall_assets/'art-index.bin',args.wall_assets/'art-tables.bin'])
    (out/'receipt.json').write_text(json.dumps(dict(release=str(args.release),inp=str(args.inp),seconds=args.seconds,start=args.start,symbols=symbols,wall_palette=str(args.wall_palette) if args.wall_palette else None,hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in inputs}),indent=2)+'\n')
    print(out)


if __name__=='__main__':main()
