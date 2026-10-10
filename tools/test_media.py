"""Private test media and prompt-driven floppy changes for bounded MAME runs."""
import memmap
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def private_copy(source, target):
    """Keep emulator writes private while sharing unchanged APFS extents."""
    if sys.platform == 'darwin' and not Path(target).exists():
        copied = subprocess.run(['/bin/cp', '-c', str(source), str(target)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if copied.returncode == 0:
            return
    shutil.copyfile(source, target)


def prepare(disk, out, disk2=None, drives=2):
    disk = Path(disk).resolve()
    if drives not in (1, 2):
        raise ValueError('one or two floppy drives required')
    target = out / disk.name
    private_copy(disk, target)
    files = [target]
    if disk.stat().st_size > 800 * 1024:
        args = ['-sl7', 'cffa3000', '-hard1', str(target)]
        script = ''
        header = disk.read_bytes()[512:1024]
        if header[:6] == b'WOLFGS' and header[7] == 2:
            source = Path(disk2) if disk2 else disk.with_name(disk.stem+'2'+disk.suffix)
            other = source.read_bytes()[512:1024]
            if (other[:8] != b'WOLFGS\x02\x02' or other[432:436] != header[432:436]
                    or other[368:432] != header[368:432]):
                raise ValueError('supplemental hard disk does not match the boot volume')
            target = out/source.name
            private_copy(source, target)
            files.append(target)
            args += ['-hard2', str(target)]
    else:
        count = disk.read_bytes()[512 + 7]
        if not 1 <= count <= 8:
            raise ValueError('invalid Wolf disk-set header')
        for n in range(2, count + 1):
            source = Path(disk2) if n == 2 and disk2 else disk.with_name('disk%d.po' % n)
            target = out / ('disk%d.po' % n)
            private_copy(source, target)
            files.append(target)
        args = ['-flop3', str(files[0])]
        if drives == 2 and count > 1:
            args += ['-flop4', str(files[1])]
        script = SWAP.replace('@DISKS@', ','.join(json.dumps(str(f)) for f in files))
        # New signs no longer write the boot strip/text screen; observe their request.
        from elf import read
        _, symbols = read(Path(__file__).resolve().parents[1]/'build/wolf.elf')
        prompt = symbols.get('UiDiskPrompt')
        observer = 'local runtimeWanted=nil\n'
        if prompt is not None:
            observer += '''runtimePromptTap=s:install_read_tap(%d,%d,"runtime-disk-prompt",function(a,d,m)
 local c=manager.machine.devices[":maincpu"]
 if c.state.PC.value==a+1 then
  local n=c.state.A.value&65535;runtimeWanted=n~=0 and n or nil
 end
end)
''' % (prompt,prompt)
        script = observer+script
    (out / 'media.json').write_text(json.dumps([
        dict(file=str(f), sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files
    ], indent=2) + '\n')
    return args, script


# Prompt/drive discovery follows the team's tools/probe.lua; see NOTICE.
SWAP = memmap.fill(r'''
local swapDisks={@DISKS@}
local swapAsked,swapSince,swapInserted=nil,nil,nil
emu.register_frame_done(function()
  local wanted=runtimeWanted
  if not wanted then
  for _,base in ipairs({@MM:DISK_PROMPT_00@,@MM:DISK_PROMPT@}) do
    local prompt=""
    for i=0,12 do prompt=prompt..string.char(s:read_u8(base+i)&127) end
    wanted=tonumber(prompt:match("^INSERT DISK (%d)$"))
    if wanted then break end
  end
  end
  if not wanted then swapAsked=nil; swapSince=nil; swapInserted=nil; return end
  if not swapDisks[wanted] then return end
  local now=manager.machine.time:as_double()
  if wanted~=swapAsked then swapAsked=wanted; swapSince=now; swapInserted=nil end
  for tag,img in pairs(manager.machine.images) do
    -- Firmware can finish ejecting after the observer's first insertion.
    if tag:find("35dd") and tag:find("fdc:2") and (not img.exists or (swapInserted~=wanted and now-swapSince>=2)) then
      print(string.format("INSERT %.6f disk %d",now,wanted)); io.stdout:flush()
      img:load(swapDisks[wanted]); swapInserted=wanted; return
    end
  end
end)
''')
