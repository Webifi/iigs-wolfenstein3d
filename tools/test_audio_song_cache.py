"""A successful cached pack may discard only its intact generated predecessor."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from audio_provenance import discard_generated,RECEIPT


class PreviousPackTests(unittest.TestCase):
    def check_previous(self,edit):
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder)/'previous';old.mkdir()
            data=b'compiled bank';(old/'song.bin').write_bytes(data)
            doc=dict(format=1,status='complete',outputs={'song.bin':hashlib.sha256(data).hexdigest()})
            doc['identity']=hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()
            (old/RECEIPT).write_text(json.dumps(doc))
            if edit=='changed':(old/'song.bin').write_bytes(b'edited bank')
            if edit=='extra':(old/'notes.txt').write_text('Keep this note.')
            if edit=='receipt':(old/RECEIPT).write_text('{}')
            discard_generated(old)
            self.assertEqual(old.exists(),edit is not None)

    def test_intact_previous_pack(self):self.check_previous(None)
    def test_edited_bank_survives(self):self.check_previous('changed')
    def test_extra_file_survives(self):self.check_previous('extra')
    def test_unverified_receipt_survives(self):self.check_previous('receipt')


if __name__=='__main__':unittest.main()
