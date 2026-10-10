"""Compare weapon bounds with DOS SimpleScaleShape at each view size."""
import json
from pathlib import Path

from wolfdata import ROOT, vswap, sprite
from wolf_source import sprite_ids
from viewgeometry import SIZES, weapon_height


def bounds(points):
    return (min(x for x,y in points),min(y for x,y in points),
            max(x for x,y in points)+1,max(y for x,y in points)+1)


def main():
    pages,base,_=vswap();ids=sprite_ids()
    packed=json.loads((ROOT/'build/assets/sprites.json').read_text())
    reports=[]
    for rows in SIZES:
        h=weapon_height(rows);top=(160-rows)//2;bottom=top+rows
        full_top=80-h//2
        for name in ('KNIFE','PISTOL','MACHINEGUN','CHAIN'):
            n=ids['SPR_'+name+'READY'];art=sprite(pages[base+n])
            native=packed[str(n)]
            for x,col in enumerate(art['columns'],art['left']):
                assert [(a,b) for a,b,_ in col]==[(a,b) for a,b,_ in native['columns'][x]], 'weapon art was rescaled'
            original=set();left=rows-h//2
            for x,col in enumerate(art['columns'],art['left']):
                for a,b,_ in col:
                    for y in range(max(top,full_top+a*h//64),min(bottom,full_top+b*h//64)):
                        for px in range(left+x*h//64,left+(x+1)*h//64):original.add((px,y))
            actual=set();width=h//2;left=(rows-width)//2
            for x in range(left,left+width):
                u=(x-left)*64//width
                for a,b,_ in native['columns'][u]:
                    for y in range(max(top,full_top+(a*h+63)//64),min(bottom,full_top+(b*h+63)//64)):
                        actual.update(((2*x,y),(2*x+1,y)))
            a,b=bounds(actual),bounds(original)
            assert max(abs(x-y) for x,y in zip(a,b))<=2, (rows,name,a,b)
            reports.append(dict(view_rows=rows,weapon=name,native_bounds=a,dos_bounds=b,
                                native_size=[a[2]-a[0],a[3]-a[1]],dos_size=[b[2]-b[0],b[3]-b[1]]))
    out=ROOT/'build/tests/rewrite-weapon';out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps([r for r in reports if r['weapon']=='PISTOL']))


if __name__=='__main__':main()
