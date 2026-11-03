import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from molvis.waterbox import water_topology
from molvis.preparation import prepare, validate_pair
from molvis.planning import inspect_pdb
from test_preparation import generation_payload, RTF
from test_openmm_validation import PRM

# Deliberately synthetic water parameters for integration testing only.
WATER='''* Synthetic test water
read rtf card append
* Test water
*
36 1
MASS -1 HT 1.008 H
MASS -1 OT 15.9994 O
DEFA FIRS NONE LAST NONE
RESI TIP3 0.0 NOANG NODIH
GROUP
ATOM OH2 OT -0.8
ATOM H1 HT 0.4
ATOM H2 HT 0.4
BOND OH2 H1 OH2 H2 H1 H2
ANGLE H1 OH2 H2
END
read para card flex append
* Test water parameters
*
BONDS
OT HT 450 0.9572
HT HT 0 1.5139
ANGLES
HT OT HT 55 104.52
NONBONDED nbxmod 5 atom cdiel shift vatom vdistance vswitch -
cutnb 14 ctofnb 12 ctonnb 10 eps 1 e14fac 1 wmin 1.5
OT 0 -0.15 1.7
HT 0 -0.02 1.0
END
'''


class WaterTopologyTests(unittest.TestCase):
    def test_extracts_only_topology_data(self):
        extracted=water_topology('set bad never_execute\n'+WATER)
        self.assertNotIn('read rtf',extracted)
        self.assertNotIn('read para',extracted)
        self.assertNotIn('set bad',extracted)
        self.assertIn('RESI TIP3',extracted)
        with self.assertRaises(ValueError): water_topology('RESI OTHER 0\nEND')


@unittest.skipUnless(importlib.util.find_spec('openmm') and
                    (os.environ.get('MOLVIS_PSFGEN') or importlib.util.find_spec('psfgen')),
                    'OpenMM and psfgen required')
class WaterBoxTests(unittest.TestCase):
    def test_periodic_water_preserves_protein_adds_no_ions_and_downloads(self):
        from molvis.compatibility import check_compatibility
        with TemporaryDirectory() as directory, patch.dict(os.environ,MOLVIS_OUTPUT_DIR=directory+'/prep',MOLVIS_ENVIRONMENT_DIR=directory+'/env'):
            source=prepare(generation_payload())
            payload=dict(pdb=source['pdb'],psf=source['psf'],topologies=[dict(name='test.rtf',text=RTF)],
                         parameters=[dict(name='test.prm',text=PRM)],water=[dict(name='test-water.str',text=WATER)],
                         settings=dict(solvent_model='charmm_tip3p',padding_nm=1.5))
            result=check_compatibility(payload)
            self.assertEqual(result['status'],'compatible',result)
            self.assertGreater(result['box']['water_molecules'],0)
            self.assertEqual(result['box']['added_ions'],0)
            self.assertTrue(result['box']['solute_preserved'])
            self.assertFalse(result['box']['neutralize'])
            root=Path(result['storage']['directory'])
            pdb=(root/'solvated.pdb').read_text(); psf=(root/'solvated.psf').read_text()
            self.assertTrue(pdb.startswith('CRYST1'))
            self.assertEqual(validate_pair(pdb,psf)['atom_count'],result['particles'])
            water=[a for a in inspect_pdb(pdb)['atoms'] if a['segment_id'].startswith('W')]
            self.assertTrue(all(a['residue']=='TIP3' for a in water))
            self.assertEqual(len(water),3*result['box']['water_molecules'])
            self.assertTrue((root/'environment.zip').is_file())
            self.assertEqual(json.loads((root/'manifest.json').read_text())['settings']['nonbonded_method'],'PME')
