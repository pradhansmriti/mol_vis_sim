import base64
import importlib.util
import io
import json
import subprocess
import unittest
from unittest.mock import patch
import zipfile

from molvis.planning import create_plan, inspect_pdb
from molvis.preparation import prepare, validate_pair


def pdb_atom(index, name, xyz, segid='P000', chain='A', residue=1):
    x, y, z = xyz
    return f'ATOM  {index:5d} {name:^4s} ALA {chain}{residue:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00      {segid:<4s}'


PDB = '\n'.join(pdb_atom(i, name, xyz) for i, (name, xyz) in enumerate([
    ('N', (0, 0, 0)), ('CA', (1.45, 0, 0)), ('C', (2, 1.4, 0)), ('O', (1.7, 2.5, 0))], 1))+'\nEND\n'
PSF = 'PSF\n\n       4 !NATOM\n'+''.join(f'{i} P000 1 ALA {name} {name} 0.0 12.0 0\n' for i, name in enumerate(['N','CA','C','O'], 1))+'\n0 !NBOND\n'
# Deliberately minimal, synthetic topology for exercising the native engine.
# This is test data, not a force field for scientific use.
RTF = '''* Synthetic topology for tests only
*
36 1
MASS -1 N 14.007 N
MASS -1 C 12.011 C
MASS -1 O 15.999 O
MASS -1 H 1.008 H
DEFA FIRS NONE LAST NONE
AUTO ANGLES DIHE
RESI ALA 0.0
GROUP
ATOM N N -0.3
ATOM HN H 0.3
ATOM CA C 0.0
ATOM C C 0.5
ATOM O O -0.5
BOND N HN N CA CA C C O
IC C CA N HN 1.5 110.0 180.0 120.0 1.0
END
'''


def generation_payload():
    return dict(mode='generate', pdb=PDB, topologies=[dict(name='test.rtf', text=RTF)],
                confirm_guess=True, options=dict(first='NONE', last='NONE', histidine='HSE'))


class PairTests(unittest.TestCase):
    def test_upload_preserves_pair_and_parameters(self):
        result = prepare(dict(mode='upload', pdb=PDB, psf=PSF,
                              parameters=[dict(name='test.prm',text='* test parameters')]))
        self.assertEqual(result['pdb'], PDB)
        self.assertEqual(result['psf'], PSF)
        self.assertFalse(result['manifest']['simulation_ready'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['bundle_base64']))) as bundle:
            self.assertEqual(bundle.read('prepared.psf').decode(), PSF)
            self.assertEqual(bundle.read('parameters/0-test.prm').decode(), '* test parameters')
            self.assertEqual(json.loads(bundle.read('manifest.json'))['pair']['atom_count'],4)

    def test_reject_mismatched_pair(self):
        for psf in (PSF.replace('4 !NATOM','3 !NATOM'), PSF.replace('ALA N N','ALA O N'),
                    PSF.replace('P000','P001'), PSF.replace('0.0 12.0','nan 12.0'),
                    PSF.replace('PSF','garbage'), PSF[:PSF.index('4 P000')]):
            with self.subTest(psf=psf), self.assertRaises(ValueError):
                validate_pair(PDB,psf)

    def test_plan_uses_charmm_path_for_pair(self):
        plan = create_plan(dict(pdb=PDB,psf=PSF))
        self.assertEqual(plan['preparation']['pair']['atom_count'],4)
        self.assertNotIn('amber14-all.xml', plan['settings']['forcefield'])
        self.assertIn('Unresolved', plan['settings']['solvent'])

    def test_segment_identity_supports_repeated_residue_numbers(self):
        pdb = pdb_atom(1,'CA',(0,0,0),chain=' ',segid='P000')+'\n'+pdb_atom(2,'CA',(1,0,0),chain=' ',segid='P001')
        self.assertEqual(inspect_pdb(pdb)['residue_count'],2)

    def test_generation_requires_review_and_supported_inputs(self):
        for changes in ({'confirm_guess':False}, {'topologies':[]}, {'pdb':PDB.replace('ALA','HOH')},
                        {'pdb':PDB.replace(' CA ',' XX ')}, {'options':{'histidine':'auto'}},
                        {'options':{'first':'[exec bad]'}},
                        {'topologies':[dict(name='../test.rtf',text=RTF)]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare(generation_payload() | changes)

    def test_runner_failure_and_timeout_surface_as_errors(self):
        with patch('molvis.preparation.subprocess.run', return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaisesRegex(ValueError,'preparation failed'):
                prepare(generation_payload())
        with patch('molvis.preparation.subprocess.run', side_effect=subprocess.TimeoutExpired([],120)):
            with self.assertRaisesRegex(ValueError,'120 seconds'):
                prepare(generation_payload())


@unittest.skipUnless(importlib.util.find_spec('psfgen'), 'Standalone psfgen is not installed in this Python environment')
class NativePreparationTests(unittest.TestCase):
    def test_real_psfgen_generation_and_round_trip(self):
        result = prepare(generation_payload())
        self.assertEqual(result['structure']['atom_count'],5)
        self.assertIn('HN',[a['name'] for a in result['structure']['atoms']])
        self.assertEqual(result['manifest']['details']['engine']['version'],'1.0.5')
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['bundle_base64']))) as bundle:
            self.assertEqual(bundle.read('source.pdb').decode(),PDB)
        uploaded = prepare(dict(mode='upload',pdb=result['pdb'],psf=result['psf']))
        self.assertEqual(uploaded['manifest']['pair'],result['manifest']['pair'])
        self.assertEqual(create_plan(dict(pdb=result['pdb'],psf=result['psf']))['preparation']['pair']['atom_count'],5)


if __name__ == '__main__':
    unittest.main()
