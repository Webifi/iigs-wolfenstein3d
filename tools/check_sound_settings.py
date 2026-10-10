"""Exercise real audio keys, explicit persistence and silent music on stock IIgs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from elf import read
import mame_kit

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--label',default='sound-settings');args=ap.parse_args();LABEL=args.label
OUT=ROOT/'build/tests'/(LABEL+'-cases')
OUT.mkdir(parents=True,exist_ok=True)
_,symbols=read(ROOT/'build/wolf.elf')
assert symbols['SaveAudioSettings']<0x10000,'firmware must return in bank 0'

def copy_disks(name):
    folder=OUT/name;folder.mkdir(exist_ok=True)
    for item in ('disk1.po','disk2.po','disk3.po','disk4.po','disk5.po'):
        if (ROOT/'build'/item).exists():shutil.copyfile(ROOT/'build'/item,folder/item)
    return folder

def run(name,folder,plan,end,insert=False):
    path=folder/(name+'.json');path.write_text(json.dumps(plan)+'\n')
    cmd=[sys.executable,'tools/playtest.py','--name',name,'--disk',str(folder/'disk1.po'),
         '--plan',str(path),'--end',str(end),'--settings-audit','--sound-audit']
    if insert:cmd+=['--reinsert-settings-disk']
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=100)
    if p.returncode:raise AssertionError(p.stdout[-2400:]+p.stderr[-2400:])
    log=(ROOT/'build/tests'/name/'mame.log').read_text()
    rows=[(float(t),*map(int,(fx,music,active,loaded,status))) for t,fx,music,active,loaded,status in
          re.findall(r'^AUDIOSETTING ([\d.]+) (\d+) (\d+) (\d+) (\d+) (\d+)',log,re.M)]
    assert rows and 'SOUNDVIOLATION' not in log
    return rows,log

def save():
    folder=copy_disks('save');before=(folder/'disk1.po').read_bytes()
    rows,log=run(LABEL+'-save',folder,[[2,2.2,['n  N']],[3,3.2,['b  B']],[5,5.2,['k  K']]],10,True)
    assert rows[-1][1:]==(14,14,1,1,0),rows[-1]
    after=(folder/'disk1.po').read_bytes()
    block=struct.unpack_from('<H',before,512+436)[0];offset=block*512+496
    assert before[:offset]==after[:offset] and before[offset+16:]==after[offset+16:]
    assert struct.unpack_from('<4sHH',after,offset)==(b'WSD1',0x0e0e,0x0e0e^0xa55a)
    assert any(r[-1]==65535 and r[1:3]==(14,14) for r in rows), 'changes must stay unsaved before K'
    return folder,dict(record_offset=offset,record_hex=after[offset:offset+16].hex(),only_record_changed=True)

def off():
    folder=copy_disks('off');before=(folder/'disk1.po').read_bytes()
    plan=[]
    for i in range(15):plan.append([2+i*.5,2.2+i*.5,['n  N']])
    for i in range(15):plan.append([10+i*.6,10.2+i*.6,['b  B']])
    plan += [[21,21.2,['n  N']],[22,22.2,['b  B']],[25,25.2,['m  M']],[26,26.2,['v  V']]]
    rows,log=run(LABEL+'-off',folder,plan,29)
    assert all(r[1:]==(0,0,0,1,65535) for r in rows if 20<r[0]<24)
    origin=float(re.search(r'^READY ([\d.]+)',log,re.M)[1])
    wakes=[float(t)-origin for t in re.findall(r'^MUSICWAKE ([\d.]+)',log,re.M)]
    assert not any(10<t<24 for t in wakes),wakes[-10:]
    gaps=[b-a for a,b in zip(wakes,wakes[1:]) if 1<a<b<8.3]
    assert max(gaps)<.22,('volume change blocked music',max(gaps))
    transfers=[float(t)-origin for t in re.findall(r'^AUDIODATA ([\d.]+)',log,re.M)]
    assert transfers and not any(20<t<24 for t in transfers)
    cursors=[int(c) for t,c in re.findall(r'^AUDIOCURSOR ([\d.]+) (\d+)',log,re.M) if 20<float(t)<24]
    assert cursors and len(set(cursors))==1
    assert rows[-1][1:]==(1,1,1,1,65535),rows[-1]
    assert (folder/'disk1.po').read_bytes()==before,'changing volume saved without a request'
    return dict(silent_interval_seconds=[10,24],music_wakes_while_off=0,doc_data_writes_while_both_off=0,music_cursor_stopped=True,max_alarm_gap_during_volume_changes=max(gaps),volume_keys_save_nothing=True,restart_levels=[1,1])

with ThreadPoolExecutor(max_workers=1) as pool:
    a=pool.submit(save);b=pool.submit(off)
    folder,saved=a.result();silent=b.result()
def reload_saved():
    rows,_=run(LABEL+'-reload',folder,[],2)
    assert rows[0][1:]==(14,14,1,1,65535),rows[0]
    return list(rows[0][1:3])

def cold_off():
    quiet=copy_disks('quiet');path=quiet/'disk1.po';data=bytearray(path.read_bytes())
    block=struct.unpack_from('<H',data,512+436)[0]
    struct.pack_into('<4sHH8x',data,block*512+496,b'WSD1',0,0xa55a)
    path.write_bytes(data)
    rows,log=run(LABEL+'-cold-off',quiet,[],2)
    assert rows[0][1:]==(0,0,0,0,65535),rows[0]
    assert 'MUSICWAKE' not in log and 'MUSICNOTE' not in log
    return dict(music_loaded=False,music_wakes=0,levels=[0,0])

with ThreadPoolExecutor(max_workers=1) as pool:
    a=pool.submit(reload_saved);b=pool.submit(cold_off)
    reloaded=a.result();cold=b.result()
report=dict(saved=saved,silent=silent,reloaded_levels=reloaded,cold_off=cold,
            mame=mame_kit.NAME,
            disk_sha256=hashlib.sha256((ROOT/'build/disk1.po').read_bytes()).hexdigest())
(ROOT/'docs/evidence/sound'/('settings.json' if LABEL=='sound-settings' else LABEL+'.json')).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
