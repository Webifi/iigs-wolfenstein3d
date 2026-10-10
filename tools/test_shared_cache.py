"""Shared cache correctness: relocation, changed dependencies and racing writers."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from step_cache import StepCache

TOOLS = Path(__file__).resolve().parent
PROGRAM = '''from pathlib import Path
import os
print('EXECUTED')
p = Path('build/result.bin')
p.write_bytes(Path('input').read_bytes() + os.environ.get('CHOICE', '').encode())
'''


class SharedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.environment = patch.dict(os.environ, WOLF_SHARED_CACHE=str(self.root/'shared'))
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.tmp.cleanup()

    def stage(self, name):
        root = self.root/name
        root.mkdir()
        shutil.copytree(TOOLS, root/'tools', ignore=shutil.ignore_patterns('__pycache__'))
        (root/'build').mkdir()
        (root/'input').write_bytes(b'original')
        (root/'tools/example.py').write_text(PROGRAM)
        return root

    def build(self, root, **extra):
        cache = StepCache(root, log=lambda s: None)
        env = dict(os.environ, PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', **extra)
        with (root/'run.log').open('w') as log:
            ran = cache.python([sys.executable, 'tools/example.py'], env, log)
        cache.finish()
        return ran

    def test_reuse_and_changes(self):
        first, second = self.stage('first'), self.stage('second')
        self.assertTrue(self.build(first))
        self.assertFalse(self.build(second))
        self.assertEqual((second/'build/result.bin').read_bytes(), b'original')
        (second/'input').write_bytes(b'new source')
        self.assertTrue(self.build(second))
        self.assertTrue(self.build(second, CHOICE='!'))
        self.assertEqual((second/'build/result.bin').read_bytes(), b'new source!')
        # Reachable code must invalidate even when the source data stays put.
        path = second/'tools/example.py'
        path.write_text(PROGRAM.replace("+ os.environ", "+ b'code' + os.environ"))
        self.assertTrue(self.build(second))
        self.assertEqual((second/'build/result.bin').read_bytes(), b'new sourcecode')
        self.assertEqual((first/'build/result.bin').read_bytes(), b'original')

    def test_changed_producer_adds_an_output(self):
        root = self.stage('changed-outputs')
        producer = root/'tools/producer.py'
        producer.write_text("from pathlib import Path\nPath('build/first').write_text('one')\n")
        (root/'tools/consumer.py').write_text(
            "from pathlib import Path\nPath('build/result').write_text(Path('build/second').read_text())\n")
        (root/'build/second').write_text('old')
        commands = [[sys.executable, 'tools/'+name+'.py'] for name in ('producer', 'consumer')]
        cache = StepCache(root, jobs=3, log=lambda s: None)
        env = dict(os.environ)
        cache.set_plan(commands)
        cache.run_steps(commands, env, root/'run.log')
        producer.write_text("from pathlib import Path\nimport time\ntime.sleep(.2)\n"
                            "Path('build/first').write_text('one')\nPath('build/second').write_text('new')\n")
        (root/'build/second').unlink()
        cache.set_plan(commands)
        cache.run_steps(commands, env, root/'run.log')
        self.assertEqual((root/'build/result').read_text(), 'new')

    def test_transform_reads_earlier_output(self):
        root = self.stage('transform')
        (root/'tools/producer.py').write_text(
            "from pathlib import Path\nPath('build/value').write_bytes(Path('input').read_bytes())\n")
        (root/'tools/transform.py').write_text(
            "from pathlib import Path\np=Path('build/value')\ns=p.read_bytes()\np.write_bytes(s+b'!')\n")
        commands = [[sys.executable, 'tools/'+name+'.py'] for name in ('producer', 'transform')]
        cache = StepCache(root, jobs=3, log=lambda s: None)
        env = dict(os.environ)
        cache.set_plan(commands)
        cache.run_steps(commands, env, root/'run.log')
        self.assertEqual((root/'build/value').read_bytes(), b'original!')
        (root/'input').write_bytes(b'changed')
        cache.set_plan(commands)
        cache.run_steps(commands, env, root/'run.log')
        self.assertEqual((root/'build/value').read_bytes(), b'changed!')
        ran = cache.stats['ran']
        cache.set_plan(commands)
        cache.run_steps(commands, env, root/'run.log')
        self.assertEqual(cache.stats['ran'], ran)

    def test_source_clone_and_metadata(self):
        first, second = self.stage('first'), self.stage('second-long-name')
        program = """from pathlib import Path
import sys, json
Path('build/gen').mkdir(exist_ok=True)
Path('build/gen/audio-input.json').write_text(json.dumps({'stage': str(Path.cwd()), 'source': str(Path(sys.argv[1]).resolve()), 'data': Path(sys.argv[1]).read_text()}))
"""
        sources = {}
        for stage in (first, second):
            source = self.root/(stage.name + '-source')
            source.mkdir()
            (source/'input').write_text('original')
            sources[stage] = source
            (stage/'tools/example.py').write_text(program)
        def run(stage):
            cache = StepCache(stage, source_root=sources[stage], log=lambda s: None)
            with (stage/'run.log').open('w') as log:
                return cache.python([sys.executable,'tools/example.py',str(sources[stage]/'input')],
                                    dict(os.environ,PYTHONHASHSEED='0'),log)
        self.assertTrue(run(first))
        self.assertFalse(run(second))
        cached = (second/'build/gen/audio-input.json').read_bytes()
        subprocess.run([sys.executable,'tools/example.py',str(sources[second]/'input')],cwd=second,check=True)
        self.assertEqual(cached,(second/'build/gen/audio-input.json').read_bytes())
        (sources[second]/'input').write_text('changed in the clone only')
        self.assertTrue(run(second))
        self.assertIn('changed in the clone only',(second/'build/gen/audio-input.json').read_text())

    def test_corrupted_blob_rebuilt(self):
        first, second = self.stage('first'), self.stage('second')
        self.build(first)
        blob = next((self.root/'shared/v1/blobs').glob('*/*'))
        blob.write_bytes(b'damaged')
        self.assertTrue(self.build(second))
        self.assertEqual((second/'build/result.bin').read_bytes(), b'original')

    def test_audio_receipt_binding(self):
        from cache_paths import relocate
        stage = self.stage('audio-stage')
        receipt = stage/'build/audio/music/audio-build.json'
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({'identity': 'current receipt'}))
        target = stage/'build/gen/audio-input.json'
        target.parent.mkdir()
        target.write_text(json.dumps({'audio_build_identity': 'old receipt'}))
        relocate({str(target): 'old digest'}, {'@stage': '/previous/stage'}, {'@stage': str(stage)})
        self.assertEqual(json.loads(target.read_text())['audio_build_identity'], 'current receipt')

    def test_codec_identity_and_corruption(self):
        import shared_cache
        calls = []
        def encode():
            calls.append(1)
            return b'encoded bytes'
        for _ in range(2):
            self.assertEqual(shared_cache.codec('test', b'code1', b'input', encode), b'encoded bytes')
        self.assertEqual(len(calls), 1)
        shared_cache.codec('test', b'code2', b'input', encode)
        shared_cache.codec('test', b'code1', b'changed input', encode)
        self.assertEqual(len(calls), 3)
        shared_cache.codec_path('test', b'code1', b'input').write_bytes(b'truncated')
        self.assertEqual(shared_cache.codec('test', b'code1', b'input', encode), b'encoded bytes')
        self.assertEqual(len(calls), 4)

    def test_simultaneous(self):
        first, second = self.stage('first'), self.stage('second')
        worker = self.root/'worker.py'
        worker.write_text('import os,sys\nfrom step_cache import StepCache\n'
                          'c=StepCache(sys.argv[1]); c.python([sys.executable,"tools/example.py"],'
                          'dict(os.environ,PYTHONHASHSEED="0",PYTHONDONTWRITEBYTECODE="1"),sys.stdout); c.finish()\n')
        env = dict(os.environ, PYTHONPATH=str(TOOLS))
        children = [subprocess.Popen([sys.executable,str(worker),str(root)],env=env,
                                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT) for root in (first,second)]
        logs = [child.communicate(timeout=60)[0] for child in children]
        self.assertEqual([c.returncode for c in children],[0,0], logs)
        self.assertEqual(sum(log.count(b'EXECUTED') for log in logs),1,logs)
        self.assertEqual((first/'build/result.bin').read_bytes(),(second/'build/result.bin').read_bytes())


if __name__ == '__main__':
    unittest.main()
