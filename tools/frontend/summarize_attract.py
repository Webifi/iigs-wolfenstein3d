"""Summarize an existing check_attract_transition run; never launch MAME."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import memmap
import argparse
import json
from pathlib import Path
import re
import statistics


def summarize(directory):
    log = (directory/'mame.log').read_text()
    identity = json.loads((directory/'result.json').read_text())
    paints = {int(n):float(t)*1000 for n,t in re.findall(r'^FIGHT_PAINT (\d+) ([\d.]+)$',log,re.M)}
    fine = {int(n):[float(x)*1000 for x in parts] for n,*parts in
            re.findall(r'^FIGHT_LOGIC (\d+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)$',log,re.M)}
    frames, previous = [], 0
    for number,packet,*parts in re.findall(r'^FIGHT_FRAME (\d+) (\d+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)$',log,re.M):
        frame = dict(frame=int(number),packet=int(packet),packets_this_frame=int(packet)-previous,
                     **dict(zip(('total_ms','logic_ms','publish_ms','render_cast_ms','sprite_prepare_ms'),
                                [float(x)*1000 for x in parts])),paint_ms=paints[int(number)])
        if int(number) in fine:
            frame.update(zip(('world_ms','visibility_ms','statics_ms','actors_ms'),fine[int(number)]))
        frames.append(frame)
        previous = int(packet)

    def group(rows):
        assert rows
        return dict(frames=len(rows),mean={k:statistics.mean(f[k] for f in rows)
                    for k in rows[0] if k not in ('frame','packet')},worst=max(rows,key=lambda f:f['total_ms']))

    transitions = [(float(t),tag) for t,tag in re.findall(r'^TRANSITION ([\d.]+) ([\w-]+)$',log,re.M)]
    starts = [t for t,tag in transitions if tag=='loading-begin']
    ends = [t for t,tag in transitions if tag=='demo-ready']
    visible = [t for t,tag in transitions if tag=='loading-visible']
    loads = []
    for i,(start,end) in enumerate(zip(starts,ends)):
        first = next((t for t in visible if start<=t<=end),None)
        loads.append(dict(demo=i+1,seconds=end-start,visible_after_seconds=None if first is None else first-start))
    report = dict(run=directory.name,default_view_pixels=214,
                  source='Stock MAME automatic cold boot; read-only diagnostic phase observations.',
                  note='Frame work excludes waiting for the next due packet. Phase times include interrupts occurring in that phase.',
                  slowest20=group(sorted(frames,key=lambda f:f['total_ms'],reverse=True)[:20]),
                  crowded=group([f for f in frames if 800<=f['packet']<=980]),loads=loads,
                  elf_sha256=identity['elf_sha256'],disk_sha256=identity['disk_sha256'])
    profile = directory/'profile.txt'
    if profile.exists():
        counters = [(int(address,16),int(units)) for address,units in
                    (line.split() for line in profile.read_text().splitlines())]
        report['pc_profile_seconds'] = sum(t for _,t in counters)*66/15120000000
        report['generated_scaler_seconds'] = sum(t for pc,t in counters if memmap.SCALE3<=pc<memmap.WORD_PRODUCTS)*66/15120000000
        report['pc_profile_note'] = ('Time counters include interrupts and idle; low-bank bins are 16 bytes, '
                                     'high-bank bins are 256 bytes. Each bin can contain several functions. '
                                     'Generated scaler banks are $03-$05.')
    return report


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args = parser.parse_args()
    report = summarize(args.directory)
    (args.directory/'phase-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
