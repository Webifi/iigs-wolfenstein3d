"""Allocate constant-power stereo pairs for fixed pan positions.

This GPL-licensed build-time module supplies levels and routing through
muspan, with a per-song policy for when pairing is enabled.
"""
import inspect
from source_identity import function_source
import muspan


def allocate_pairs(primary,tail_level):
    """Colour stereo pairs together, keeping the DOC registers adjacent."""
    active={};last={};kept=[]
    stats=dict(paired=0,primary_release_tails_shortened=0,short_mirror_tails=0)
    for n in sorted(primary,key=lambda n:(n.on,n.ch,n.key)):
        if n.stop<=n.on:raise ValueError('primary has no attack interval')
        active={p:m for p,m in active.items() if max(m.stop,m.partner.stop if m.partner else m.stop)>n.on}
        free=[p for p in range(12) if p not in active]
        if not free:
            released=[(p,m) for p,m in active.items() if m.off<=n.on and m.on<n.on]
            if not released:raise ValueError('adjacent stereo allocation would cut a held primary')
            p,m=min(released,key=lambda item:tail_level(item[1],n.on))
            m.stop=m.end=n.on;stats['primary_release_tails_shortened']+=1
            if m.partner:
                m.partner.stop=m.partner.end=n.on;stats['short_mirror_tails']+=1
            del active[p];free=[p]
        preferred=[p for p in free if p in last and last[p].z is n.z]
        same_pitch=[p for p in preferred if last[p].key==n.key]
        p=min(same_pitch or preferred or free)
        n.voice=2*p+n.route_side
        if n.partner:
            n.partner.voice=2*p+n.partner.route_side;kept.append(n.partner);stats['paired']+=1
        kept.append(n);active[p]=last[p]=n
    return sorted(kept,key=lambda n:(n.on,n.voice)),stats

source = function_source(muspan.prepare)
old = 'channels={ch for ch,hs in histories.items() if len({p for _,p in hs})>1}'
assert source.count(old)==1
source=source.replace(old,'channels={n.ch for n in s.notes}')
needle='        if n.ch==9:\n            offset=127*n.r.pan'
assert source.count(needle)==1
source=source.replace(needle,'        if hasattr(n,"performed_pan_track"):\n            n.pan_track=n.performed_pan_track\n        elif n.ch==9:\n            offset=127*n.r.pan')
source=source.replace('if m.off<=n.on]', 'if m.off<=n.on and m.on<n.on]')
source=source.replace('    def tail_level(n,t):',
    '    def tail_level(n,t):\n        if getattr(s,"capture_factory",None):return s.capture_factory.tail_level(s,n,t)')
lines=source.splitlines()
matches=[i for i,line in enumerate(lines) if 'already centred, no pan motion' in line]
assert len(matches)==1
lines[matches[0]]='        # Wolf preserves centred parts with required pairs too.'
source='\n'.join(lines)
start=source.index('    for n in sorted(primary+aux+optional,')
source=source[:start]+'''    s.notes, pair_stats=allocate_pairs(primary,tail_level)
    stats.update(pair_stats)
    stats['adjacent_pairs']=True
    s.pan_stats=stats
'''
namespace=dict(muspan.__dict__)
namespace['range']=lambda *a: range(24) if a==(14,) else range(*a)
namespace['allocate_pairs']=allocate_pairs
exec(compile(source,'Doom muspan.prepare with Wolf fixed-pan policy','exec'),namespace)
prepare=namespace['prepare']

# Quantizing each side independently can push a full-scale pair above the
# mono power limit. Select the nearest legal pair before applying song gain.
original_levels=muspan.levels
source=function_source(original_levels)
# Fixed panning needs no tighter envelope timing than the note's existing
# scheduler allowance. Moving pan retains its one-tick bound.
needle='            n.level_wait=1'
assert source.count(needle)==1
source=source.replace(needle,'            if len({p for _,p in hs})>1:n.level_wait=1')
source=source.replace('sorted(vals,key=lambda v:abs(v-l))[:3]',
                      'sorted(vals,key=lambda v:abs(v-l))[:3]+[0]')
source=source.replace('sorted(vals,key=lambda v:abs(v-r))[:3]',
                      'sorted(vals,key=lambda v:abs(v-r))[:3]+[0]')
needle='((a,b) for a in aa for b in bb)'
assert source.count(needle)==1
source=source.replace(needle,'((a,b) for a in aa for b in bb if a*a+b*b<=total*total)')
exec(compile(source,'Wolf bounded constant-power pan quantization','exec'),namespace)
captured_levels=namespace['levels']


def levels(s,tracks,exact):
    # Keep the original model's pan rounding and command cadence. Captured
    # envelope fitting has its own quantization policy.
    return (captured_levels if getattr(s,'capture_factory',None) else original_levels)(s,tracks,exact)
