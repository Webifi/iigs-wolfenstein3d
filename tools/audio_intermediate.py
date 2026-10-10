"""Portable, editable inputs for rebuilding music without synthesizer tools.

The package contains source-relative score edits, PCM sources, instrument
generators and capture receipts. It never contains complete scores, DOC banks,
native command streams or full-song audio.
"""
import array
import copy
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import wave

from audio_package import sha, checked, write_toml, contained, validate_dos, validate_effects
from game_profile import read_toml


def export_model(font_path, midi, target):
    from music_score import midi_notes
    """Retain used instrument regions and exact source PCM, not the SF2 file."""
    import sf2
    from sample_model import resolve
    sf=sf2.SF2(str(font_path))
    source_hash=sha(Path(font_path).read_bytes())
    programs=sorted({(128 if n['channel']==10 else 0,n['program']-1) for n in midi_notes(midi)})
    presets=[];samples=set()
    for bank,program in programs:
        modeled=resolve(sf,bank,program,source_hash)
        index,name=sf.presets[bank,modeled]
        pz=sf._zones(sf.pbag,sf.pgen,sf.phdr[index][3],sf.phdr[index+1][3])
        pg=pz[0] if pz and 'instrument' not in pz[0] else {}
        rows=[]
        for p in pz:
            if 'instrument' not in p:continue
            i=p['instrument'];iz=sf._zones(sf.ibag,sf.igen,sf.inst[i][1],sf.inst[i+1][1])
            ig=iz[0] if iz and 'sampleID' not in iz[0] else {}
            for z in iz:
                if 'sampleID' not in z:continue
                g=dict(sf2.DEFAULTS);g.update(ig);g.update(z)
                for k,v in list(pg.items())+list(p.items()):
                    if k not in ('keyRange','velRange','instrument'):g[k]=g.get(k,0)+v
                ranges={}
                for field in ('keyRange','velRange'):
                    a,b=p.get(field,(0,127)),z.get(field,(0,127))
                    ranges[field]=[max(a[0],b[0]),min(a[1],b[1])]
                samples.add(g['sampleID'])
                rows.append(dict(keys=ranges['keyRange'],velocities=ranges['velRange'],generators=g))
        preset=dict(bank=bank,program=program,name=name,regions=rows)
        if modeled!=program:preset['model_program']=modeled
        presets.append(preset)
    entries=[]
    target.mkdir(parents=True,exist_ok=True)
    for sid in sorted(samples):
        s=sf.sample(sid);path=target/f'sample-{sid:04}.wav'
        pcm=array.array('h',(round(v*32768) for v in s.data))
        if sys.byteorder!='little':pcm.byteswap()
        with wave.open(str(path),'wb') as f:
            f.setparams((1,2,s.rate,0,'NONE','not compressed'));f.writeframes(pcm.tobytes())
        entries.append(dict(id=sid,file=path.name,sha256=sha(path.read_bytes()),
                            **{k:v for k,v in vars(s).items() if k!='data'}))
    write_toml(target/'model.toml',dict(format=1,source_sha256=sha(Path(font_path).read_bytes()),
        samples=entries,presets=presets),'# Original sample regions and envelopes. PCM is stored in the adjacent WAV files.')


class ModelFont:
    """The same region calculation, using preserved PCM and generator data."""
    def __init__(self,path):
        self.root=path.parent;self.document=read_toml(path)
        if self.document['format']!=1:raise ValueError('unsupported instrument model')
        self.presets={(p['bank'],p['program']):(i,p['name']) for i,p in enumerate(self.document['presets'])}
        self.rows={(p['bank'],p['program']):p['regions'] for p in self.document['presets']}
        self.entries={s['id']:s for s in self.document['samples']};self.samples={}

    def sample(self,sid):
        if sid not in self.samples:
            import sf2
            row=self.entries[sid];path=contained(self.root,row['file']);checked(path,row['sha256'])
            with wave.open(str(path)) as f:
                if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(1,2,row['rate']):
                    raise ValueError('preserved instrument WAV format changed')
                pcm=array.array('h',f.readframes(f.getnframes()))
            if sys.byteorder!='little':pcm.byteswap()
            s=sf2.Sample()
            for k,v in row.items():
                if k not in ('id','file','sha256'):setattr(s,k,v)
            s.data=[v/32768 for v in pcm];self.samples[sid]=s
        return self.samples[sid]

    def regions(self,bank,program,key,velocity):
        import sf2
        return [sf2.region(self,copy.deepcopy(r['generators']),key)
                for r in self.rows.get((bank,program),[])
                if r['keys'][0]<=key<=r['keys'][1] and r['velocities'][0]<=velocity<=r['velocities'][1]]


def note_key(note,root):
    return (note['channel'],note['tick'],note['key'],note['velocity'],root)


class PreservedSong:
    def __init__(self,package,name,midi):
        self.package=Path(package).resolve()
        manifest=read_toml(self.package/'intermediate.toml')
        if manifest['format']!=2:raise ValueError('unsupported intermediate package')
        self.root=contained(self.package,'inputs/'+name)
        self.meta=read_toml(self.root/'inputs.toml')
        from audio_defaults import performance_identity
        if performance_identity(midi)!=self.meta['performance_sha256']:
            raise ValueError('performed score or instruments changed; regenerate the intermediate captures')
        self.model=self.root/'model/model.toml'
        self.font=ModelFont(self.model)


class PreservedSources:
    def __init__(self,sampler,song):
        self.sampler,self.song=sampler,song
        self.records={tuple(r['note']):r for r in song.meta['captures']}
        sampler.performed_pan=song.meta.get("performed_pan",[])

    def prepare(self,zones):
        self.sampler.unavailable_captures={tuple(row) for row in self.song.meta['unavailable']}

    def extract(self,zone,note,root):
        row=self.records.get(note_key(note,root))
        if row is None:
            raise ValueError('this tuning requires an uncaptured played note; regenerate the intermediate package with the synthesis setup')
        path=contained(self.song.root,row['file']);checked(path,row['sha256'])
        meta=read_toml(path.with_suffix('.toml'))
        # The existing reducers consume JSON receipts beside source WAVs.
        target=self.sampler.out/'captures'/path.name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        target.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
        return target,row['identity'],meta


def export_song(package,recipe,midi,font,sampler,info):
    """Save upstream inputs. No generated bank/command/preview output is copied."""
    package=Path(package);doc=copy.deepcopy(read_toml(recipe));name=doc['name']
    target=package/'inputs'/name;target.mkdir(parents=True,exist_ok=True)
    from audio_score_delta import derive,write
    from audio_defaults import performance_identity
    raw=checked(recipe.parent/doc['original']['file'],doc['original']['sha256'])
    pair_catalog=read_toml(Path(__file__).resolve().parents[1]/'profiles/audio/reference-pairs.toml')
    pairs=next((p['part'] for p in pair_catalog['song'] if p['imf_sha256']==sha(raw)),[])
    delta=derive(raw,midi,pairs);write(target/'score.toml',delta)
    selection=dict(instruments=info['selected_instruments'],source=doc['source'],
                   changes=doc.get('change',[]))
    selection['source']=dict(selection['source'])
    selection['source'].pop('file',None)
    if 'defaults' in doc:
        selection['defaults']=read_toml(recipe.parent/doc['defaults']['file'])
    write_toml(target/'selection.toml',selection,
        '# Selection provenance. The chosen instruments are applied by score.toml.\n'
        '# Change instruments in the synthesis recipe and export again to obtain matching captures.')
    export_model(font,midi,target/'model')
    # The selected performance is frozen; instrument changes require recapture.
    doc.pop('defaults',None);doc.pop('change',None);doc.pop('instrument',None)
    doc['source'].update(kind='imf-delta',file='../inputs/'+name+'/score.toml',sha256=sha((target/'score.toml').read_bytes()))
    doc['original']['file']='../licensed/'+name+'.imf'
    source_policy=(getattr(sampler,'policy_path',None) or Path(__file__).resolve().parents[1]/'profiles/audio/sampling-defaults.toml')
    shutil.copy2(source_policy,target/'sampling.toml')
    doc['doc']['sampling_policy']='../inputs/'+name+'/sampling.toml'
    # Full performances and solo-track renders are developer diagnostics, not
    # portable inputs. Freeze the final measured calibration instead.
    balance=info.get('automatic_balance',{})
    for key,value in balance.get('calibration',{}).items():
        if key!='captures':doc['doc'][key]=copy.deepcopy(value)
    doc['doc']['auto_balance']=False
    doc['doc']['level_mode']=info.get('level_mode','legacy')
    records=[]
    for key,(path,identity,meta) in sorted(sampler.track_sources.extractions.items()):
        to=target/'captures'/path.name;to.parent.mkdir(exist_ok=True);shutil.copy2(path,to)
        write_toml(to.with_suffix('.toml'),meta)
        records.append(dict(note=list(key),file='captures/'+path.name,sha256=sha(to.read_bytes()),identity=identity))
    # Explicit prepared WAV overrides also belong to the portable input set.
    for i,spec in enumerate(doc['doc'].get('capture',[])):
        if 'wav' in spec:
            original=(recipe.parent/spec['wav']).resolve();to=target/'captures'/f'explicit-{i:02}.wav'
            to.parent.mkdir(exist_ok=True);shutil.copy2(original,to)
            shutil.copy2(original.with_suffix('.json'),to.with_suffix('.json'))
            spec.update(wav='../inputs/'+name+'/captures/'+to.name,sha256=sha(to.read_bytes()))
    write_toml(package/'songs'/(name+'.toml'),doc,
        '# Editable offline recipe: levels, pan, quality, captures and per-sample overrides.\n'
        '# The original AdLib source is supplied through --data; it is not bundled here.')
    write_toml(target/'inputs.toml',dict(format=2,midi_sha256=sha(midi),performance_sha256=performance_identity(midi),
        font_source_sha256=info['font_sha256'],original_sha256=doc['original']['sha256'],
        expected_bank_sha256=info['cold_sha256'],
        compiler_sources=info['compiler_sources'],
        unavailable=[list(x) for x in sorted(getattr(sampler,'unavailable_captures',set()))],
        captures=records,performed_pan=getattr(sampler,'performed_pan',[])),
        '# Capture identities and references. expected_bank_sha256 is a comparison receipt, not bank data.')


def finish_package(package,game):
    for name in game.required_music.values():
        read_toml(package/'inputs'/name/'inputs.toml')
    write_toml(package/'intermediate.toml',dict(format=2,profile=game.key,
        songs=[dict(id=i,name=name) for i,name in game.required_music.items()]),
        '# Rebuild with audio_compile.py music-pack THIS_FOLDER --data YOUR_DOS_FILES --out OUTPUT.\n'
        '# No Roland executable, ROM, SoundFont, DOC bank or native music stream is included.')


def export_effects(package,samples,game,data,shared=None):
    """Preserve rendered source effects, before resident-bank layout/packing."""
    from dos_data import DosData
    chunks=DosData(data,game.key,shared).audio()
    target=package/'effects/ym3812';target.mkdir(parents=True,exist_ok=True)
    entries=[]
    for path in sorted(samples.glob('*.u8')):
        ident=int(path.stem)
        if not 0<=ident<game.sounds:raise ValueError('effect outside profile')
        to=target/path.name;shutil.copy2(path,to)
        entries.append(dict(id=ident,file=path.name,sha256=sha(to.read_bytes()),
                            original_sha256=sha(chunks[game.sounds+ident])))
    if not entries:raise ValueError('missing rendered AdLib effect sources')
    write_toml(target/'samples.toml',dict(format=1,samples=entries),
        '# Unsigned 8-bit mono source effects at 7042.65625 Hz, before resident-bank packing.')
