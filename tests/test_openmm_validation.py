import importlib.util
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from molvis.openmm_validation import validate
from molvis.preparation import prepare, validate_pair
from test_preparation import generation_payload, RTF


# Synthetic parameters exercise loading and minimization, not a scientific model.
PRM = '''* Synthetic test parameters
*
BONDS
N H 300 1.0
N C 300 1.45
C C 300 1.50
C O 300 1.23
ANGLES
H N C 50 110
N C C 50 110
C C O 50 120
DIHEDRALS
X N C X 0.1 1 0
X C C X 0.1 1 0
IMPROPER
NONBONDED nbxmod 5 atom cdiel shift vatom vdistance vswitch -
cutnb 14 ctofnb 12 ctonnb 10 eps 1 e14fac 1 wmin 1.5
N 0 -0.1 1.8
H 0 -0.02 1.0
C 0 -0.1 2.0
O 0 -0.1 1.7
END
'''


@unittest.skipUnless(importlib.util.find_spec('openmm') and
                    (os.environ.get('MOLVIS_PSFGEN') or importlib.util.find_spec('psfgen')),
                    'OpenMM and a native psfgen backend required')
class OpenMMValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, MOLVIS_OUTPUT_DIR=str(self.root/'preparations'), MOLVIS_ENVIRONMENT_DIR=str(self.root/'environments'))
        env.start(); self.addCleanup(env.stop)
        result = prepare(generation_payload())
        self.preparation = Path(result['storage']['directory'])
        self.topology = self.root/'test.rtf'; self.topology.write_text(RTF)
        self.parameters = self.root/'test.prm'; self.parameters.write_text(PRM)

    def test_parameter_loading_minimization_and_input_preservation(self):
        original = (self.preparation/'prepared.pdb').read_bytes()
        output = self.root/'diagnostic'
        report = validate(self.preparation, [self.topology], [self.parameters], output,
                          max_iterations=5, platform='Reference')
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(report['simulation_ready'])
        self.assertEqual(report['particles'], 5)
        self.assertLessEqual(report['after']['potential_energy_kj_mol'], report['before']['potential_energy_kj_mol'])
        self.assertEqual((self.preparation/'prepared.pdb').read_bytes(), original)
        validate_pair((output/'minimized.pdb').read_text(), (output/'prepared.psf').read_text())
        with self.assertRaises(FileExistsError):
            validate(self.preparation, [self.topology], [self.parameters], output)

    def test_missing_force_field_terms_fail_and_save_failure(self):
        self.parameters.write_text('* Missing parameters\n*\nEND\n')
        output = self.root/'failed'
        with self.assertRaises(Exception):
            validate(self.preparation, [self.topology], [self.parameters], output, platform='Reference')
        report = json.loads((output/'report.json').read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertFalse((output/'minimized.pdb').exists())

    def test_actual_compatibility_worker_and_missing_terms(self):
        from molvis.compatibility import check_compatibility
        payload = dict(pdb=(self.preparation/'prepared.pdb').read_text(), psf=(self.preparation/'prepared.psf').read_text(),
                       topologies=[dict(name='test.rtf',text=RTF)],parameters=[dict(name='test.prm',text=PRM)])
        for model in ('vacuum','obc2','gbn2'):
            with self.subTest(model=model):
                result = check_compatibility(payload | dict(settings=dict(solvent_model=model)))
                self.assertEqual(result['status'],'compatible',result)
                self.assertEqual(result['particles'],5)
                self.assertFalse(result['simulation_ready'])
                self.assertTrue((Path(result['storage']['directory'])/'system.xml').is_file())
        payload['parameters'] = [dict(name='missing.prm',text='* Missing\n*\nEND\n')]
        result = check_compatibility(payload | dict(settings=dict(solvent_model='vacuum')))
        self.assertEqual(result['status'],'failed')

    def test_readiness_test_runs_bounded_dynamics(self):
        from molvis.compatibility import check_compatibility
        result=check_compatibility(dict(pdb=(self.preparation/'prepared.pdb').read_text(),psf=(self.preparation/'prepared.psf').read_text(),
                                       topologies=[dict(name='test.rtf',text=RTF)],parameters=[dict(name='test.prm',text=PRM)],
                                       settings=dict(solvent_model='vacuum'),test_dynamics=True))
        self.assertEqual(result['status'],'compatible',result)
        self.assertEqual(result['readiness']['dynamics_steps'],100)
        self.assertEqual(result['readiness']['duration_ps'],.2)
        self.assertFalse(result['simulation_ready'])
        self.assertTrue((Path(result['storage']['directory'])/'state.xml').is_file())
        root=Path(result['storage']['directory'])
        samples=[json.loads(line) for line in (root/'measurements.jsonl').read_text().splitlines()]
        minimum=[s for s in samples if s['stage']=='minimization']
        dynamics=[s for s in samples if s['stage']=='dynamics']
        self.assertTrue(minimum)
        self.assertTrue(all(s['temperature_k'] is None and s['time_ps'] is None for s in minimum))
        self.assertEqual([s['step'] for s in dynamics],list(range(0,101,10)))
        self.assertAlmostEqual(dynamics[-1]['time_ps'],.2)
        # Five mobile atoms, one N-H constraint, three COM degrees removed.
        for sample in dynamics:
            self.assertTrue(math.isfinite(sample['temperature_k']))
            self.assertAlmostEqual(sample['total_energy_kj_mol'],sample['potential_energy_kj_mol']+sample['kinetic_energy_kj_mol'])
            self.assertAlmostEqual(sample['temperature_k'],2*sample['kinetic_energy_kj_mol']/(11*0.00831446261815324),places=5)
        self.assertIn('measurements.csv',result['storage']['download_urls'])


if __name__ == '__main__':
    unittest.main()
