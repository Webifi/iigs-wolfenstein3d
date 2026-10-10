"""Build-time two-operator patch sampling from Yamaha's application manual.

This is an analytic sampled-instrument rendition, not a cycle-exact YM3812.
Envelope rates, multipliers, levels and feedback follow the retained manual;
continuous phase/level arithmetic replaces the chip's internal quantization.
"""
import math
from wolfaudio import OPL_RATE

MULT=(.5,1,2,3,4,5,6,7,8,9,10,10,12,12,15,15)
FB=(0,math.pi/16,math.pi/8,math.pi/4,math.pi/2,math.pi,math.tau,2*math.tau)
KSL=(0,9,12,13.875,15,16.125,16.875,17.625,18,18.75,19.125,19.5,19.875,20.25,20.625,21)


def wave(phase,kind):
    phase%=math.tau
    s=math.sin(phase)
    if kind==0:return s
    if kind==1:return max(0,s)
    if kind==2:return abs(s)
    return abs(s) if phase%math.pi < math.pi/2 else 0


def attenuation(db):
    return 10**(-db/20)


def scale_level(scale,fnum,block):
    return (scale&63)*.75+max(0,KSL[fnum>>6]-3*(7-block))*(0,1,.5,2)[scale>>6]


def rate_seconds(n,character,fnum,block,attack=False):
    if not n:return math.inf
    key=block*2+(fnum>>9)
    rate=min(63,4*n+(key if character&16 else key//4))
    whole,part=divmod(rate,4)
    if attack and whole==15:return 0
    # Full 0-100% times, manual Table 3-6, interpolated by subrate.
    return (2.82624 if attack else 39.28064)*2**(1-whole)/(1,1.25,1.5,1.75)[part]


class Envelope:
    def __init__(self):
        self.db=96.;self.stage='off';self.key=False

    def gate(self,on):
        if on and not self.key:self.stage='attack'
        elif not on and self.key:self.stage='release'
        self.key=on

    def advance(self,dt,char,ad,sr,fnum,block):
        sustain=93 if sr>>4==15 else (sr>>4)*3
        if self.stage=='attack':
            seconds=rate_seconds(ad>>4,char,fnum,block,True)
            if not seconds:self.db=0
            elif math.isfinite(seconds):
                used=min(dt,math.log(self.db+1)*seconds/math.log(97))
                self.db=max(0,(self.db+1)*math.exp(-used*math.log(97)/seconds)-1)
                dt-=used
            if self.db<1e-8:self.db=0;self.stage='decay'
        if self.stage=='decay':
            speed=96/rate_seconds(ad&15,char,fnum,block)
            used=min(dt,max(0,sustain-self.db)/speed) if speed else dt
            self.db+=used*speed;dt-=used
            if self.db>=sustain:self.db=sustain;self.stage='sustain'
        if self.stage=='release' or self.stage=='sustain' and not char&32:
            self.db+=dt*96/rate_seconds(sr&15,char,fnum,block)
        self.db=min(96,self.db)
        return self.db


def render_effect(effect,rate=7000):
    p=effect['patch'];env=[Envelope(),Envelope()];phase=[0.,0.]
    block=effect['block'];out=[];notes=effect['notes']
    rate*=4;last_fnum=0
    # ID_SD feeds one f-number byte at 140 Hz and keys off at the end.
    for n in range(round((len(notes)/140+.04)*rate)):
        step=n*140//rate;fnum=notes[step] if step<len(notes) else 0
        if fnum:last_fnum=fnum
        freq=OPL_RATE*last_fnum*2**(block-20)
        levels=[]
        for op in range(2):
            env[op].gate(bool(fnum))
            db=env[op].advance(1/rate,p[op],p[4+op],p[6+op],last_fnum,block)
            if p[op]&128:db+=(1-math.cos(n/rate*math.tau*3.7))*.5
            levels.append(attenuation(db+scale_level(p[2+op],last_fnum,block)))
            vibrato=2**(7*math.sin(n/rate*math.tau*6.4)/1200) if p[op]&64 else 1
            phase[op]+=math.tau*freq*MULT[p[op]&15]*vibrato/rate
        mod=wave(phase[0],p[8]&3)*levels[0]
        # SDL_AlSetFXInst deliberately sets C0=0, ignoring patch nConn.
        value=wave(phase[1]+mod*8*math.pi,p[9]&3)*levels[1]
        out.append(value)
    return pcm(sum(out[n:n+4])/4 for n in range(0,len(out),4))


def pcm(values):
    return bytes(max(1,min(255,round(128+v*110))) for v in values)


def cycle(p,mod_db):
    # Two fundamental periods retain MULT=1/2. Eightfold integration limits
    # aliasing in the 256-byte table; prior periods settle feedback.
    over=8;count=256*over;values=[];last=prior=0.
    level=attenuation(mod_db+(p[2]&63)*.75)
    for n in range(count*4):
        phase=n/count*2*math.tau
        mod=wave(phase*MULT[p[0]&15]+(last+prior)*.5*FB[(p[10]>>1)&7],p[8]&3)*level
        value=wave(phase*MULT[p[1]&15]+(0 if p[10]&1 else mod*8*math.pi),p[9]&3)
        if p[10]&1:value=(value+mod)*.5
        prior,last=last,mod
        if n>=count*3:values.append(value)
    return pcm(sum(values[n:n+over])/over for n in range(0,count,over))
