import unittest

from molvis.compatibility import check_compatibility, solvent_settings
from molvis.planning import create_plan
from test_preparation import PDB, PSF


class CompatibilityTests(unittest.TestCase):
    def test_deferred_environment_does_not_assign_solvent_or_salt(self):
        plan = create_plan(dict(pdb=PDB,psf=PSF,check_compatibility=True))
        self.assertEqual(plan['compatibility']['status'],'deferred')
        self.assertEqual(plan['settings']['solvent_model'],'deferred')
        self.assertIsNone(plan['settings']['salt_molar'])
        self.assertIsNone(plan['settings']['padding_nm'])
        self.assertIsNone(plan['settings']['nonbonded_method'])
        self.assertIn('environment',[s['id'] for s in plan['steps']])

    def test_missing_parameters_are_not_reported_compatible(self):
        result = check_compatibility(dict(pdb=PDB, psf=PSF, settings=dict(solvent_model="obc2")))
        self.assertEqual(result['status'], 'needs_input')
        self.assertFalse(result['simulation_ready'])

    def test_explicit_solvent_requires_water_definitions(self):
        result = check_compatibility(dict(pdb=PDB, psf=PSF, settings=dict(solvent_model='charmm_tip3p')))
        self.assertEqual(result['status'], 'needs_input')
        self.assertEqual(result['settings']['nonbonded_method'], 'PME')
        self.assertTrue(result['required'])

    def test_implicit_default_screening_and_explicit_no_ions(self):
        for model in ('obc2','gbn2'):
            self.assertEqual(solvent_settings(dict(solvent_model=model))['salt_molar'],.2)
        explicit=solvent_settings(dict(solvent_model='charmm_tip3p'))
        self.assertEqual(explicit['salt_molar'],0)
        self.assertFalse(explicit['neutralize'])
        self.assertTrue(explicit['periodic'])
        with self.assertRaisesRegex(ValueError,'no ions'):
            solvent_settings(dict(solvent_model='charmm_tip3p',salt_molar=.2))
        with self.assertRaisesRegex(ValueError,'disabled'):
            solvent_settings(dict(solvent_model='charmm_tip3p',neutralize=True))

    def test_invalid_solvent_settings_rejected(self):
        for settings in ({'solvent_model':'unknown'}, {'salt_molar':-1}, {'padding_nm':0}, {'salt_molar':'nan'}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                solvent_settings(settings)
        with self.assertRaisesRegex(ValueError,'Vacuum'):
            check_compatibility(dict(pdb=PDB,psf=PSF,settings=dict(solvent_model='vacuum',salt_molar=.15)))

    def test_plan_retains_environment_and_manual_protonation(self):
        plan = create_plan(dict(pdb=PDB, psf=PSF, settings=dict(solvent_model='charmm_tip3p',padding_nm=1.2),
                                preparation_options=dict(histidine='HSD',first='NTER',last='CTER'),
                                check_compatibility=True))
        self.assertEqual(plan['settings']['nonbonded_method'],'PME')
        self.assertEqual(plan['settings']['salt_molar'],0)
        self.assertIn('HSD',plan['settings']['protonation'])
        self.assertIn('no automatic',plan['settings']['protonation'])
        self.assertIn('solvate',[step['id'] for step in plan['steps']])
        self.assertEqual(plan['compatibility']['status'],'needs_input')
        self.assertFalse(plan['execution_available'])
