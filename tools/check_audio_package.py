"""Verify that consumer audio preflight works without developer audio modules."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ReaderIsolation(unittest.TestCase):
    def test_minimal_reader_tree_validates_music_and_effect_identities(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary);(target/'tools').mkdir();(target/'profiles').mkdir()
            for name in ('audio_package.py','game_profile.py','dos_data.py'):
                shutil.copyfile(root/'tools'/name,target/'tools'/name)
            shutil.copytree(root/'tools/vendor',target/'tools/vendor')
            for path in (root/'profiles').glob('*.toml'):
                shutil.copyfile(path,target/'profiles'/path.name)
            shutil.copytree(root/'profiles/conversion',target/'profiles/conversion')
            code='''import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path.cwd()/'tools'))
from audio_package import write_toml, validate_effects, sha
p=Path('package');game=SimpleNamespace(key='fixture',sounds=1,required_music={0:'SONG'})
write_toml(p/'intermediate.toml',dict(format=2,profile='fixture',songs=[dict(id=0,name='SONG')]))
write_toml(p/'inputs/SONG/inputs.toml',dict(original_sha256=sha(b'IMF')))
r=p/'effects/ym3812';r.mkdir(parents=True);(r/'00.u8').write_bytes(b'sample')
write_toml(r/'samples.toml',dict(format=1,samples=[dict(id=0,file='00.u8',sha256=sha(b'sample'),original_sha256=sha(b'OPL'))]))
source=SimpleNamespace(profile=game,audio=lambda:[b'',b'OPL',b'',b'IMF'])
assert validate_effects(p,game,None,source=source)==r
assert not any(n in sys.modules for n in ('audio_recipes','music_score','audio_compile','doccompiler','numpy','sf2'))
print('isolated preflight passed')
'''
            result=subprocess.run([sys.executable,'-I','-B','-c',code],cwd=target,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('isolated preflight passed',result.stdout)


if __name__=='__main__':
    unittest.main()
