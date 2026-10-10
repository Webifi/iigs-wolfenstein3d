"""Render a fixed-key percussion pitch sweep into its waveform, keeping level envelopes live."""
import math
import mussc
import musdsp

def install(song):
    reports=[]
    for z in song.zones:
        if not z.notes or any(n.preset!=(0,118) for n in z.notes):continue
        speeds={round(n.sp,12) for n in z.notes}
        if len(speeds)!=1 or any(any(b for _,b in n.bends) for n in z.notes):
            raise ValueError('sweep baking needs distinct fixed-key tables for MIDI bends')
        speed=z.notes[0].sp;old_rate=z.rate;old_loop=list(z.float_lt);old_attack=list(z.float_tab)
        old_gain=z.gain;cap=mussc.SWEEP_MAX/mussc.SWEEP[118]
        longest=max(n.stop-n.on+2 for n in z.notes)/140
        end=min(longest,math.ceil(cap*140)/140+2/140)
        fc=max(1,round(512*old_rate*speed/8/mussc.DOC_RATE))
        rate=fc*mussc.DOC_RATE/512
        count=math.ceil(end*mussc.DOC_RATE)+64
        values=[];phase=0.;k=mussc.SWEEP[118]*math.log(2)/12
        switch=math.ceil(cap*140)
        attack_end=min(len(old_attack)-1,z.attack*old_rate)
        for i in range(count):
            t=i/mussc.DOC_RATE
            j=int(phase);f=phase-j
            if phase<attack_end:
                a=old_attack[min(j,len(old_attack)-1)];b=old_attack[min(j+1,len(old_attack)-1)]
            else:
                a=old_loop[j%len(old_loop)];b=old_loop[(j+1)%len(old_loop)]
            values.append(a+(b-a)*f)
            # Use the same 39-semitone fall, with a smooth trajectory instead of half-semitone steps.
            phase+=rate*max(1.,8*math.exp(-k*t))/mussc.DOC_RATE
        table=musdsp.resample(values,mussc.DOC_RATE,rate,taps=24)[:math.ceil(end*rate)]
        looping=longest>cap
        loop=[]
        if looping:
            phase_cap=rate*8*(1-math.exp(-k*cap))/k
            offset=phase_cap-rate*cap
            for i in range(len(old_loop)):
                p=i+offset;j=math.floor(p);f=p-j
                loop.append(old_loop[j%len(old_loop)]*(1-f)+old_loop[(j+1)%len(old_loop)]*f)
        z.kind='attack' if looping else 'oneshot'
        z.nat=0.;z.nat_len=0.;z.native=False
        z.loop_len=len(loop);z.attack=switch/140;z.s_mid=1.;z.s_min=z.s_max=1.
        z.exact_fc=fc;z.baked_attack_tics=switch if looping else 0;z.attack_rate=rate
        song.finish(z,table,loop,rate)
        for n in z.notes:n.sp=1.;n.freqs=[(n.on,1.)]
        reports.append(dict(instrument=118,key=z.notes[0].key,notes=sum(n.half==0 for n in z.notes),longest_seconds=longest,
                            pages_before=(len(old_attack)+len(old_loop)+255)//256,pages_after=(len(z.table)+len(z.ltable)+255)//256,
                            rate=rate,frequency=fc,looping=looping,held_level_change_db=(z.gain-old_gain)*6.02/32,
                            level_envelope='unchanged live DOC volume envelope',sweep_semitones_per_second=mussc.SWEEP[118]))
    if reports:
        song.layout()
        if song.low<64:raise ValueError('baked sweep exceeds music pages')
    song.baked_sweeps=reports
