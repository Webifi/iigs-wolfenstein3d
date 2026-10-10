"""Calypsi ELF images/symbols, adapted from the team's fastprof ELF reader."""
import struct
from pathlib import Path

def read(path):
 data=Path(path).read_bytes()
 if data[:4]!=b'\x7fELF':raise ValueError('not an ELF')
 po,=struct.unpack_from('<I',data,28);ps,pn=struct.unpack_from('<HH',data,42)
 segments=[]
 for i in range(pn):
  kind,off,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',data,po+i*ps)
  if kind==1:segments.append(dict(address=va,data=data[off:off+fs],size=ms,flags=flags))
 so,=struct.unpack_from('<I',data,32);ss,sn=struct.unpack_from('<HH',data,46)
 sections=[struct.unpack_from('<10I',data,so+i*ss) for i in range(sn)];symbols={}
 for s in sections:
  if s[1]!=2:continue
  strings=sections[s[6]]
  for off in range(s[4],s[4]+s[5],16):
   n,v,size,info,other,idx=struct.unpack_from('<IIIBBH',data,off)
   if not n or not idx:continue
   start=strings[4]+n;name=data[start:data.index(b'\0',start)].decode()
   symbols[name]=v
 return segments,symbols
