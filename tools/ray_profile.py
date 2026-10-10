"""Ray-part timing from stock PC bins and counted instructions in one frame."""
import argparse
import json
from pathlib import Path
from elf import read

ap=argparse.ArgumentParser()
ap.add_argument('scene',type=Path)
ap.add_argument('--elf',type=Path)
args=ap.parse_args()
_,sym=read(args.elf or (args.scene/'profile.elf' if (args.scene/'profile.elf').exists() else Path('build/wolf.elf')))
counts=json.loads((args.scene/'instruction-counts.json').read_text())
def entries(name):return counts.get(f'{sym[name]:06x}',{}).get('count',0)
rays=entries('traceRay');cells=entries('ddaLoop');kept=entries('nextRay')
if 'castProgramsBegin' in sym:kept=json.loads((args.scene/'result.json').read_text())['view']//2
attempts=entries('interpolateRay')
anchor_entries=[name for name in ('interpolateAnchors16','interpolateAnchors8',
                                 'interpolateAnchors4','interpolateAnchors2') if name in sym]
attempts+=sum(entries(name) for name in anchor_entries)
interpolation_start=anchor_entries[0] if anchor_entries else 'interpolateRay'
parts={
 'setup': [('traceRay','ddaLoop')],
 'grid': [('ddaLoop','wallHit')],
 'wall_and_plane': [('wallHit','keepPlane')],
 'depth_height': [('keepPlane','heightRange')],
 'height_source': [('heightRange','nextRay')],
 'loop': [('nextRay','castDone')],
 'hit_coordinate': [('hitCoordinate','doorHit'),('mulLowFrac','rayPartial' if 'rayPartial' in sym else 'hitCoordinate')],
}
if 'hitXIdentity' in sym:
    parts['shared_products']=[('mulFrac','focalProduct')]
else:
    parts['hit_coordinate'].append(('mulFrac','focalProduct'))
if 'castProgramsBegin' in sym:parts['command_stream']=[('castProgramsBegin','castProgramsEnd')]
if attempts:
    if 'planeRay' in sym:
        parts['interpolation']=[(interpolation_start,'planeRay'),('resolveRayMaterial','mulLowFrac')]
        parts['plane_setup']=[('planeRay','resolveRayMaterial')]
    else:parts['interpolation']=[(interpolation_start,'mulLowFrac')]
if 'InitOriginJump' in sym:parts['initial_skip']=[('InitOriginJump',interpolation_start)]
plane_samples=entries('planeRay') if 'planeRay' in sym else 0
finish_samples=entries('heightRange')
bins=[(int(a,16),int(t)*66/15120000) for a,t in (line.split() for line in (args.scene/'profile.txt').read_text().splitlines())]
executed={int(a,16):row['count'] for a,row in counts.items()}
def block(pc):return pc&(~15 if pc<0x60000 else ~255)
bin_counts={}
for pc,count in executed.items():bin_counts[block(pc)]=bin_counts.get(block(pc),0)+count
result={'traced_rays':rays,'kept_columns':kept,'interpolated_columns':kept-rays,'interpolation_attempts':attempts,'grid_cells':cells,'parts':{},'note':'PC-bin time (16 bytes below bank $06, 256 above) is apportioned by instruction execution counts at routine boundaries. Cycles are estimates at 2.8 MHz including modeled refresh, not instruction-exact timings.', 'accounting':'pc_bins_apportioned_by_instruction_counts', 'shared_product_note':'With direct hit-product rows, remaining mulFrac calls serve collision planes. They are shown per frame rather than charged to every fixed ray finish.'}
for name,ranges in parts.items():
    selected={}
    for pc,count in executed.items():
        if any(sym[lo]<=pc<sym[hi] for lo,hi in ranges):selected[block(pc)]=selected.get(block(pc),0)+count
    ms=sum(t*selected.get(a,0)/bin_counts[a] for a,t in bins if bin_counts.get(a))
    n=1 if name in ('initial_skip','shared_products') else cells if name=='grid' else attempts if name=='interpolation' else kept if name in ('loop','command_stream') else plane_samples if name=='plane_setup' else rays if name=='setup' else finish_samples
    unit='cycles_per_frame' if name in ('initial_skip','shared_products') else 'cycles_per_cell' if name=='grid' else 'cycles_per_attempt' if name=='interpolation' else 'cycles_per_kept_column' if name in ('loop','command_stream') else 'cycles_per_ray'
    result['parts'][name]={'ms':ms,unit:ms*2800/n if n else None}
result['fixed_cycles_per_ray']=None if plane_samples else sum(p.get('cycles_per_ray',0) or 0 for p in result['parts'].values())
result['skipped_cells']=3*(entries('originJumpUsedX')+entries('originJumpUsedY')) if 'originJumpUsedX' in sym else 0
if 'originJumpUsedSevenX' in sym:result['skipped_cells']+=7*(entries('originJumpUsedSevenX')+entries('originJumpUsedSevenY'))
result['finish_samples']=finish_samples
result['plane_samples']=entries('planeRay') if 'planeRay' in sym else 0
result['weighted_span_columns']=sum(entries(n) for n in ('weightedSpanPost','mixedWeightedPost','splitWeightedPost') if n in sym)
result['weighted_midpoints']=entries('weightedRay') if 'weightedRay' in sym else 0
# The plain span is straight code since spanPost4: spanFillPost starts a seven-post span, spanPost4 a three-post one.
plain=7*entries('spanFillPost')+3*(entries('spanPost4')-entries('spanFillPost')) if 'spanPost4' in sym else entries('spanFillPost')
result['bulk_emitted_columns']=plain+sum(entries(n) for n in ('mixedSpanPost','splitSpanPost') if n in sym)
(args.scene/'ray-profile.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
