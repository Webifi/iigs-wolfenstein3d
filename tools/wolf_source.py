"""Extract constants and tables from the selected Wolf or Spear source sections."""
import re
from functools import lru_cache
from wolfdata import ID

def wolf_only(text):
 active=[True];positive=[];out=[]
 for line in text.splitlines():
  m=re.match(r'\s*#\s*(ifdef|ifndef)\s+SPEAR',line)
  if m:
   cond=m[1]=='ifndef';positive.append(cond);active.append(active[-1] and cond)
  elif re.match(r'\s*#\s*else',line) and positive:
   active[-1]=active[-2] and not positive[-1]
  elif re.match(r'\s*#\s*endif',line) and positive:
   active.pop();positive.pop()
  elif active[-1]:out.append(line)
 return '\n'.join(out)

def sprite_ids():
 return _sprite_ids().copy()

@lru_cache(maxsize=1)
def _sprite_ids():
 text=(ID/'WOLFSRC/WL_DEF.H').read_text()
 text=text[text.index('SPR_DEMO'):];text=text[:text.index('};')]
 text=wolf_only(text);text=re.sub(r'//[^\n]*|/\*.*?\*/','',text,flags=re.S)
 names=re.findall(r'\b[A-Z][A-Z0-9_]*\b',text)
 return {name:i for i,name in enumerate(names)}

def statics():
 return list(_statics())

@lru_cache(maxsize=1)
def _statics():
 text=(ID/'WOLFSRC/WL_ACT1.C').read_text();text=text[text.index('} statinfo[]'):];text=text[:text.index('};')]
 text=wolf_only(text)
 return [(p,t or 'dressing') for p,t in re.findall(r'\{(SPR_STAT_\d+)(?:,([a-z0-9_]+))?\}',text)]

def states(families="grd|dog|ss|boss"):
 return list(_states(families))

@lru_cache(maxsize=None)
def _states(families):
 text=wolf_only((ID/'WOLFSRC/WL_ACT2.C').read_text())
 rows=[('s_none',(0,0,0,'NULL','NULL','s_none'))]
 ids=sprite_ids()
 if families is None:families='[a-z]+'
 for name,body in re.findall(rf'statetype\s+(s_(?:{families})\w*)\s*=\s*\{{([^}}]+)\}}',text):
  rotate,pic,tics,think,action,nextstate=[v.strip() for v in body.split(',')]
  rows.append((name,(int(rotate.replace('true','1').replace('false','0')),ids[pic] if pic in ids else int(pic),int(tics),think,action,nextstate.lstrip('&') if nextstate != 'NULL' else None)))
 return rows

def random_table():
 return list(_random_table())

@lru_cache(maxsize=1)
def _random_table():
 text=(ID/'WOLFSRC/ID_US_A.ASM').read_text();text=text[text.index('rndtable db'):text.index('PUBLIC\trndtable')]
 nums=[int(v) for v in re.findall(r'\b\d+\b',text)]
 if len(nums)!=256:raise ValueError('original RNG length')
 return nums

def attack_table():
 return list(_attack_table())

@lru_cache(maxsize=1)
def _attack_table():
 text=(ID/'WOLFSRC/WL_AGENT.C').read_text()
 text=text[text.index('attackinfo[4][14]'):];text=text[:text.index('};')]
 rows=[tuple(map(int,row)) for row in re.findall(r'\{\s*(\d+),\s*(-?\d+),\s*(\d+)\s*\}',text)]
 if len(rows)!=16:raise ValueError('original weapon cycles')
 return rows

def hitpoints():
 return [row[:] for row in _hitpoints()]

@lru_cache(maxsize=1)
def _hitpoints():
 text=wolf_only((ID/'WOLFSRC/WL_ACT2.C').read_text())
 text=text[text.index('starthitpoints[4][NUMENEMIES]'):];text=text[:text.index('};')]
 text=re.sub(r'//[^\n]*|/\*.*?\*/','',text,flags=re.S)
 rows=[list(map(int,re.findall(r'\d+',row))) for row in re.findall(r'\{([^{}]+)\}',text)]
 if len(rows)!=4 or len({len(row) for row in rows})!=1:raise ValueError('original enemy HP')
 return [[row[n] for n in (0,3,2,4)] for row in rows]


def engine_only(text, *, spear=False):
 # Reuse the Wolf selector after reversing only the SPEAR conditionals.
 if spear:
  text=re.sub(r'(^\s*#\s*)(ifdef|ifndef)(\s+SPEAR\b)',
              lambda m:m[1]+('ifndef' if m[2]=='ifdef' else 'ifdef')+m[3],text,flags=re.M)
 return wolf_only(text)

def sound_ids(*, spear=False):
 text=(ID/('WOLFSRC/AUDIOSOD.H' if spear else 'WOLFSRC/AUDIOWL6.H')).read_bytes().decode('latin-1')
 body=text[text.index('typedef enum'):].split('}',1)[0]
 return {name:i for i,name in enumerate(re.findall(r'\b([A-Z0-9_]+SND)\b',body))}

def reference_tables(*, spear=False):
 """Complete source tables for a selected engine; no native actor bindings."""
 selected=lambda name:engine_only((ID/'WOLFSRC'/name).read_text(),spear=spear)
 text=selected('WL_DEF.H');text=text[text.index('SPR_DEMO'):].split('};',1)[0]
 text=re.sub(r'//[^\n]*|/\*.*?\*/','',text,flags=re.S)
 sprites={name:i for i,name in enumerate(re.findall(r'\b[A-Z][A-Z0-9_]*\b',text))}
 text=selected('WL_ACT1.C');text=text[text.index('} statinfo[]'):].split('};',1)[0]
 objects=[(pic,kind or 'dressing') for pic,kind in re.findall(r'\{(SPR_STAT_\d+)(?:,([a-z0-9_]+))?\}',text)]
 text=selected('WL_ACT2.C')
 actors=[('s_none',(0,0,0,'NULL','NULL','s_none'))]
 for name,body in re.findall(r'statetype\s+(s_[a-z]+\w*)\s*=\s*\{([^}]+)\}',text):
  rotate,pic,tics,think,action,nextstate=[v.strip() for v in body.split(',')]
  actors.append((name,(int(rotate.replace('true','1').replace('false','0')),
                      sprites[pic] if pic in sprites else int(pic),int(tics),think,action,
                      nextstate.lstrip('&') if nextstate!='NULL' else None)))
 body=text[text.index('starthitpoints[4][NUMENEMIES]'):].split('};',1)[0]
 body=re.sub(r'//[^\n]*|/\*.*?\*/','',body,flags=re.S)
 hp=[list(map(int,re.findall(r'\d+',row))) for row in re.findall(r'\{([^{}]+)\}',body)]
 if len(hp)!=4 or len({len(row) for row in hp})!=1:raise ValueError('original enemy HP')
 return dict(sprites=sprites,statics=objects,states=actors,hitpoints=hp)


# Keep the legacy extraction byte-for-byte on Wolf builds.
from wolfdata import PROFILE
if PROFILE.spear:
 from functools import lru_cache
 reference_tables = lru_cache(maxsize=2)(reference_tables)
 def sprite_ids():
  return reference_tables(spear=True)['sprites']
 def statics():
  return reference_tables(spear=True)['statics']
 def states(families="grd|dog|ss|trans"):
  rows=reference_tables(spear=True)['states']
  return rows if families is None else [row for row in rows if row[0]=='s_none' or re.match(r's_(?:'+families+r')',row[0])]
