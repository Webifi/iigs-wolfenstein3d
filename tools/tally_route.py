"""Check the merged exact-logic tally after native menu floor loading.

The private disk carries a stat-only checkpoint; the later world restore is
bypassed by the loader fixture (complete saves use check_saved_world.py). A named fixture places the
player beside the switch, isolates actors and sets counts/score; floor art,
planes, the use command, tally arithmetic and score awards run natively.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from elf import read
import memmap
from floor_check import checkpoint, checkpoint_lua

ROOT = Path(__file__).resolve().parents[1]

LUA = r'''
local s=mem
local prepared,reported=false,false
local vars=@VARS@
local function u32(a) return s:read_u16(a)+s:read_u16(a+2)*65536 end
local function put32(a,v) s:write_u16(a,v&65535);s:write_u16(a+2,v>>16) end
local function game(n) return vars[n] end
fixtureTap=s:install_write_tap(0x3f0,0x3f0,"tally-fixture",function(a,d,m)
  if d==1 and not prepared then
    prepared=true
    put32(@PX@,@X@);put32(@PY@,@Y@)
    s:write_u16(@TX@,@X@>>16);s:write_u16(@TY@,@Y@>>16)
    s:write_u16(@ANGLE@,@DEG@);s:write_u16(@NEXTACTOR@,0)
    s:write_u16(game("killcount"),4);s:write_u16(game("killtotal"),4)
    s:write_u16(game("secretcount"),0);s:write_u16(game("secrettotal"),2)
    s:write_u16(game("treasurecount"),1);s:write_u16(game("treasuretotal"),2)
    put32(game("score"),35000);put32(game("nextextra"),40000)
    s:write_u16(game("lives"),3)
    s:write_u8(0x3e0,16)
  elseif d==2 and prepared then
    s:write_u8(0x3e0,0)
    if s:read_u16(@FLOW@)==3 and not reported then
      reported=true
      print(string.format('TALLY {"bonus":%d,"kill":%d,"secret":%d,"treasure":%d,"seconds":%d,"left":%d,"par":%d,"score":%d,"lives":%d,"next":%d,"music":%d,"phase":%d}',
        u32(@BONUS@),s:read_u16(@KR@),s:read_u16(@SR@),s:read_u16(@TR@),s:read_u16(@SEC@),s:read_u16(@LEFT@),s:read_u16(@PAR@),
        u32(game("score")),s:read_u16(game("lives")),s:read_u16(@NEXT@),s:read_u16(@MUSIC@),s:read_u16(@FLOW@)))
    end
  end
end)
'''


def main():
    _, symbols = read(ROOT/'build/wolf.elf')
    logic = json.loads((ROOT/'build/assets/logic.json').read_text())
    layout, fields = logic['layout'], logic['fields']
    variables = {n:memmap.WORLD+layout['VARS']+2*i for i,n in enumerate(logic['vars'])}
    player = memmap.WORLD+layout['OBJLIST']
    source = ROOT/'build/wolf-hd.po'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    results = []
    for floor, x, y, angle in [(0,6528,12160,0),(9,45*256+128,11*256+128,180)]:
        name = 'tally-exact-%d'%floor
        out = ROOT/'build/tests'/name
        out.mkdir(parents=True,exist_ok=True)
        disk = checkpoint(source,out,floor)
        table = '{'+','.join('[%s]=%d'%(json.dumps(n),v) for n,v in variables.items())+'}'
        script = LUA.replace('@VARS@',table)
        tokens = dict(X=x*256,Y=y*256,DEG=angle)
        for token,field in [('PX','O_X'),('PY','O_Y'),('TX','O_TILEX'),('TY','O_TILEY'),('ANGLE','O_ANGLE'),('NEXTACTOR','O_NEXT')]:
            tokens[token] = player+fields[field]
        for token,name_ in [('FLOW','flowPhase'),('BONUS','tallyBonus'),('KR','tallyKill'),('SR','tallySecret'),('TR','tallyTreasure'),('SEC','tallySec'),('LEFT','tallyLeft'),('PAR','tallyPar'),('NEXT','nextFloor'),('MUSIC','musicRequest')]:
            tokens[token] = symbols[name_]
        for name_,value in tokens.items():
            script = script.replace('@'+name_+'@',str(value))
        assert '@' not in script
        fixture = out/'fixture.lua'
        fixture.write_text(checkpoint_lua()+script)
        command = [sys.executable,str(ROOT/'tools/ui_test.py'),'--name',name,'--disk',str(disk),'--hd','--lua',str(fixture),
                   '--seconds','200','--steps',
                   'wait=1;sleep=1;key=Esc;wait=2;sleep=0.4;key=Down;key=Return;wait=4;sleep=0.4;key=Return;wait=0;waitmem=%d,3;sleep=0.1;snap=tally;end='%symbols['flowPhase']]
        proc = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=540)
        (out/'driver.log').write_text(proc.stdout+proc.stderr)
        if proc.returncode:
            raise RuntimeError('Tally route failed; see '+str(out/'driver.log'))
        log = (out/'mame.log').read_text()
        rows = re.findall(r'^TALLY (.*)$',log,re.M)
        assert len(rows)==1, 'missing tally at '+str(out)
        row = json.loads(rows[0])
        bonus = 15000 if floor==9 else max(0,90-row['seconds'])*500+10000
        assert row['bonus']==bonus and row['score']==35000+bonus, row
        assert row['lives']==3+(35000+bonus)//40000, row
        assert (row['kill'],row['secret'],row['treasure'])==(100,0,50), row
        assert row['next']==1 and row['music']==16 and row['phase']==3, row
        if floor==0:
            assert row['par']==90 and row['left']==max(0,90-row['seconds']),row
        results.append(dict(floor=floor,result=row))
        print('floor',floor,row,flush=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
    result = dict(disk_sha256=source_hash,method=__doc__,cases=results)
    target = ROOT/'build/tests/tally-exact.json'
    target.write_text(json.dumps(result,indent=2)+'\n')
    print('Evidence:',target)


if __name__=='__main__':
    main()
