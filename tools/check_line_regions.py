"""Check empty-region geometry and native moving-wall occupancy counts."""
import memmap
import json
import random
import struct
from check_sight_ratio import ROOT,check_native
from buildconfig import config
from line_regions import encode
from wolfsim import Game,Obj


def main():
    rng=random.Random(65816)
    floors=[]
    for floor in range(10):
        game=Game(floor)
        packed,ids,rectangles=encode(game.tilemap)
        native=(ROOT/f'build/levels/{floor}/logic.bin').read_bytes()[0xfc00:]
        assert native==packed
        assert all(Game(floor,difficulty=skill).tilemap==game.tilemap for skill in range(3))
        ob=Obj(1)
        for x0,x1,y0,y1 in rectangles:
            for _ in range(1000):
                ob.x=rng.randrange(x0*256,(x1+1)*256)*256
                ob.y=rng.randrange(y0*256,(y1+1)*256)*256
                game.plux=rng.randrange(x0*256,(x1+1)*256)
                game.pluy=rng.randrange(y0*256,(y1+1)*256)
                game.player.tilex=game.plux>>8;game.player.tiley=game.pluy>>8
                assert game.check_line(ob),(floor,ob.x,ob.y,game.plux,game.pluy)
        floors.append(dict(floor=floor,rectangles=len(rectangles),open_cells=sum(bool(n) for n in ids),cases=len(rectangles)*1000))
    game=Game(config()['floor']-1)
    _,ids,_=encode(game.tilemap)
    first,second=[i for i,n in enumerate(ids) if n==1][:2]
    records=[]
    for tile in range(1,256):
        for value,cell,count in ((1,first,1),(tile,first,1),(tile,second,2),(0,first,1),(0,second,0)):
            records.append(struct.pack('<3H',value,cell,count))
    report=check_native('line-regions-native',records,'StoreLogicTile',0x118a,x_dp=0x8a,output_field=(memmap.OLD_VISIBILITY+0xedae))
    restored=[struct.pack('<3H',value,cell,count) for value,cell,count in
              ((1,first,1),(255,first,1),(192,second,2),(0,first,1),(0,second,0))]
    report['restored_map']=check_native('line-regions-restored',restored,'RecountLineRegions',0x118a,
                                      x_dp=0x8a,output_field=(memmap.OLD_VISIBILITY+0xedae),byte_store=memmap.OLD_WORLD,long_entry=True)
    report.update(floors=floors,source_cases=sum(f['cases'] for f in floors),difficulty_invariance=True,
                  checks='exact source sight inside rectangles; every nonzero wall byte; occupied-to-occupied writes; re-enable only after the last wall leaves')
    (ROOT/'build/tests/line-regions-native/result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
