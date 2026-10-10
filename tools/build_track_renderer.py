#!/usr/bin/env python3
"""Build a headless Nuked-SC55 renderer with the complete-track mixer tap.

Uses an existing jcmoyer source tree and a C++23 compiler. ROMs are neither read
nor copied. The input tree is read-only; patched sources and objects go to --out.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def apply_patch(source,patch):
    """Apply exact-context unified hunks, without relying on a shell patch tool."""
    lines=patch.splitlines(keepends=True);i=0;files=[]
    while i<len(lines):
        if not lines[i].startswith('--- a/'):
            raise ValueError('expected a unified patch source path')
        name=lines[i][6:].strip();i+=1
        if lines[i].strip()!='+++ b/'+name:raise ValueError('patch path mismatch')
        i+=1;original=(source/name).read_text().splitlines(keepends=True);result=[];at=0
        while i<len(lines) and lines[i].startswith('@@'):
            match=re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@',lines[i])
            if not match:raise ValueError('invalid patch hunk')
            start=int(match[1])-1
            if start<at:raise ValueError('overlapping patch hunks')
            result+=original[at:start];at=start;i+=1
            while i<len(lines) and lines[i][:1] in (' ','+','-') and not lines[i].startswith('--- a/'):
                row=lines[i];i+=1
                if row[0] in (' ','-'):
                    if at>=len(original) or original[at]!=row[1:]:
                        raise ValueError('source differs from the supported renderer patch at '+name+':'+str(at+1))
                    at+=1
                if row[0] in (' ','+'):result.append(row[1:])
        result+=original[at:];files.append((name,''.join(result)))
    return files


def build(args):
    source=args.source.resolve();out=args.out.resolve()
    if source==out or source in out.parents or out in source.parents:
        raise ValueError('--out must be separate from the original renderer source tree')
    patch=(Path(__file__).parent/'sc55/track-capture.patch').read_text()
    changes=apply_patch(source,patch)
    local=out/'source';local.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source/'src',local/'src',dirs_exist_ok=True)
    shutil.copyfile(source/'LICENSE',out/'LICENSE')
    for name,text in changes:(local/name).write_text(text)
    obj=out/'obj';(obj/'backend').mkdir(parents=True,exist_ok=True)
    version=re.search(r'project \(nuked-sc55 VERSION ([0-9.]+)',(source/'CMakeLists.txt').read_text())[1]
    parts=version.split('.')
    config=(local/'src/backend/config.h.in').read_text()
    replacements={'#cmakedefine01 NUKED_ENABLE_ASIO':'#define NUKED_ENABLE_ASIO 0',
                  '#cmakedefine01 NUKED_ENABLE_DECODER2':'#define NUKED_ENABLE_DECODER2 1',
                  '@CMAKE_PROJECT_VERSION@':version,'@NUKED_SOURCE@':'complete-track mixer capture v1'}
    replacements.update({'@CMAKE_PROJECT_VERSION_'+k+'@':v for k,v in zip(('MAJOR','MINOR','PATCH'),parts)})
    for before,after in replacements.items():config=config.replace(before,after)
    (obj/'backend/config.h').write_text(config)
    compiler=shutil.which(args.cxx)
    cc=shutil.which(args.cc)
    if not compiler or not cc:raise ValueError('install a C++23 compiler (Clang or GCC) and set --cxx/--cc')
    inputs=[]
    for folder in ('backend','backend/decoder2','common','renderer'):
        inputs+=sorted((local/'src'/folder).glob('*.cpp'))
    includes=['-I'+str(local/'src'/p) for p in ('','backend','common')]+['-I'+str(obj),'-I'+str(obj/'backend')]
    def compile_one(path):
        dest=obj/(path.relative_to(local).as_posix().replace('/','_')+'.o')
        command=[compiler,'-std=c++23','-O2','-DNDEBUG','-include','cstddef','-include','cstdlib',*includes,'-c',str(path),'-o',str(dest)]
        subprocess.run(command,check=True)
        return dest
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:objects=list(pool.map(compile_one,inputs))
    sha_obj=obj/'sha.o'
    subprocess.run([cc,'-O2','-c',str(local/'src/backend/sha/sha224-256.c'),'-o',str(sha_obj)],check=True)
    exe=out/('nuked-sc55-track-render'+('.exe' if os.name=='nt' else ''))
    subprocess.run([compiler,*map(str,objects),str(sha_obj),'-o',str(exe)],check=True)
    identity=dict(version=version,patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                  renderer_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                  compiler=subprocess.check_output([compiler,'--version'],text=True).splitlines()[0],
                  source_files={p.relative_to(local).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((local/'src').rglob('*')) if p.is_file()},
                  baseline_equivalence_verified=False)
    (out/'build.json').write_text(json.dumps(identity,indent=2)+'\n')
    print(exe)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--cxx',default='clang++' if sys.platform=='darwin' else 'g++')
    parser.add_argument('--cc',default='clang' if sys.platform=='darwin' else 'gcc')
    parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args()
    if not 1<=args.jobs<=32:parser.error('--jobs must be between 1 and 32')
    build(args)
