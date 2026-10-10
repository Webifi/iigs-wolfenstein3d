"""Rebuild the small DOS IMF player using LLVM, without embedding music."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm-bin',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=Path(__file__).with_name('sb_imf_player.com'))
    args=parser.parse_args()
    import os
    suffix='.exe' if os.name=='nt' else ''
    def tool(name):
        p=args.llvm_bin/(name+suffix)
        if not p.is_file():raise ValueError('Missing LLVM tool: '+str(p))
        return str(p)
    with tempfile.TemporaryDirectory(prefix='sb-player-') as temp:
        obj=Path(temp)/'player.o';raw=Path(temp)/'player.raw'
        subprocess.run([tool('llvm-mc'),'-triple=i386-pc-none','-filetype=obj',
                        str(Path(__file__).with_name('sb_imf_player.s')),'-o',str(obj)],check=True)
        relocations=subprocess.check_output([tool('llvm-objdump'),'-r',str(obj)],text=True)
        rows=[line.split() for line in relocations.splitlines() if re.match(r'^[0-9a-f]{8}\s',line)]
        # Absolute 16-bit references all target .text at address0. Their
        # addends already contain the COM origin; no external linking is needed.
        if not rows or any(row[1:]!=['R_386_16','.text'] for row in rows):
            raise ValueError('Unexpected DOS player relocation; refusing an unlinked binary')
        subprocess.run([tool('llvm-objcopy'),'-O','binary','--only-section=.text',str(obj),str(raw)],check=True)
        data=raw.read_bytes()
        if any(data[:256]) or len(data)>65536:raise ValueError('Invalid COM origin or length')
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_bytes(data[256:])
        print(args.out)


if __name__=='__main__':main()
