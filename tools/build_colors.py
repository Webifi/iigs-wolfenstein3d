"""Fit each floor's palette to visible art at the configured distance lights."""
import collections
import argparse
import json
import math
import random
from pathlib import Path
from wolfdata import CONVERSION,ROOT,PROFILE,maps,vswap,palette,sprite
from wolf_source import sprite_ids,statics
from sourceview import source_frame
import viewcolor as vc
from gscolor import align4
from shared_gray import align_palette
from wood_lighting import preserve_grain
from floor_art import ceiling as floor_ceiling, floor_color
from palette_sampling import wall_histogram, world_distribution, conversion_scores, no_regression

# Fixed prefix: slot 0 black, slot 1 light neutral. The other fourteen colors are
# chosen for the picture, then permuted. Their RGB is not snapped to a hue.
FIXED=((0,0,0),(13,13,13))
WORLD_CONVERSION=CONVERSION['world']
CFG=dict(err_kc=WORLD_CONVERSION['error_chroma_weight'],
         err_kh=WORLD_CONVERSION['error_hue_weight'],
         err_d0=WORLD_CONVERSION['large_error_scale'],
         noise_kc=WORLD_CONVERSION['noise_chroma_weight'],
         hue_k=WORLD_CONVERSION['noise_hue_weight'])
LIGHT_GAINS=tuple(WORLD_CONVERSION['light_gains'])
WALL_LIGHT_GAINS=tuple(WORLD_CONVERSION.get('wall_light_gains', LIGHT_GAINS))
FIT_GAINS=tuple(WORLD_CONVERSION['palette_fit_gains'])


def ordered_colors(colors):
    """Choose shared slot roles without replacing any fitted RGB value."""
    ordered = align4(colors, 2)
    words = align_palette([(r << 8) | (g << 4) | b for r,g,b in ordered])
    return [tuple(word >> shift & 15 for shift in (8,4,0)) for word in words]


def seed_colors(palette):
    """Restore fitting anchors before optimizing a previously aligned palette."""
    if len(palette)!=16 or any(len(c)!=3 or any(type(v) is not int or not 0<=v<=255 or v%17 for v in c) for c in palette):
        raise ValueError('seed palette must contain sixteen 12-bit RGB colors')
    rest=[tuple(v//17 for v in c) for c in palette]
    for anchor in FIXED:
        if anchor not in rest:
            raise ValueError('seed palette is missing a fixed black/bright fitting anchor')
        rest.remove(anchor)
    return list(FIXED)+rest


def shaded(rgb,gain):
    return tuple(vc.to_srgb(vc.LIN[v]*gain) for v in rgb)


def floor_shapes(level):
    from floor_art import shapes
    actors, objects, weapons = shapes(level)
    sampling = PROFILE.document['graphics'].get('palette_sampling', {})
    ids = sprite_ids()
    objects.difference_update(ids[name] for name in sampling.get('exclude_objects', ()))
    objects.update(ids[name] for name in sampling.get('include_objects', ()))
    return actors, objects, weapons


def light_maps(pal, ordered, metric):
    """Fit stored light levels to an existing palette without changing its slots."""
    mixes=vc.Mixes(ordered,metric)
    walls=[[mixes.bytes_for(shaded(c,gain),.20) for c in pal] for gain in WALL_LIGHT_GAINS]
    preserve_grain(walls,pal,ordered,metric,WALL_LIGHT_GAINS)
    sprites=[[mixes.bytes_for(shaded(c,gain),.35) for c in pal] for gain in LIGHT_GAINS]
    for c in (0x19,0x1d,0xbf,127,125,124):
        k=min(range(16),key=lambda k:metric.err(vc.oklab8(pal[c]),vc.lab12(ordered[k])))
        walls[-1][c]=(k*17,k*17)
    return walls,sprites


def fitting_targets(world,sprite_counts,weapon_counts,pal,flat_weights=None):
    weights=[0.0]*256;lit=[0.0]*256;full=[0.0]*256
    for counter,share,alpha in ((world,.68,1),(sprite_counts,.20,.75),(weapon_counts,.12,.75)):
        total=sum(v**alpha for v in counter.values())
        for c,v in counter.items():
            w=share*(v**alpha)/total;weights[c]+=w
            (full if counter is weapon_counts else lit)[c]+=w
    flat_weights=flat_weights or {}
    for c,w in flat_weights.items():
        lit[c]=max(0.0,lit[c]-.68*w)
    targets=[];solid=[]
    for i,c in enumerate(pal):
        for gain in FIT_GAINS:
            if lit[i]:
                lab=vc.oklab8(shaded(c,gain))
                targets.append((lab,lit[i]/len(FIT_GAINS)*(1+2*math.hypot(*lab[1:])),.20));solid.append(False)
        if full[i]:
            lab=vc.oklab8(c);targets.append((lab,full[i]*(1+2*math.hypot(*lab[1:])),.35));solid.append(False)
        if flat_weights.get(i,0):
            lab=vc.oklab8(c);targets.append((lab,.68*flat_weights[i]*(1+2*math.hypot(*lab[1:])),0));solid.append(True)
    return targets, weights, solid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap-wood',action='store_true',
                        help='Update only wood mappings in already fitted floor palettes.')
    parser.add_argument('--remap-lights',action='store_true',
                        help='Regenerate light mappings with the existing fitted palettes and slot order.')
    parser.add_argument('--output', type=Path, default=ROOT/'build/palettes',
                        help='Palette receipt directory; does not change native build assets.')
    parser.add_argument('--floors', type=int, nargs='+',
                        help='Zero-based source floors to convert (default: the complete selected game).')
    parser.add_argument('--seed-palettes', type=Path,
                        help='Start optimization from existing per-floor fitted colors, not fixed replacements.')
    args=parser.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    levels=maps();pages,base,_=vswap();pal=palette();metric=vc.Metric(CFG)
    selected = list(range(PROFILE.floors)) if args.floors is None else args.floors
    if any(n < 0 or n >= PROFILE.floors for n in selected):
        parser.error('floor index is outside the selected source game')
    if args.remap_lights:
        for n in selected:
            target=out/(str(n)+'.json');record=json.loads(target.read_text())
            wall_lights,sprite_lights=light_maps(pal,[tuple(v//17 for v in c) for c in record['palette']],metric)
            record.update(wall_lights=wall_lights,sprite_lights=sprite_lights,
                          wall_ab=wall_lights[-1],sprite_ab=sprite_lights[-1],light_gains=LIGHT_GAINS,
                          palette_fit_gains=FIT_GAINS)
            target.write_text(json.dumps(record,separators=(',',':'))+'\n')
            print('floor',n+1,'light maps',LIGHT_GAINS,flush=True)
        return
    if args.remap_wood:
        for n in selected:
            target=out/(str(n)+'.json');record=json.loads(target.read_text())
            preserve_grain(record['wall_lights'],pal,
                           [tuple(v//17 for v in c) for c in record['palette']],metric,WALL_LIGHT_GAINS)
            record['wall_ab']=record['wall_lights'][-1]
            target.write_text(json.dumps(record,separators=(',',':'))+'\n')
        return
    vc.FIXED=FIXED
    for n in selected:
        level=levels[n]
        target=out/(str(n)+'.json')
        world=collections.Counter();flat_counts=collections.Counter();sprite_counts=collections.Counter();weapon_counts=collections.Counter()
        starts=[(i%64,i//64,t) for i,t in enumerate(level['planes'][1]) if 19<=t<=22]
        x,y,t=starts[0];spawn=dict(x=x*256+128,y=y*256+128,angle=((1-(t-19))*256)%1024)
        poses=[dict(spawn,angle=a*128) for a in range(8)]
        cells=[i for i,t in enumerate(level['planes'][0]) if t>=107];rng=random.Random(0x574f4c46+n)
        for i in rng.sample(cells,min(32,len(cells))):poses.append(dict(x=(i%64)*256+128,y=(i//64)*256+128,angle=rng.randrange(1024)))
        for pose in poses:
            pixels,heights=source_frame(n,pose,240,status=False)
            for height in heights:
                flat_counts[floor_ceiling(n)]+=max(20,80-height//2)-20
                flat_counts[floor_color()]+=140-min(140,80+(height+1)//2)
            for row in range(20,140):world.update(pixels[row*320+40:row*320+280])
        view_counts = world.copy()
        wall_counts, wall_faces = wall_histogram(level['planes'][0], pages, base)
        coverage_share = WORLD_CONVERSION.get('wall_coverage_share', .20)
        world = world_distribution(world, wall_counts, coverage_share)
        groups=floor_shapes(level)
        for shapes,counter in ((groups[0]|groups[1],sprite_counts),(groups[2],weapon_counts)):
            for number in shapes:
                for col in sprite(pages[base+number])['columns']:
                    for a,b,raw in col:counter.update(raw)
        flat_weights={c:(1-coverage_share)*count/sum(view_counts.values()) for c,count in flat_counts.items()}
        targets,weights,solid=fitting_targets(world,sprite_counts,weapon_counts,pal,flat_weights)
        legacy_targets,_,_=fitting_targets(view_counts,sprite_counts,weapon_counts,pal)
        colors=vc.kmeans([(t,w) for t,w,_ in legacy_targets],fixed=FIXED)
        if args.seed_palettes:
            seed=json.loads((args.seed_palettes/(str(n)+'.json')).read_text())['palette']
            colors=seed_colors(seed)
        else:
            colors=vc.Search(legacy_targets,metric).run(colors,12)
        baseline=ordered_colors(colors)
        baseline_walls,baseline_sprites=light_maps(pal,baseline,metric)
        colors=vc.Search(targets,metric,solid).run(colors,12)
        # Align before conversion. Every comparison uses actual generated cells.
        ordered=ordered_colors(colors)
        if ordered==baseline:
            wall_lights,sprite_lights=baseline_walls,baseline_sprites
        else:
            wall_lights,sprite_lights=light_maps(pal,ordered,metric)
        wall_views=view_counts-flat_counts
        domains=(('views',wall_views,'wall',1),('walls',wall_counts,'wall',1),
                 ('background',flat_counts,'flat',1),
                 ('sprites',sprite_counts,'sprite',.75),('weapons',weapon_counts,'weapon',.75))
        before=conversion_scores(pal,baseline,baseline_walls,baseline_sprites,LIGHT_GAINS,domains,metric)
        after=conversion_scores(pal,ordered,wall_lights,sprite_lights,LIGHT_GAINS,domains,metric)
        retained=no_regression(before,after)
        if not retained:
            ordered,wall_lights,sprite_lights=baseline,baseline_walls,baseline_sprites
        quality=dict(baseline=before,candidate=after,coverage_candidate_retained=retained,
                     colors_changed=ordered!=baseline)
        mixes=vc.Mixes(ordered,metric)
        ab=wall_lights[-1];spr=sprite_lights[-1]
        report=dict(floor=n+1,palette=[list(map(lambda v:v*17,c)) for c in ordered],wall_ab=ab,sprite_ab=spr,wall_pair=[mixes.pair_for(c) for c in pal],sprite_pair=[mixes.pair_for(c) for c in pal],
                    wall_lights=wall_lights,sprite_lights=sprite_lights,light_gains=LIGHT_GAINS,palette_fit_gains=FIT_GAINS,
                    samples=len(poses),weights=weights,source_shapes=[sorted(g) for g in groups],
                    wall_coverage_share=coverage_share,wall_faces=dict(sorted(wall_faces.items())),
                    quality=quality,flat_world_weights=flat_weights)
        target.write_text(json.dumps(report,separators=(',',':'))+'\n')
        print('floor',n+1,'palette',' '.join('%X%X%X'%c for c in ordered),flush=True)

if __name__=='__main__':main()
