"""The native reductions must preserve the scalar compiler's exact values."""
import math
import os
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).parent/'doccompiler'))
import audio_numeric as fast
import audio_dsp
import audio_fit
import audio_timbre
import capture_tone


class NumericTests(unittest.TestCase):
    def test_reused_body_features(self):
        rate=8000.;period=rate/440
        source=[math.sin(i*2*math.pi/period)*math.exp(-i/12000) for i in range(4800)]
        baseline=(640,period,256,3,256*rate/round(period*3))
        cache={}
        for values,holds,attack in ((source,(.15,.4),.1),(source,(.2,.5),.06),
                                    ([v+.2*math.sin(i*.4) for i,v in enumerate(source)],(.2,.5),.06)):
            args=(values,rate,69,0,1.,1.2,holds,attack,baseline)
            self.assertEqual(audio_timbre.match_body(*args,cache=cache),
                             audio_timbre.match_body(*args,cache={}))

    def test_prefix_and_quantization(self):
        rng=random.Random(314)
        values=[rng.uniform(-2,2) for _ in range(16000)]+[i+.5 for i in range(-128,128)]
        prefix=[0.]
        for v in values:prefix.append(prefix[-1]+v*v)
        self.assertEqual(list(fast.prefix_energy(values)),prefix)
        for peak in (127.,128.,1.73):
            self.assertEqual(fast.quantize(values,peak),
                bytes(max(1,min(255,128+round(v*127./peak))) for v in values))
            self.assertEqual(fast.quantized_values(values,peak),
                [max(-127,min(127,round(v*127/peak)))*peak/127 for v in values])
            encoded=[max(-127,min(127,round(v*127/peak))) for v in values]
            self.assertEqual(fast.quantized_loop(values,peak,803,2048),
                [encoded[(((i+1)*803)>>9)%len(encoded)] for i in range(2048)])
        table=bytes(range(1,256))+b'\0';rate=894886/34
        for actual in (rate*513/512,rate*27/512,22000.123):
            self.assertEqual(fast.sample_playback(table,.791,actual,rate,2900),
                [(table[a]-128)*.791/127 if a<len(table)-1 else 0.
                 for i in range(2900) for a in [math.floor((i+1)*actual/rate)]])

    def test_batched_bands(self):
        if audio_dsp._numpy is None:self.skipTest('NumPy path is not in use')
        rng=random.Random(81)
        for n in (0,33,1024,32000):
            values=[rng.uniform(-2,2) for _ in range(n)]
            got=fast.band_energy(values,26320.,audio_fit.BANDS+audio_fit.QUALITY_BANDS)
            with patch.object(fast,'band_energy',return_value=None):
                self.assertEqual(got,audio_fit._band_energy(values,26320.))

    def test_resample_weights(self):
        import native_host
        rng=random.Random(12)
        for n in (1,17,345,3000):
            values=[rng.uniform(-5,5) for _ in range(n)]
            for rate in (6000.,22000.3,64000.):
                for periodic in (False,True):
                    self.assertEqual(fast.resample(values,44100.,rate,24,periodic),
                        native_host.resample(values,44100.,rate,24,periodic))

    def test_ordered_reductions(self):
        rng=random.Random(1978)
        for n in (0,1,33,1024,8000):
            values=[rng.uniform(-3,3) for _ in range(n)]
            self.assertEqual(fast.rms(values),math.sqrt(sum(v*v for v in values)/max(1,n)))
            if n:
                curve=[rng.uniform(-6,6) for _ in range(11)]
                self.assertEqual(fast.corrected(values,.87,curve,64000),
                    [v*.87*10**(-audio_fit.curve_value(curve,i/64000)/20) for i,v in enumerate(values)])

    def test_fft_power(self):
        if audio_dsp._numpy is None:self.skipTest('NumPy path is not in use')
        rng=random.Random(5)
        for n in (0,150,2048,2500):
            values=[rng.uniform(-1,1) for _ in range(n)]
            padded=(values+[0.]*2048)[:2048]
            bins=audio_dsp.fft([v*(.5-.5*math.cos(2*math.pi*i/2047)) for i,v in enumerate(padded)])
            self.assertEqual(fast.power(values,2048,2047),[abs(v)**2 for v in bins[:1025]])

    def test_batched_spectra(self):
        if audio_dsp._numpy is None:self.skipTest('NumPy path is not in use')
        rng=random.Random(7);values=[rng.uniform(-5,5) for _ in range(11000)]
        windows=[(0,0),(0,133),(300,1333),(9900,12000)]
        self.assertEqual(fast.window_powers(values,windows),
            [sum(v*v for v in values[a:b])/max(1,len(values[a:b])) for a,b in windows])
        for frequency in (44.,440.,9900.):
            actual=fast.spectra(values,windows,26320.,frequency)
            with patch.object(fast,'spectra',return_value=None):
                self.assertEqual(actual,[audio_timbre.spectrum(values[a:b],26320.,frequency) for a,b in windows])

    def test_decoded_envelope(self):
        rng=random.Random(14);rate=894886/34;frames=12000
        for kind in ('oneshot','attack'):
            for baked in (False,True):
                z=SimpleNamespace(kind=kind,table=bytes(rng.randrange(1,256) for _ in range(256)),
                    ltable=bytes(rng.randrange(1,256) for _ in range(512)),attack=.012,
                    capture_envelope_baked_release=baked,capture_envelope=[rng.uniform(-1,25) for _ in range(50)],
                    capture_release_curve=[rng.uniform(0,30) for _ in range(50)])
                for hold,chold in ((None,None),(.1,None),(.1,.15)):
                    curve=[rng.uniform(-3,3) for _ in range(30)]
                    got=fast.decoded(z,frames,620,500,.3,.27,-2,curve,hold,chold,rate)
                    expected=[]
                    for i in range(frames):
                        if kind=='oneshot':
                            at=((i+1)*620)>>9;value=(z.table[at]-128)*.3/127 if at<len(z.table) else 0.;gain=1.
                        else:
                            table=z.table if i<500 else z.ltable;at=(((i+1)*620)>>9)%len(table)
                            value=(table[at]-128)*(.3 if i<500 else .27)/127
                            db=(capture_tone.note_db(z,i/rate,hold,1.,i>=500) if hold is not None else capture_tone.envelope_db(z,i/rate,force=True) if i>=500 else 0.)
                            gain=10**(-db/20)
                        age=i/rate
                        if chold is not None and hold is not None and age>hold:age=chold+age-hold
                        expected.append(value*gain*10**((-2-audio_fit.curve_value(curve,age))/20))
                    self.assertEqual(got,expected)

if __name__=='__main__':unittest.main()
