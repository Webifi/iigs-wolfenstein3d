"""Count interpolation differences at identical captured poses and bound them."""
import argparse
import json
from pathlib import Path
from reference import render, project_sprites, overlay_sprites, HEIGHTS

ap=argparse.ArgumentParser();ap.add_argument('scene',type=Path);args=ap.parse_args()
reports=[]
mode=json.loads((args.scene/'result.json').read_text()).get('rays','half')
stride={'thirtytwo':32,'sixteenth':16,'eighth':8,'quarter':4}.get(mode,2)
for path in sorted(args.scene.glob('state*.json'),key=lambda p:int(p.stem[5:])):
    n=path.stem[5:];state=json.loads(path.read_text());view=state['view_width']
    state['unwrapped_rays']=json.loads((args.scene/'result.json').read_text()).get('unwrapped_rays',False)
    state['material_lookup']=json.loads((args.scene/'result.json').read_text()).get('material_lookup',False)
    state['material_guard_texels']=json.loads((args.scene/'result.json').read_text()).get('material_guard_texels',3)
    state['push_planes']=json.loads((args.scene/'result.json').read_text()).get('push_planes',False)
    state['door_planes']=json.loads((args.scene/'result.json').read_text()).get('door_planes',False)
    state['coarse_material']=json.loads((args.scene/'result.json').read_text()).get('coarse_material',False)
    state['vector_weights']=json.loads((args.scene/'result.json').read_text()).get('vector_weights',False)
    state['split_span']=json.loads((args.scene/'result.json').read_text()).get('split_span',False)
    state['mixed_span']=json.loads((args.scene/'result.json').read_text()).get('mixed_span',False)
    state['weighted_span']=json.loads((args.scene/'result.json').read_text()).get('weighted_span',False)
    state['weighted_rays']=json.loads((args.scene/'result.json').read_text()).get('weighted_rays',False)
    state['plane_rays']=json.loads((args.scene/'result.json').read_text()).get('plane_rays',False)
    state['span_fill']=json.loads((args.scene/'result.json').read_text()).get('span_fill',False)
    state['tilemap']=(args.scene/f'map{n}.bin').read_bytes()
    world=json.loads((args.scene/f'objects{n}.json').read_text())['objects']
    exact,er=render(state,view,interpolate=False)
    interp,ir=render(state,view,interpolate=stride)
    ev=project_sprites(state,world,er['visible_tiles'],view)
    iv=project_sprites(state,world,ir['visible_tiles'],view)
    overlay_sprites(exact,ev,view,er['records']);overlay_sprites(interp,iv,view,ir['records'])
    changed_columns={c for c,(a,b) in enumerate(zip(er['records'],ir['records'])) if a[:3]!=b[:3]}
    interpolated=set(range(view))-set(ir['traced_columns'])
    assert changed_columns<=interpolated
    offset=(160-view)//2
    allowed={row*160+offset+c for c in changed_columns for row in range(offset,offset+view)}
    changed_sprites=[r for r in ev if r not in iv]+[r for r in iv if r not in ev]
    for r in changed_sprites:
        left,right=r[:2];left=left-65536 if left>=32768 else left;right=right-65536 if right>=32768 else right
        h=HEIGHTS[r[2]//2]
        allowed.update(row*160+offset+c for c in range(max(0,left),min(view,right)) for row in range(max(offset,80-h//2),min(offset+view,80+(h+1)//2)))
    actual=(args.scene/f'frame{n}.bin').read_bytes()
    differences={i for i,(a,b) in enumerate(zip(actual,exact)) if a!=b}
    unexpected=differences-allowed
    oracle=sum(a!=b for a,b in zip(actual,interp))
    row={'frame':int(n),'interpolated_columns':len(interpolated),'changed_wall_columns':len(changed_columns),'differing_bytes_from_exact':len(differences),'outside_interpolation_or_changed_sprite_rectangles':len(unexpected),'interpolated_reference_differences':oracle,'changed_sprite_records':len(changed_sprites),'max_texture_column_error_same_page':max((abs(a[2]-b[2]) for a,b in zip(er['records'],ir['records']) if a[1]==b[1]),default=0),'max_circular_texture_column_error_same_page':max((min(abs(a[2]-b[2]),64-abs(a[2]-b[2])) for a,b in zip(er['records'],ir['records']) if a[1]==b[1]),default=0),'different_material_columns':sum(a[1]!=b[1] for a,b in zip(er['records'],ir['records']))}
    reports.append(row)
    assert not unexpected and not oracle,row
(args.scene/'interpolation-differences.json').write_text(json.dumps(reports,indent=2)+'\n')
print(json.dumps(reports,indent=2))
