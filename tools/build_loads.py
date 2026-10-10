"""Explicit live-asset loads for separate art and ray-table banks."""
from wolfdata import ROOT, PROFILE
from buildconfig import config
def main():
    from registered_loads import boot_rows
    from sight_rooms import prepare_all
    prepare_all(ROOT, PROFILE.floors, config()['floor']-1)
    loads=boot_rows()
    (ROOT/'build/assets/load-list.txt').write_text(''.join(str(p.relative_to(ROOT))+'@0x%06x\n'%a for a,p in sorted(loads)))

if __name__=='__main__':main()
