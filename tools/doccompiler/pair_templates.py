"""Lossless paired DOC templates for the existing prepared 65816 entry point.

Each opcode identifies a stereo pair and an ordered register-write template.
Equal left/right operands share a byte; frequent literal events and small
volume deltas use spare opcodes. Every DOC transfer retains BUSY polling.
The JSON oracle follows the waves and is absent from the installed cold bank.
"""
from collections import Counter, defaultdict
import json
import struct
import unit2
import batchcompile
from prepared import Code, verify

def plan(rows):
    state=[127]*32;paircounts=Counter();parts=[]
    for pos,wait,groups,end in rows:
        voices=defaultdict(list)
        for reg,vals in groups:
            for i,v in enumerate(vals):voices[((reg+i)&31)//2].append((reg+i,v))
        row=[]
        for pair,writes in sorted(voices.items()):
            local=[]
            for reg,vals in batchcompile.batches(writes):
                if reg&224==64:
                    state[reg&31:(reg&31)+len(vals)]=vals
                    levels=tuple(state[pair*2:pair*2+2]);paircounts[levels]+=1
                    local.append((reg,tuple(vals),levels))
                else:local.append((reg,tuple(vals),None))
            row.append((pair,local))
        parts.append((pos,wait,row,end))
    pairs=[(127,127)]+[p for p,_ in paircounts.most_common() if p!=(127,127)][:127]
    pairids={p:i for i,p in enumerate(pairs)}
    output=[];counts=Counter()
    for pos,wait,parts,end in parts:
        row=[]
        for pair,groups in parts:
            key=[];args=[]
            for r,vals,levels in groups:
                rel=r-pair*2
                if levels is not None:
                    if levels==(127,127):kind=4;literal=(0,)
                    elif levels in pairids:kind=3;literal=();args.append(pairids[levels])
                    else:kind=5;literal=();args.extend(levels)
                elif r&224==160:kind=1;literal=vals
                elif len(set(vals))==1 and len(vals)>1:kind=2;literal=();args.append(vals[0])
                else:kind=0;literal=();args.extend(vals)
                key.append((rel,len(vals),kind,literal))
            key=tuple(key);counts[key]+=1;row.append((pair,key,tuple(args)))
        output.append((pos,wait,row,end))
    keys=[k for k,n in counts.most_common()];ids={k:i for i,k in enumerate(keys)}
    size=sum(2+sum((1 if ids[k]<16 else 3)+len(a) for pair,k,a in row) for _,_,row,_ in output)
    return output,keys,pairs,size

PAIR,OP,VAL,LEFT,RIGHT,DL,DR,MASK=0x24,0x26,0x28,0x2a,0x2b,0x2c,0x2d,0x2e

def compile_rows(header,records,waves,timeline=()):
    output,keys,pairs,_=plan(records)
    ids={k:i for i,k in enumerate(keys)}
    if len(keys)>256:raise ValueError('more than 256 pair templates')
    delta={};state=[127]*32;seen=set()
    for pos,wait,groups,end in records:
        before=list(state);voices=defaultdict(list)
        for r,vals in groups:
            for i,v in enumerate(vals):voices[((r+i)&31)//2].append((r+i,v))
            if r&224==64:state[r&31:(r&31)+len(vals)]=vals
        for pair,ww in voices.items():
            if pair in seen and all(r&224==64 for r,v in ww):
                entries=tuple(sorted((r&1,v-before[r&31]) for r,v in ww))
                if len(entries)==len(set(r for r,d in entries)) and all(-8<=d<=8 for r,d in entries):
                    delta[pos,pair]=entries
            if any(r&224==64 for r,v in ww):seen.add(pair)
    events={};candidates=defaultdict(set)
    for pos,wait,row,end in output:
        for pair,key,args in row:
            eid=(pos,pair);cost=(1 if ids[key]<16 else 3)+len(args)
            if cost<=1:continue
            events[eid]=cost-1
            candidates['literal',pair,ids[key],args].add(eid)
            if eid in delta:candidates['delta',pair,delta[eid]].add(eid)
    slots=[x for x in range(256) if x&15>=12 and x not in (13,14,15)]
    # Each event belongs to at most a literal and a delta candidate. Update
    # those gains when it is claimed, preserving insertion order for ties.
    members=defaultdict(list)
    gains={}
    for key,hits in candidates.items():
        gains[key]=sum(events[e] for e in hits)-(20+len(key[3]) if key[0]=='literal' else 24)
        for eid in hits:members[eid].append(key)
    chosen={};specials={}
    for op in slots:
        if not gains:break
        key=max(gains,key=gains.get)
        if gains[key]<=0:break
        hits=candidates[key]-chosen.keys()
        specials[op]=key
        for eid in hits:
            chosen[eid]=op
            for other in members[eid]:gains[other]-=events[eid]
    stream=bytearray();times=[];source_times={pos:t for t,pos in timeline}
    for pos,wait,row,end in output:
        if pos in source_times:times.append((source_times[pos],len(stream)))
        stream.append(wait)
        for pair,key,args in row:
            if (pos,pair) in chosen:stream.append(chosen[pos,pair]);continue
            k=ids[key]
            stream.extend(((k<<4)|(pair-2),) if k<16 else (15,k,pair-2))
            stream.extend(args)
        stream.append(14 if end else 13)
    literal_at={}
    for op,key in specials.items():
        if key[0]=='literal':
            literal_at[op]=len(stream);stream.extend(key[3])
    vectors=(unit2.STREAM+len(stream)+1)&~1
    extra=vectors+2*len(keys)
    body=extra+512
    c=Code(body)
    def call(label):c.jump(label);c.data[-3]=0x20
    def indexed_jump(at):c.word(0x7c,at)
    def indexed_call(at):c.word(0xfc,at)
    def address(rel):
        c.ready();c.word(0xad,PAIR);c.emit(0x09,rel,0x8f,0x3e,0xc0,0xe0)
    def branch(op,label):
        # Branch over a three-byte absolute jump when the condition is false.
        inverse={0xf0:0xd0,0xd0:0xf0,0x90:0xb0,0xb0:0x90,0x30:0x10,0x10:0x30}[op]
        c.emit(inverse,3);c.jump(label)
    def scaled(value):c.word(0xad,value);c.emit(0xaa);c.word(0xbd,unit2.VSCALE);c.write()
    c.mark('next');c.operand();c.word(0x8d,OP);c.word(0x9c,OP+1)
    c.emit(0x29,15,0xc9,12);branch(0xb0,'special')
    c.emit(0x0a,0x18,0x69,4);c.word(0x8d,PAIR);c.word(0x9c,PAIR+1)
    c.word(0xad,OP);c.emit(0x4a,0x4a,0x4a,0x29,30,0xaa)
    indexed_call(vectors);c.jump('next')
    c.mark('special');c.word(0xad,OP)
    c.emit(0xc9,13);branch(0xf0,'end')
    c.emit(0xc9,14);branch(0xf0,'loop')
    c.emit(0xc9,15);branch(0xf0,'escape')
    c.emit(0xc2,0x20);c.word(0xad,OP);c.emit(0x0a,0xaa);c.word(0xa9,0);c.emit(0xe2,0x20)
    indexed_call(extra);c.jump('next')
    c.mark('escape');c.operand();c.emit(0xc2,0x20,0x0a,0xaa);c.word(0xa9,0);c.emit(0xe2,0x20)
    c.operand();c.emit(0x0a,0x18,0x69,4);c.word(0x8d,PAIR);c.word(0x9c,PAIR+1)
    indexed_call(vectors);c.jump('next')
    c.mark('end');c.emit(0x6b)
    c.mark('loop');c.word(0xa0,0);c.emit(0x6b)
    c.mark('unused');c.emit(0x60)
    for i,key in enumerate(keys):
        c.mark('key'+str(i))
        for rel,n,kind,values in key:
            if kind in (3,4):
                if kind==4:c.emit(0xa9,values[0])
                else:c.operand()
                c.word(0xae,PAIR);c.word(0x9d,unit2.LEVEL);c.word(0x9e,unit2.LEVEL+1);c.emit(0xaa)
                address(rel)
                for k in range(n):
                    if k:c.ready()
                    c.word(0xbd,0x280 if (rel+k)&1 else 0x200);c.write()
            elif kind==5:
                c.word(0xae,PAIR);c.operand();c.emit(0x09,128);c.word(0x9d,unit2.LEVEL)
                c.operand();c.word(0x9d,unit2.LEVEL+1)
                address(rel)
                for k in range(n):
                    if k:c.ready()
                    c.word(0xbd,unit2.LEVEL+((rel+k)&1))
                    if not (rel+k)&1:c.emit(0x29,127)
                    c.emit(0xda,0xaa);c.word(0xbd,unit2.VSCALE);c.emit(0xfa);c.write()
            else:
                address(rel)
                for k in range(n):
                    if k:c.ready()
                    if kind==1:c.emit(0xa9,values[k])
                    elif kind==2:
                        if not k:c.operand();c.word(0x8d,VAL)
                        else:c.word(0xad,VAL)
                    else:c.operand()
                    c.write()
                if rel&224==160 and (kind!=1 or any(v&3==3 for v in values)):c.emit(*([0xea]*32))
        c.emit(0x60)
    for op,key in specials.items():
        c.mark('special'+str(op));c.emit(0xa9,key[1]*2);c.word(0x8d,PAIR);c.word(0x9c,PAIR+1)
        if key[0]=='literal':
            c.emit(0x5a);c.word(0xa0,literal_at[op]);call('key'+str(key[2]));c.emit(0x7a,0x60)
        else:
            ds=dict(key[2]);mask=sum(1<<side for side in ds)
            for a,value in [(DL,ds.get(0,0)),(DR,ds.get(1,0)),(MASK,mask)]:c.emit(0xa9,value&255);c.word(0x8d,a)
            call('delta');c.emit(0x60)
    c.mark('delta');c.word(0xae,PAIR);c.word(0xbd,unit2.LEVEL);branch(0x30,'raw')
    c.emit(0xaa);c.word(0xbd,0x100);c.word(0x8d,LEFT);c.word(0xbd,0x180);c.word(0x8d,RIGHT);c.jump('loaded')
    c.mark('raw');c.emit(0x29,127);c.word(0x8d,LEFT);c.word(0xbd,unit2.LEVEL+1);c.word(0x8d,RIGHT)
    c.mark('loaded')
    for a,d in [(LEFT,DL),(RIGHT,DR)]:c.word(0xad,a);c.emit(0x18);c.word(0x6d,d);c.word(0x8d,a)
    c.word(0xae,PAIR);c.word(0xad,LEFT);c.emit(0x09,128);c.word(0x9d,unit2.LEVEL);c.word(0xad,RIGHT);c.word(0x9d,unit2.LEVEL+1)
    c.word(0xad,MASK);c.emit(0xc9,2);branch(0xf0,'rightonly')
    address(64);scaled(LEFT)
    c.word(0xad,MASK);c.emit(0xc9,1);branch(0xf0,'deltadone')
    c.ready();scaled(RIGHT);c.jump('deltadone')
    c.mark('rightonly');address(65);scaled(RIGHT)
    c.mark('deltadone');c.emit(0x60)
    code=c.resolve();hotlen=body+len(code)
    if hotlen>65535:raise unit2.HotBankOverflow(hotlen)
    hot=bytearray(hotlen);hot[:unit2.STREAM]=header[:unit2.STREAM]
    hot[0x100:0x440]=bytes(0x340);hot[0x100:0x200]=bytes([127])*256
    for i,(l,r) in enumerate(pairs):hot[0x100+i]=l;hot[0x180+i]=r
    hot[0x300:0x304]=bytes((0x5c,c.labels['next']&255,c.labels['next']>>8,0x3e))
    hot[unit2.STREAM:unit2.STREAM+len(stream)]=stream;hot[body:]=code
    for i in range(len(keys)):struct.pack_into('<H',hot,vectors+2*i,c.labels['key'+str(i)])
    for op in range(256):struct.pack_into('<H',hot,extra+2*op,c.labels.get('special'+str(op),c.labels['unused']))
    hot[unit2.LEVEL+4:unit2.LEVEL+28]=bytes(24)
    hot[21]=48;hot[22:32]=bytes(10);hot[30]=32;hot[31]=44
    struct.pack_into('<HH',hot,6,len(stream),hotlen)
    oracle=json.dumps(dict(keys=keys,specials=specials),separators=(',',':')).encode()
    data=bytes(hot)+waves+oracle
    verify(data, records)
    return data,times,dict(prepared=True,pair_templates=True,handler_bytes=len(code),handlers=len(keys),
        special_opcodes=len(specials),hot_bytes=hotlen,stream_bytes=len(stream),pair_dictionary=len(pairs))

def wake(self):
    if not hasattr(self, "defs"):
        self.defs = json.loads(bytes(self.u[self.oracle_base:]))
    u,writes=self.u,[]
    def get():
        b=u[unit2.STREAM+self.y];self.y+=1;return b
    def volume(pair,values,rel,count):
        for k in range(count):
            level=values[(rel+k)&1]
            writes.append((pair*2+rel+k,level if self.symbolic else u[unit2.VSCALE+level]))
    def template(pair,ident,read):
        for rel,count,kind,literal in self.defs['keys'][ident]:
            if kind in (3,4):
                index=read() if kind==3 else literal[0]
                u[unit2.LEVEL+pair*2:unit2.LEVEL+pair*2+2]=bytes((index,0))
                volume(pair,(u[0x100+index],u[0x180+index]),rel,count)
            elif kind==5:
                left,right=read(),read()
                u[unit2.LEVEL+pair*2:unit2.LEVEL+pair*2+2]=bytes((left|128,right))
                volume(pair,(left,right),rel,count)
            else:
                values=literal if kind==1 else [read()]*count if kind==2 else [read() for _ in range(count)]
                writes.extend((pair*2+rel+k,v) for k,v in enumerate(values))
    b=get();assert b>0xd0 and b&15
    n=b&15
    if b>=0xe0:
        writes.append((29,u[unit2.WLO+n]))
        if b<0xf0:writes.append((61,u[unit2.WHI+n]))
    writes.append((189,10))
    while True:
        op=get()
        if op in (13,14):
            if op==14:self.y=0
            return n,writes
        if op==15:
            ident,pair=get(),get()+2;template(pair,ident,get)
        elif op&15<12:template((op&15)+2,op>>4,get)
        else:
            spec=self.defs['specials'][str(op)];kind,pair=spec[:2]
            if kind=='literal':template(pair,spec[2],iter(spec[3]).__next__)
            else:
                index=u[unit2.LEVEL+pair*2]
                values=[index&127,u[unit2.LEVEL+pair*2+1]] if index&128 else [u[0x100+index],u[0x180+index]]
                for side,delta in spec[2]:values[side]+=delta
                assert all(0<=v<128 for v in values)
                u[unit2.LEVEL+pair*2:unit2.LEVEL+pair*2+2]=bytes((values[0]|128,values[1]))
                for side,_ in spec[2]:volume(pair,values,64+side,1)
