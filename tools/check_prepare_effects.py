"""Regression checks for source preservation and explicit DOC limits."""
import unittest
from prepare_effects import DOC_RATE, demand, frequency, render_doc_model, source_pcm, table_bytes


class SourcePreservation(unittest.TestCase):
    def test_duration_silence_and_amplitude_survive(self):
        raw = bytes([128])*5000 + bytes([132, 170, 220])*4000 + bytes([128])*9000
        self.assertEqual(source_pcm(raw), raw)
        self.assertGreater(len(raw),4095)
        self.assertEqual(max(source_pcm(raw)),220)

    def test_only_zero_bytes_change(self):
        raw=bytes(range(256))*40
        result=source_pcm(raw)
        self.assertEqual(len(raw),len(result))
        self.assertEqual([(a,b) for a,b in zip(raw,result) if a!=b],[(0,1)]*40)

    def test_full_tables_do_not_cap(self):
        self.assertEqual(table_bytes(4095),4096)
        self.assertEqual(table_bytes(4096),8192)
        self.assertEqual(table_bytes(24577),32768)
        self.assertEqual(table_bytes(108539),131072)

    def test_model_uses_fixed_levels(self):
        data=bytes([192])*7000+b'\0'
        fc=frequency(7043,1024)
        loud=render_doc_model(data,fc,1024,255,continuous=True)
        quiet=render_doc_model(data,fc,1024,128,continuous=True)
        self.assertEqual(len(loud),len(quiet))
        self.assertGreater(len(loud),26000)
        self.assertAlmostEqual(quiet[0]/loud[0],128/255,places=6)
        self.assertEqual(len(render_doc_model(data,fc,1024,0,continuous=True)),len(loud))

    def test_unrepresentable_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            frequency(192000,1024)

    def test_memory_overflow_does_not_reduce_samples(self):
        row=dict(id=0,sample_sha256='same',bytes_with_terminator=20001,one_shot_table_bytes=32768,
                 source_rate=7043,current_bytes=4096)
        floor=dict(floor=0,effects=[0],pinned=[0],resident_bytes=5500)
        report=demand([row],floor,[dict(start=0,end=16384)],dict(buffer_bytes=1024,buffers_per_voice=2,
                     voices=2,effects_doc_bytes=16384))
        self.assertEqual(report['existing_region_unplaced'],[0])
        self.assertEqual(report['proposed_ram_bytes'],21457)
        self.assertEqual(report['exceeds_entire_effect_partition'],[0])
        self.assertEqual(report['two_voice_stream_buffer_bytes'],4096)
        self.assertEqual(row['bytes_with_terminator'],20001)


if __name__ == '__main__':
    unittest.main()
