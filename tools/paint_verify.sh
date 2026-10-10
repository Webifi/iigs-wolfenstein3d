#!/bin/bash
# One verification round of a paint step against a baseline: pictures at 214/320 (paint_check + paint_compare),
# 160/240 captures of demos 0 and 1, the mid-frame check (paint_twice) and a crash report check. About 15 minutes.
# usage: tools/paint_verify.sh NAME BASEFULL BASEOTHER DISK ELF
#   BASEFULL / BASEOTHER: test directories under build/tests of the baseline (a paint_check run of all demos at 214 and 320,
#   and a --views 160 240 --demos 0 1 --capture-only run). DISK must be newer than ELF (touch a preserved copy).
# Results: build/NAME-{full,compare,other,other-compare,twice,ips}.log, build/NAME-done.flag, docs/evidence/paint2/NAME-*.json
cd "$(dirname "$0")/.." || exit 1
NAME=$1; BASEFULL=$2; BASEOTHER=$3; DISK=$4; ELF=$5
ls ~/Library/Logs/DiagnosticReports/ | grep "^iigs-" | sort > build/ips_before_$NAME.txt
nice -n 20 python3 tools/paint_check.py $NAME-full $DISK $ELF > build/$NAME-full.log 2>&1; echo "full exit $?" >> build/$NAME-full.log
python3 tools/paint_compare.py build/tests/$BASEFULL build/tests/$NAME-full docs/evidence/paint2/$NAME-compare.json > build/$NAME-compare.log 2>&1; echo "compare exit $?" >> build/$NAME-compare.log
nice -n 20 python3 tools/paint_check.py $NAME-other $DISK $ELF --views 160 240 --demos 0 1 --capture-only > build/$NAME-other.log 2>&1; echo "other exit $?" >> build/$NAME-other.log
python3 - <<PY > build/$NAME-other-compare.log 2>&1
import mmap,json
cases=[]
for c in ('d0-v160','d1-v160','d0-v240','d1-v240'):
    a=open(f'build/tests/$BASEOTHER/{c}/0/frames.shr','rb');b=open(f'build/tests/$NAME-other/{c}/0/frames.shr','rb')
    ma=mmap.mmap(a.fileno(),0,access=mmap.ACCESS_READ);mb=mmap.mmap(b.fileno(),0,access=mmap.ACCESS_READ)
    assert len(ma)==len(mb)
    n=len(ma)//32768
    px=[i+1 for i in range(n) if ma[i*32768:i*32768+32000]!=mb[i*32768:i*32768+32000]]
    pal=[i+1 for i in range(n) if ma[i*32768+32000:(i+1)*32768]!=mb[i*32768+32000:(i+1)*32768]]
    cases.append(dict(case=c,frames=n,pixel_difference_frames=px,palette_phase_frames=pal))
    print(c,'frames',n,'pixel-different',px,'palette',pal)
json.dump(dict(before='$BASEOTHER',after='$NAME-other',cases=cases),open('docs/evidence/paint2/$NAME-other-views.json','w'),indent=2)
open('docs/evidence/paint2/$NAME-other-views.json','a').write('\n')
PY
nice -n 20 python3 tools/paint_twice.py $NAME-twice $DISK $ELF > build/$NAME-twice.log 2>&1; echo "twice exit $?" >> build/$NAME-twice.log
sleep 2
ls ~/Library/Logs/DiagnosticReports/ | grep "^iigs-" | sort | diff build/ips_before_$NAME.txt - | grep '^>' > build/$NAME-ips.log; echo "ips done" >> build/$NAME-ips.log
echo ALLDONE > build/$NAME-done.flag
