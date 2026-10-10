"""Observe original menu/score/game and aborted-demo song transitions."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

import music_capture
import floor_capture
import test_media
from elf import read

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--abort-demo', action='store_true')
    ap.add_argument('--name', required=True)
    ap.add_argument('--floppy', action='store_true', help='one drive with native song/menu disk prompts')
    args = ap.parse_args()
    out = ROOT/'build/tests'/args.name
    out.mkdir(parents=True, exist_ok=True)
    _, symbols=read(ROOT/'build/wolf.elf')
    observer=music_capture.lua()
    media=['--hd']
    if args.floppy:
        _, swaps=test_media.prepare(ROOT/'build/disk1.po', out, drives=1)
        observer+='\nlocal s=mem\n'+swaps+'''
local menuNeedsDisk=false
menuDiskTap=mem:install_read_tap(%d,%d,"menu-disk",function(a,d,m) if cpu.state.PB.value==0x3f then menuNeedsDisk=true end end)
menuFoundTap=mem:install_read_tap(%d,%d,"menu-found",function(a,d,m) if cpu.state.PB.value==0x3f then menuNeedsDisk=false end end)
emu.register_frame_done(function()
 if menuNeedsDisk then
  local drive=manager.machine.images[":fdc:2:35dd"]
  if not drive.exists then drive:load(%s);print("MENU_DISK1") end
 end
end)
''' % (symbols['needWait'],symbols['needWait'],symbols['needDone'],symbols['needDone'],json.dumps(str(out/'disk1.po')))
        media=[]
    if not args.abort_demo:
        # SCREEN_ID 0 precedes setView. viewShown also returns without publication
        # while screenHold keeps the loading/menu picture live; wait for release.
        assets=floor_capture.lua(out, floor=0, trigger=symbols['viewShown'], value=0)
        assets=assets.replace('install_write_tap', 'install_read_tap')
        assets=assets.replace('if d~=0 or ', 'if ')
        assets=assets.replace(' or assetsChecked', ' or not menuAssetsPending')
        assets=assets.replace('if assetsChecked', 'if not menuAssetsPending')
        assets=assets.replace('  assetsChecked=true', '  menuAssetsPending=false')
        assets=assets.replace('  if not menuAssetsPending',
            '  if manager.machine:side_effects_disabled() or cpu.state.PB.value~=2 then return end\n'
            '  if s:read_u16(%d)~=3 then return end\n'
            '  if s:read_u16(%d)~=0 then\n'
            '   if menuAssetsPending then print("ASSETS_HELD_VIEW"); menuHeldViews=menuHeldViews+1 end\n'
            '   return\n  end\n'
            '  if s:read_u16(%d)~=0 then return end\n  if not menuAssetsPending'
            % (symbols['currentSong'], symbols['screenHold'], symbols['palHold']))
        observer+='''
local s=mem
local menuAssetsPending=false
local menuHeldViews=0
menuAssetsTap=s:install_write_tap(0x3e4,0x3e4,"menu-assets-pending",function(a,d,m)
 if d==0 then menuAssetsPending=true end
end)
'''+assets
    (out/'observe.lua').write_text(observer)
    if args.abort_demo:
        # A title demo has no live game: Escape returns its main menu to title.
        steps = ['wait=13','sleep=1','key=Esc','wait=2','sleep=0.4','key=Esc',
                 'wait=1','sleep=1','snap=title-again','end=']
        expected = [7,3,7]
    else:
        steps = ['wait=1','sleep=1','key=Return','wait=2','sleep=0.4','key=Return','wait=15','sleep=0.4','key=Return','wait=3','sleep=0.4','key=Return',
                 'wait=0','sleep=1','key=Esc','wait=2','sleep=0.4']+['key=Down']*4
        steps += ['key=Return','wait=6','sleep=1','snap=scores','key=Esc','wait=2','sleep=0.4',
                  'key=Esc','wait=0','sleep=1','snap=game-again','end=']
        expected = [7,3]
    subprocess.run([sys.executable,'tools/ui_test.py','--name',args.name,*media,
                    '--seconds','600','--steps',';'.join(steps),
                    '--lua',str(out/'observe.lua')], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    log = (out/'mame.log').read_text()
    songs = music_capture.events(log)
    assert [s['song'] for s in songs] == expected, songs
    if not args.abort_demo:
        assert 'ASSETS_HELD_VIEW' in log, 'held new-game view was not observed'
        assert re.findall(r'^ASSETS_DONE (\d+)$',log,re.M)==['0','0'],log[-3000:]
    disk=ROOT/('build/disk1.po' if args.floppy else 'build/wolf-hd.po')
    result = dict(disk_sha256=hashlib.sha256(disk.read_bytes()).hexdigest(),floppy=args.floppy,
                  abort_demo=args.abort_demo, expected=expected, song_starts=songs,
                  held_view_skips=log.count("ASSETS_HELD_VIEW") if not args.abort_demo else None,
                  published_asset_checks=len(re.findall(r"^ASSETS_DONE (\d+)$",log,re.M)) if not args.abort_demo else None,
                  glu_violations=0, asset_differences=0 if not args.abort_demo else None,method=__doc__)
    (out/'songs.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
