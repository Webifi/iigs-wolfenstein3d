"""DOC sample progression, board transfer, and untouched output-level checks."""
from array import array
import cmath
import math
import tempfile
import unittest
from pathlib import Path

from doc_output import Output, POLES, GAINS
from doc_render import CLOCK, SCAN, synthesize, write_wave, unpack
from check_music_packs import bank


class Rendering(unittest.TestCase):
    def test_cold_variants_decode_same_wave_and_program(self):
        a=unpack(bank());b=unpack(bank(blocks=True))
        self.assertEqual(a[:2],b[:2])

    def test_constant_voice_has_fixed_doc_gain_and_system_control(self):
        ram=bytearray([129])*65536
        writes=[(0,4,0),(0,36,2),(0,68,255),(0,132,64),(0,196,0),(0,164,0)]
        end=SCAN*2500
        a=synthesize(ram,writes,0,end,system_volume=15)
        b=synthesize(ram,writes,0,end,system_volume=7)
        steady=a[500:]
        self.assertAlmostEqual(sum(steady)/len(steady),255/(32768*8),delta=1e-7)
        self.assertLess(max(abs(y-x*7/15) for x,y in zip(a,b)),1e-12)

    def test_zero_terminator_stops_voice_without_playing_unsigned_zero(self):
        ram=bytearray([129])*65536;ram[0x4002]=0
        writes=[(0,4,0),(0,36,2),(0,68,255),(0,132,64),(0,196,0),(0,164,0)]
        a=synthesize(ram,writes,0,SCAN*400)
        self.assertLess(max(map(abs,a[100:])),1e-10)
        self.assertGreater(max(a[:50]),0.)

    def test_one_shot_ends_after_complete_table(self):
        ram=bytearray([129])*65536
        writes=[(0,4,0),(0,36,2),(0,68,255),(0,132,64),(0,196,0),(0,164,2)]
        a=synthesize(ram,writes,0,SCAN*500)
        self.assertGreater(sum(a[200:350]),.1)
        self.assertLess(max(map(abs,a[650:])),1e-9)

    def test_output_circuit_sine_transfer_matches_board_equation(self):
        rate=48000;end=CLOCK//10;out=Output(CLOCK,rate,end)
        frequency=3000
        for tick in range(0,end,8):
            out.add(1000*math.sin(2*math.pi*frequency*(tick+4)/CLOCK),tick,min(tick+8,end))
        result=out.finish(0,15)[1000:]
        rms=(sum(v*v for v in result)/len(result))**.5
        s=complex(0,2*math.pi*frequency)
        transfer=1/((1+3.3e-6*s)*(1+1.12e-5*s+2.184e-10*s*s))
        # WAV frames average the analog signal across each output interval.
        aperture=math.sin(math.pi*frequency/rate)/(math.pi*frequency/rate)
        expected=1000*17/(4*32768)/math.sqrt(2)*abs(transfer)*aperture
        self.assertAlmostEqual(rms/expected,1.,delta=.001)
        self.assertAlmostEqual(GAINS[0]+2*GAINS[1].real,1.)

    def test_wave_writer_does_not_normalize_or_compress(self):
        with tempfile.TemporaryDirectory() as temp:
            report=write_wave(Path(temp)/'test.wav',array('d',[0.,.25,-.5,1.25]))
            self.assertEqual(report['peak'],1.25)
            self.assertEqual(report['clipped_samples'],1)
            import wave
            with wave.open(str(Path(temp)/'test.wav')) as wav:
                pcm=array('h',wav.readframes(4))
            self.assertEqual(list(pcm),[0,8192,-16384,32767])

    def test_instrument_outputs_follow_voice_reuse_and_sum_to_untouched_mix(self):
        ram=bytearray([129])*65536
        writes=[(0,4,0),(0,36,2),(0,68,255),(0,132,64),(0,196,0),(0,164,0),
                (SCAN*800,68,127),(SCAN*1600,68,0)]
        labels=[1]*6+[2,2]
        end=SCAN*2000
        mixed=synthesize(ram,writes,0,end)
        parts=synthesize(ram,writes,0,end,part_tags=labels,parts=[1,2])
        self.assertEqual(mixed,parts['mix'])
        self.assertLess(max(abs(m-a-b) for m,a,b in zip(mixed,parts['ch01'],parts['ch02'])),1e-12)
        # The second part takes the same oscillator at its next volume write;
        # the first part's filter release is preserved instead of hard-cut.
        first_writes=[(t,r,0 if r==68 and ch!=1 else v) for (t,r,v),ch in zip(writes,labels)]
        self.assertEqual(parts['ch01'],synthesize(ram,first_writes,0,end))

    def test_instrument_labels_must_match_real_engine_register_order(self):
        from unittest.mock import patch
        from doc_parts import trace_labels
        writes=[(1,4,7),(2,68,0),(3,68,120),(4,164,0)]
        oracle=bytes([68,120,2,164,0,2])
        with patch('doc_parts.tagged_oracle',return_value=(oracle,[2])):
            labels,channels=trace_labels(writes,3,b'',None,None,15)
            self.assertEqual(labels,[0,0,2,2]);self.assertEqual(channels,[2])
            with self.assertRaisesRegex(ValueError,'differs'):
                trace_labels(writes[:2]+[(3,68,121),(4,164,0)],3,b'',None,None,15)
            with self.assertRaisesRegex(ValueError,'fewer'):
                trace_labels(writes[:-1],3,b'',None,None,15)


if __name__=='__main__':unittest.main()
