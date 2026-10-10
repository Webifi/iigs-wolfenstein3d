"""Check every hit against DOS damage, walls, closed doors and death behavior."""
import argparse,json,math
from pathlib import Path
from wolf_source import random_table,states
ap=argparse.ArgumentParser();ap.add_argument('scene',type=Path);ap.add_argument('--old',action='store_true');ap.add_argument('--game-over',action='store_true');args=ap.parse_args()
p=args.scene;data=json.loads((p/'walk.json').read_text());fail=[];hits=[];rng=random_table()
fade=data.get('fade')
if fade is not None and not args.old:
 if not fade.get('writes'):fail.append('no palette writes by the death fade')
 if fade.get('start_time') is not None:
  if fade.get('end_time') is None:fail.append('the death fade did not end')
  else:
   tics=(fade['end_clock']-fade['start_clock'])&65535
   if not 70<=tics<=82:fail.append(['the death fade did not take 70 DOC tics',tics])
   if fade.get('start_hash')!=fade.get('end_hash'):fail.append('the pixels of the view changed during the death fade')
   if fade.get('not_red'):fail.append(['palette words not at the red of Died() when the fade ended',fade['not_red']])
   if fade.get('hud_start')!=fade.get('hud_end'):fail.append('the status bar palettes changed during the death fade')
 over=fade.get('over')
 if over is not None:
  if over['other_pixels']:fail.append(['game over: pixels of the view that are not slot 2',over['other_pixels']])
  if over['red']!=0xa00:fail.append(['game over: slot 2 is not the red of Died()',over['red']])
  if over['white']!=0xfff:fail.append(['game over: slot 1 is not white',over['white']])
def line_blocker(h):
 if h.get('exact'):
  from types import SimpleNamespace
  import wolfsim
  game=wolfsim.Game.__new__(wolfsim.Game)
  game.player=SimpleNamespace(tilex=h['x']>>8,tiley=h['y']>>8)
  game.plux,game.pluy=h['x'],h['y']
  game.tilemap,game.doorposition=h['logicmap'],h['logicdoors']
  actor=SimpleNamespace(x=h['object'][0]<<8,y=h['object'][1]<<8)
  return None if game.check_line(actor) else {'source_checkline':False}
 x1,y1=h['object'][:2];x2,y2=h['x'],h['y'];grid=h['map']
 for swap in (False,True):
  a,b,c,d=(y1,x1,y2,x2) if swap else (x1,y1,x2,y2)
  start,end=a>>8,c>>8
  if start==end:continue
  direction=1 if end>start else -1;partial=256-(a&255) if direction>0 else a&255
  delta=(d-b)*256;den=abs(c-a);step=max(-32767,min(32767,(-1 if delta<0 else 1)*(abs(delta)//den)))
  frac=b+(step*partial>>8)
  for cell in range(start+direction,end+direction,direction):
   x,y=(frac>>8,cell) if swap else (cell,frac>>8);frac+=step
   value=grid[x*64+y]
   if value and (value<128 or value>=192 or h['doors'][value&127]==0):return dict(x=x,y=y,tile=value)
 return None
for h in data['hits']:
 o=h['object'];dist=max(abs(o[12]-(h['x']>>8)),abs(o[13]-(h['y']>>8)))
 if o[3] in (102,103):dist=dist*2//3
 expected=rng[h['random']]>>(2 if dist<2 else 3 if dist<4 else 4)
 if h['damage']!=expected:fail.append(['damage',h['time'],expected,h['damage']])
 blocked=line_blocker(h)
 if blocked:fail.append(['shot crosses solid tile',h['time'],blocked])
 a=h['angle']*math.tau/1024;c=math.cos(a);s=-math.sin(a);dx=o[0]-h['x'];dy=o[1]-h['y'];depth=dx*c+dy*s;side=dy*c-dx*s
 in_fov=depth>0 and abs(side)<depth*.731
 if in_fov and not h['projected']:fail.append(['unprojected shooter inside field of view',h['time'],h['actor']])
 hits.append(dict(seconds=h['time'],attacker=h['actor'],x=o[0],y=o[1],damage=h['damage'],projected=h['projected'],drawn=h.get('drawn'),inside_fov=in_fov,wall_or_closed_door=blocked))
# A same-frame pickup can raise health after the killing blow. Death is the
# level state, and the camera frames still have to face the killer.
dead=[f for f in data['frames'] if f['state']==1 or f['health']==0]
if not dead:fail.append('walk did not reach death')
if args.old:
 if data['final']['health'] or data['final']['state']!=1:fail.append('old build did not remain dead')
else:
 if args.game_over:
  if data['final']['state']!=3:fail.append('zero spare lives did not show game over')
 else:
  final=data['final']
  if (final['health'],final['lives'],final['state'],final['pwall'])!=(100,2,0,0):fail.append(['restart',final])
  turns=[f for f in dead if f.get('deathphase')==2]
  if not turns or turns[-1]['angle']!=turns[-1]['target']:fail.append('death view did not face the killer')
  elif data['hits'][-1]['actor'] not in turns[-1].get('ids',[]):fail.append('killer missing from the final death picture')
  if any(f['pwall'] for f in data['frames']):fail.append('idle world step started a push wall')
st=dict(states());fire=[st['s_grdshoot'+str(n)][2] for n in (1,2,3)]
result=dict(hits=hits,original_guard_shoot_states_tics=fire,original_shot_at_tic=sum(fire[:2]),deaths=data['death'],final=data['final'],failures=fail)
(p/'walk-oracle.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(hits=len(hits),rear_hits=sum(not h['inside_fov'] for h in hits),shoot_states=fire,final=data['final'],failures=fail),indent=2))
if fail:raise SystemExit(1)
