"""Check tabled and fallback shooting chances against integer division."""
import memmap
import json
import re
import struct
from check_sight_ratio import ROOT,check_native


def main():
    tics=(0,1,2,3,4,5,7,64,255,4095,4096,65535)
    records=[struct.pack('<3H',distance,t,((t*16)&65535)//distance)
             for t in tics for distance in range(1,256)]
    definitions={k:int(v,0) for k,v in re.findall(r'^(V_\w+)\s+\.equ\s+(\S+)',(ROOT/'build/gen/logic.inc').read_text(),re.M)}
    report=check_native('chase-chance-native',records,'chanceByDist',memmap.OLD_WORLD+definitions['V_tics'],patches=('chanceSet',),input_field=0x114e)
    report.update(tics=tics,distances=255,checks='one/four-tic tables and generic wrapped-word division')
    (ROOT/'build/tests/chase-chance-native/result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
