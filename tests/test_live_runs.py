import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from molvis import live_runs
from molvis.compatibility import observe_worker
from test_preparation import PDB,PSF


class LiveRunTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        env=patch.dict(os.environ,MOLVIS_RUN_DIR=str(self.root));env.start();self.addCleanup(env.stop)
        jobs=patch.dict(live_runs._jobs,{},clear=True);jobs.start();self.addCleanup(jobs.stop)
        self.addCleanup(live_runs.shutdown)
        self.payload=dict(pdb=PDB,psf=PSF,settings=dict(solvent_model='vacuum'),parameters=[dict(name='test.prm',text='* test')])

    def test_samples_visible_before_completion_and_persist_afterwards(self):
        emitted=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def worker(payload,observer,cancel_event):
            observer(dict(type='sample',data=dict(sequence=1,stage='minimization',potential_energy_kj_mol=-1)))
            emitted.set();release.wait(3)
            return dict(status='compatible',message='done')
        with patch('molvis.live_runs.check_compatibility',side_effect=worker):
            started=live_runs.start_run(self.payload);self.assertTrue(emitted.wait(2))
            current=live_runs.read_run(started['id'])
            self.assertEqual(current['status'],'running')
            self.assertEqual(len(current['samples']),1)
            with self.assertRaisesRegex(ValueError,'already active'): live_runs.start_run(self.payload)
            release.set();live_runs._jobs[started['id']]['thread'].join(3)
        finished=live_runs.read_run(started['id']);self.assertEqual(finished['status'],'completed')
        del live_runs._jobs[started['id']]
        self.assertEqual(live_runs.read_run(started['id'])['samples'],finished['samples'])

    def test_cancellation_preserves_partial_samples(self):
        emitted=threading.Event()
        def worker(payload,observer,cancel_event):
            observer(dict(type='sample',data=dict(sequence=1,stage='minimization',potential_energy_kj_mol=-1)))
            emitted.set();cancel_event.wait(3)
            return dict(status='cancelled',message='cancelled')
        with patch('molvis.live_runs.check_compatibility',side_effect=worker):
            started=live_runs.start_run(self.payload);self.assertTrue(emitted.wait(2))
            live_runs.cancel_run(started['id']);live_runs._jobs[started['id']]['thread'].join(3)
        record=live_runs.read_run(started['id'])
        self.assertEqual(record['status'],'cancelled');self.assertEqual(len(record['samples']),1)

    def test_restarted_active_record_is_interrupted_not_resumed(self):
        identifier='12345678-1234-1234-1234-123456789abc';root=self.root/identifier;root.mkdir()
        (root/'run.json').write_text(json.dumps(dict(id=identifier,status='running')))
        (root/'measurements.jsonl').write_text('')
        self.assertEqual(live_runs.read_run(identifier)['status'],'interrupted')
        with self.assertRaises(ValueError): live_runs.read_run('../../private')

    def test_cancellation_terminates_the_native_worker(self):
        event=threading.Event();event.set();start=time.monotonic()
        process,cancelled=observe_worker([sys.executable,'-c','import time; time.sleep(30)'],self.root,self.root,lambda event:None,event)
        self.assertTrue(cancelled);self.assertEqual(process.returncode,-1)
        self.assertLess(time.monotonic()-start,5)
