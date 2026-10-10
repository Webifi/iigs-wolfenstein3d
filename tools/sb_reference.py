"""Developer-only original IMF reference through DOSBox-X's Sound Blaster 16."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import wave
from audio_build_cache import digest

PIT_HZ = 1193182
PIT_DIVISOR = 1702

PLAYER = Path(__file__).with_name('sb_imf_player.com')


def render(source, executable, out, expected):
    source, executable, out = (Path(p).resolve() for p in (source,executable,out))
    if digest(source) != expected:
        raise ValueError('Original IMF source does not match its recipe')
    raw = source.read_bytes()
    if len(raw) < 6:
        raise ValueError('Truncated IMF source')
    size = struct.unpack_from('<H',raw)[0]
    if not size or size%4 or size+2>len(raw):
        raise ValueError('Invalid original IMF length')
    events = list(struct.iter_unpack('<BBH',raw[2:2+size]))
    seconds = (sum(row[2] for row in events[:-1])+1)*PIT_DIVISOR/PIT_HZ
    if any(x in str(out) for x in ('"','\n','\r')):
        raise ValueError('Capture path contains characters unsupported by DOSBox mount')
    out.mkdir(parents=True,exist_ok=True)
    if list(out.glob('*.wav')):
        raise ValueError('Sound Blaster renderer needs a fresh capture directory')
    # The small supplied DOS player follows Wolf's register/timer and mixer
    # setup. The DOSBox card and mixer produce the WAV, not a raw OPL core.
    shutil.copyfile(PLAYER,out/'PLAYER.COM')
    (out/'MUSIC.IMF').write_bytes(raw[:size+2])
    config = f'''[sdl]
fullscreen=false
output=surface
showmenu=false
[dosbox]
machine=svga_s3
memsize=16
captures={out}
[cpu]
core=normal
cycles=fixed 20000
[mixer]
rate=49716
nosound=false
[sblaster]
sbtype=sb16
sbmixer=true
oplmode=auto
oplemu=nuked
oplrate=49716
[midi]
mpu401=none
[ne2000]
ne2000=false
[autoexec]
mount c "{out}"
c:
dx-capture /a /-d PLAYER.COM
if errorlevel 1 echo FAIL > STATUS.TXT
if not errorlevel 1 echo PASS > STATUS.TXT
exit
'''
    (out/'dosbox.conf').write_text(config)
    # DOSBox-X -silent disables the Sound Blaster itself. Dummy SDL drivers
    # suppress host playback/window creation while leaving the card active.
    command = [str(executable),'-fastlaunch','-exit','-nogui','-conf',str(out/'dosbox.conf')]
    with (out/'dosbox.log').open('w') as log:
        subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT,check=True,
                       timeout=seconds*2+45,env=dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_VIDEODRIVER='dummy'))
    recordings = list(out.glob('*.wav'))
    if (out/'STATUS.TXT').read_text().strip() != 'PASS' or len(recordings) != 1:
        raise ValueError('Sound Blaster capture failed; see '+str(out/'dosbox.log'))
    wav = recordings[0]
    with wave.open(str(wav),'rb') as stream:
        frames,rate,channels,width = stream.getnframes(),stream.getframerate(),stream.getnchannels(),stream.getsampwidth()
        pcm = stream.readframes(frames)
    if (rate,channels,width)!=(49716,2,2) or abs(frames/rate-seconds) > .25:
        raise ValueError('Sound Blaster capture format or complete-loop timing differs')
    samples = [x[0] for x in struct.iter_unpack('<h',pcm)]
    peak = max(map(abs,samples),default=0)
    if not peak or peak>=32767:
        raise ValueError('Sound Blaster capture is silent or clipped; no gain correction was applied')
    target=out/'soundblaster.wav'
    wav.rename(target)
    receipt = dict(kind='original-imf-soundblaster-emulation',source_sha256=expected,
        source_music_bytes_sha256=digest(out/'MUSIC.IMF'),player_sha256=digest(PLAYER),
        player_source_sha256=digest(PLAYER.with_suffix('.s')),
        emulator_sha256=digest(executable),configuration_sha256=digest(out/'dosbox.conf'),
        card='Sound Blaster 16',opl='Nuked OPL3 in AdLib-compatible mode',
        fm_mixer_register_26=255,pit_divisor=PIT_DIVISOR,rate=rate,channels=channels,
        frames=frames,seconds=frames/rate,peak=peak,wav_sha256=digest(target),
        normalization=False,added_gain_db=0,compression=False,limiting=False,
        developer_only=True,used_for_doc_conversion=False,physical_recording=False)
    (out/'soundblaster.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return target,receipt
