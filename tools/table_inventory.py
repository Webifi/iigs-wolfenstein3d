"""Audit executed arithmetic beside stock PC-time samples, not fetch taps."""
import memmap
import argparse
import bisect
import csv
import json
import re
from pathlib import Path
from elf import read

ROOT=Path(__file__).resolve().parents[1]
SCENES=('turn','walk','guards','fight')
COLUMNS=('entries','instructions','multiply_calls','table_product_calls','divide_calls','shifts','compares','indexed_reads')


def inventory(elf,profile_prefix,count_prefix):
    _,symbols=read(elf)
    labels=sorted((a,n) for n,a in symbols.items() if memmap.SW_SEG_CODE<=a<memmap.WORD_PRODUCTS)
    addresses=[a for a,n in labels]
    by_addr={a:n for a,n in labels}
    samples={};selected=set()
    for scene in SCENES:
        times=json.loads((Path(str(profile_prefix)+scene)/'profile.json').read_text())
        total=sum(times.values())
        hot={n for n,ms in times.items() if ms>=total*.005}
        selected.update(hot)
        counts=json.loads((Path(str(count_prefix)+scene)/'instruction-counts.json').read_text())
        rows={}
        for raw,item in counts.items():
            pc=int(raw,16)
            if not addresses[0]<=pc<memmap.WORD_PRODUCTS:continue
            name=labels[bisect.bisect_right(addresses,pc)-1][1]
            row=rows.setdefault(name,dict.fromkeys(COLUMNS,0))
            n=item['count'];instruction=item['instruction'].lower()
            op=instruction.split()[0]
            row['instructions']+=n
            if pc==symbols[name]:row['entries']+=n
            if op in ('asl','lsr','rol','ror','xba'):row['shifts']+=n
            if op in ('cmp','cpx','cpy','bit'):row['compares']+=n
            if op in ('lda','ldx','ldy') and re.search(r',[xy]|\[[^]]+\]',instruction):row['indexed_reads']+=n
            if op in ('jsr','jsl'):
                target=re.search(r'\$([0-9a-f]+)',instruction)
                if target:
                    address=int(target[1],16)
                    if len(target[1])<=4:address|=pc&0xff0000
                    callee=by_addr.get(address,'')
                    if callee in ('mulFrac','signedProduct'):
                        row['multiply_calls']+=n
                    if callee in ('mulLowFrac','rayPartial'):
                        row['table_product_calls']+=n
                    if 'div' in callee.lower():row['divide_calls']+=n
        samples[scene]=dict(total_ms=total,times=times,counts=rows)
    report=[]
    for name in sorted(selected):
        report.append(dict(routine=name,scenes={s:dict(ms=samples[s]['times'].get(name,0),
                           percent=100*samples[s]['times'].get(name,0)/samples[s]['total_ms'],
                           **samples[s]['counts'].get(name,dict.fromkeys(COLUMNS,0))) for s in SCENES}))
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--elf',type=Path,required=True)
    ap.add_argument('--profiles',type=Path,required=True)
    ap.add_argument('--counts',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    rows=inventory(args.elf,args.profiles,args.counts)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.with_suffix('.json').write_text(json.dumps(rows,indent=2)+'\n')
    with args.out.with_suffix('.csv').open('w',newline='') as f:
        writer=csv.writer(f,lineterminator='\n')
        writer.writerow(['routine','scene','ms','percent',*COLUMNS,'operations_per_entry'])
        for row in rows:
            for scene,data in row['scenes'].items():
                entry=data['entries']
                per='; '.join(f'{c}={data[c]/entry:.2f}' for c in COLUMNS[2:]) if entry else 'no entry in sampled frame'
                writer.writerow([row['routine'],scene,round(data['ms'],4),round(data['percent'],3),
                                 *(data[c] for c in COLUMNS),per])
    print(f'{len(rows)} labels above 0.5% in at least one sampled frame')


if __name__=='__main__':main()
