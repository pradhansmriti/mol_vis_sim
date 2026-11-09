import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from molvis.planning import create_plan, inspect_pdb
from molvis.preparation import prepare, validate_pair, select_protein, map_terminal_oxygens, verify_terminal_coordinates, remove_input_hydrogens
from molvis.standalone_psfgen import write_script


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


class StorageIsolation:
    def setUp(self):
        self.output = TemporaryDirectory()
        self.addCleanup(self.output.cleanup)
        env = patch.dict(os.environ, {'MOLVIS_OUTPUT_DIR': self.output.name})
        env.start()
        self.addCleanup(env.stop)


class PairTests(StorageIsolation, unittest.TestCase):
    def test_hydrogen_filter_preserves_heavy_atoms_and_respects_elements(self):
        heavy = pdb_atom(1, 'CA', (1,2,3))
        named = pdb_atom(2, '1HB', (2,3,4))
        deuterium = pdb_atom(3, 'D', (3,4,5))
        explicit_h = pdb_atom(4, 'X', (4,5,6)).ljust(76)+' H'
        explicit_heavy = pdb_atom(5, 'HG', (5,6,7)).ljust(76)+' C'
        kept, removed = remove_input_hydrogens([heavy,named,deuterium,explicit_h,explicit_heavy])
        self.assertEqual(kept, [heavy,explicit_heavy])
        self.assertEqual([a['name'] for a in removed], ['1HB','D','X'])

    def test_cter_mapping_is_endpoint_only_and_preserves_pdb_columns(self):
        lines = [pdb_atom(1,'O',(0,1,2),residue=1),
                 pdb_atom(2,'O',(3,4,5),residue=2),pdb_atom(3,'OXT',(6,7,8),residue=2)]
        mapped, changes = map_terminal_oxygens(lines,'CTER','P000')
        self.assertEqual(mapped[0],lines[0])
        self.assertEqual([line[12:16].strip() for line in mapped],['O','OT1','OT2'])
        for before, after in zip(lines,mapped):
            self.assertEqual(before[:12],after[:12])
            self.assertEqual(before[16:],after[16:])
        self.assertEqual([c['source_name'] for c in changes],['O','OXT'])
        self.assertEqual(verify_terminal_coordinates('\n'.join(mapped),changes)['max_displacement_angstrom'],0)
        self.assertEqual(map_terminal_oxygens(lines,'NONE','P000'),(lines,[]))
        self.assertEqual(map_terminal_oxygens(mapped,'CTER','P000'),(mapped,[]))

    def test_terminal_coordinate_check_rejects_changed_coordinates(self):
        mapped, changes = map_terminal_oxygens([pdb_atom(1,'O',(1,2,3))],'CTER','P000')
        changed = mapped[0][:30]+f'{9.:8.3f}'+mapped[0][38:]
        with self.assertRaisesRegex(ValueError,'did not preserve'):
            verify_terminal_coordinates(changed,changes)

    def test_cter_mapping_rejects_ambiguous_aliases(self):
        with self.assertRaisesRegex(ValueError,'Ambiguous CTER'):
            map_terminal_oxygens([pdb_atom(1,'O',(1,2,3)),pdb_atom(2,'OT1',(3,2,1))],'CTER','P000')
    def test_standalone_executable_adapter_records_version_and_hash(self):
        executable = Path(self.output.name)/'fake-psfgen'
        executable.write_text(f'#!{sys.executable}\nfrom pathlib import Path\n'
                              f'Path("prepared.pdb").write_text({PDB!r})\n'
                              f'Path("prepared.psf").write_text({PSF!r})\n'
                              'Path("engine-version.txt").write_text("2.0\\n")\n')
        executable.chmod(0o755)
        with patch.dict(os.environ, {'MOLVIS_PSFGEN': str(executable)}):
            result = prepare(generation_payload())
        engine = result['manifest']['details']['engine']
        self.assertEqual(engine['version'],'2.0')
        self.assertEqual(engine['name'],'standalone psfgen executable')
        self.assertEqual(engine['executable'],str(executable.resolve()))
        self.assertEqual(len(engine['executable_sha256']),64)

    def test_tcl_adapter_rejects_script_injection_and_wrong_settings(self):
        work = Path(self.output.name)
        for config in [dict(topologies=['x;exec bad'],segments=[],options=dict(histidine='HSE',first='NTER',last='CTER')),
                       dict(topologies=[],segments=[],options=dict(histidine='HSE',first='[exec bad]',last='CTER'))]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                write_script(work,config)

    def test_zero_exit_does_not_hide_engine_error(self):
        def failed_engine(*args, **kwargs):
            kwargs['stdout'].write('psfgen) ERROR! Failed to parse autogenerate statement.\n')
            kwargs['stdout'].flush()
            return subprocess.CompletedProcess(args[0],0)
        with patch('molvis.preparation.subprocess.run',side_effect=failed_engine):
            with self.assertRaises(ValueError) as error:
                prepare(generation_payload())
            self.assertIn('--psfgen /path/to/psfgen', str(error.exception))
            self.assertIn('Engine details:', str(error.exception))
            self.assertIn('Failed to parse autogenerate statement', str(error.exception))
    def test_protein_selection_excludes_water_ions_and_ligands_keeps_hydrogens(self):
        hydrogen = pdb_atom(5,'HN',(0,1,0))
        water = pdb_atom(6,'O',(6,0,0),residue=101).replace('ALA','HOH').replace('ATOM  ','HETATM')
        ion = pdb_atom(7,'CA',(7,0,0),residue=102).replace('ALA','CAL').replace('ATOM  ','HETATM')
        ligand = pdb_atom(8,'C1',(8,0,0),residue=103).replace('ALA','LIG').replace('ATOM  ','HETATM')
        protein, report = select_protein(PDB.replace('END',hydrogen+'\n'+water+'\n'+ion+'\n'+ligand))
        self.assertIn(hydrogen,protein)
        self.assertNotIn('HOH',protein)
        self.assertNotIn('CAL',protein)
        self.assertNotIn('LIG',protein)
        self.assertEqual(report['selected_atoms'],5)
        self.assertEqual(report['excluded_atoms'],3)
        self.assertEqual(report['excluded_by_residue']['HOH'],dict(residues=1,atoms=1))

    def test_selection_rejects_empty_multiple_models_and_retains_modified_backbone(self):
        with self.assertRaisesRegex(ValueError,'empty'):
            select_protein(pdb_atom(1,'O',(0,0,0)).replace('ALA','HOH'))
        with self.assertRaisesRegex(ValueError,'Multiple models'):
            select_protein('MODEL 1\n'+PDB+'MODEL 2\n'+PDB)
        with self.assertRaisesRegex(ValueError,'unsupported modified residues'):
            prepare(generation_payload() | {'pdb':PDB.replace('ALA','MSE')})
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

    def test_outputs_persist_and_preparations_do_not_overwrite(self):
        payload = dict(mode='upload',pdb=PDB,psf=PSF)
        first, second = prepare(payload), prepare(payload)
        self.assertNotEqual(first['storage']['directory'],second['storage']['directory'])
        saved = Path(first['storage']['directory'])
        self.assertEqual(saved.parent,Path(self.output.name).resolve())
        self.assertEqual((saved/'prepared.pdb').read_text(),PDB)
        self.assertEqual((saved/'prepared.psf').read_text(),PSF)
        self.assertEqual(json.loads((saved/'manifest.json').read_text())['storage'],first['storage'])
        self.assertEqual((saved/'preparation.zip').read_bytes(),base64.b64decode(first['bundle_base64']))
        self.assertFalse(list(Path(self.output.name).glob('.pending-*')))

    def test_storage_failure_is_not_reported_as_success(self):
        blocker = Path(self.output.name)/'not-a-folder'
        blocker.write_text('occupied')
        with patch.dict(os.environ, {'MOLVIS_OUTPUT_DIR':str(blocker)}):
            with self.assertRaisesRegex(ValueError,'Could not save preparation files'):
                prepare(dict(mode='upload',pdb=PDB,psf=PSF))

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
        self.assertEqual(plan['settings']['solvent_model'], 'deferred')
        self.assertEqual(plan['compatibility']['status'], 'not_checked')

    def test_segment_identity_supports_repeated_residue_numbers(self):
        pdb = pdb_atom(1,'CA',(0,0,0),chain=' ',segid='P000')+'\n'+pdb_atom(2,'CA',(1,0,0),chain=' ',segid='P001')
        self.assertEqual(inspect_pdb(pdb)['residue_count'],2)

    def test_generation_requires_review_and_supported_inputs(self):
        for changes in ({'confirm_guess':False}, {'topologies':[]}, {'pdb':PDB.replace('ALA','HOH')},
                        {'pdb':PDB.replace(' CA ',' XX ')}, {'options':{'histidine':'auto'}},
                        {'options':{'first':'[exec bad]'}},
                        {'options':{'hydrogens':'automatic'}},
                        {'topologies':[dict(name='../test.rtf',text=RTF)]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare(generation_payload() | changes)

    def test_runner_failure_and_timeout_surface_as_errors(self):
        with patch('molvis.preparation.subprocess.run', return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaisesRegex(ValueError,'could not prepare the structure'):
                prepare(generation_payload())
        with patch('molvis.preparation.subprocess.run', side_effect=subprocess.TimeoutExpired([],120)):
            with self.assertRaisesRegex(ValueError,'120 seconds'):
                prepare(generation_payload())


@unittest.skipUnless(os.environ.get('MOLVIS_PSFGEN') or importlib.util.find_spec('psfgen'), 'No native psfgen backend is configured')
class NativePreparationTests(StorageIsolation, unittest.TestCase):
    def test_rebuild_removes_input_hydrogens_only_from_engine_input(self):
        hydrogen = pdb_atom(5,'HN',(20,20,20))
        source = PDB.replace('END',hydrogen+'\nEND')
        payload = generation_payload() | {'pdb':source}
        retained = prepare(payload)
        self.assertEqual(next(a['xyz'] for a in retained['structure']['atoms'] if a['name']=='HN'), [20,20,20])
        payload['options']['hydrogens'] = 'rebuild'
        rebuilt = prepare(payload)
        self.assertNotEqual(next(a['xyz'] for a in rebuilt['structure']['atoms'] if a['name']=='HN'), [20,20,20])
        details = rebuilt['manifest']['details']
        self.assertNotIn('target_ph',details['protonation'])
        self.assertFalse(details['protonation']['automatic_ph_assignment'])
        self.assertEqual(details['hydrogen_handling']['removed_input_atoms'],1)
        saved = Path(rebuilt['storage']['directory'])
        self.assertIn(hydrogen,(saved/'source.pdb').read_text())
        self.assertIn(hydrogen,(saved/'protein.pdb').read_text())
        self.assertNotIn(hydrogen,(saved/'segments/segment-0.pdb').read_text())
        original = {a['name']:a['xyz'] for a in inspect_pdb(PDB)['atoms']}
        self.assertEqual({a['name']:a['xyz'] for a in rebuilt['structure']['atoms'] if a['name']!='HN'},original)

    def test_cter_native_generation_preserves_terminal_oxygens(self):
        terminal = '\n'.join(pdb_atom(i,name,xyz,residue=2) for i,(name,xyz) in enumerate([
            ('N',(4,0,0)),('CA',(5.45,0,0)),('C',(6,1.4,0)),('O',(5.7,2.5,0)),('OXT',(7.1,1.2,0))],5))
        source = PDB.replace('END',terminal+'\nEND')
        topology = RTF.rsplit('END',1)[0]+'''PRES CTER -0.5
GROUP
ATOM C C 0.5
ATOM OT1 O -0.5
ATOM OT2 O -0.5
DELETE ATOM O
BOND C OT1 C OT2
END
'''
        result = prepare(generation_payload() | dict(pdb=source,topologies=[dict(name='terminal-test.rtf',text=topology)],
                         options=dict(first='NONE',last='CTER',histidine='HSE')))
        details = result['manifest']['details']
        self.assertEqual(details['terminal_coordinate_check']['mapped_atoms'],2)
        self.assertEqual(details['terminal_coordinate_check']['max_displacement_angstrom'],0)
        output = {(a['residue_id'],a['name']):a['xyz'] for a in result['structure']['atoms']}
        self.assertEqual(output[('2','OT1')],[5.7,2.5,0])
        self.assertEqual(output[('2','OT2')],[7.1,1.2,0])
        self.assertEqual(output[('1','O')],[1.7,2.5,0])
        self.assertNotIn('failed to set coordinate for atom O',details['log'])
        saved = Path(result['storage']['directory'])
        self.assertEqual((saved/'source.pdb').read_text(),source)
        self.assertIn('OXT',(saved/'protein.pdb').read_text())
        self.assertIn('OT2',(saved/'segments'/'segment-0.pdb').read_text())
    def test_generation_with_crystal_water_saves_original_and_protein_selection(self):
        water = pdb_atom(9,'O',(9,0,0),residue=101).replace('ALA','HOH').replace('ATOM  ','HETATM')
        source = PDB.replace('END',water+'\nEND')
        result = prepare(generation_payload() | {'pdb':source})
        self.assertEqual(result['structure']['atom_count'],5)
        selection = result['manifest']['details']['selection']
        self.assertEqual(selection['excluded_by_residue']['HOH']['residues'],1)
        saved = Path(result['storage']['directory'])
        self.assertEqual((saved/'source.pdb').read_text(),source)
        self.assertNotIn('HOH',(saved/'protein.pdb').read_text())
        self.assertNotIn('HOH',result['pdb'])
    def test_real_psfgen_generation_and_round_trip(self):
        result = prepare(generation_payload())
        self.assertEqual(result['structure']['atom_count'],5)
        self.assertIn('HN',[a['name'] for a in result['structure']['atoms']])
        engine = result['manifest']['details']['engine']
        if os.environ.get('MOLVIS_PSFGEN'):
            self.assertGreaterEqual(int(engine['version'].split('.')[0]),2)
            self.assertEqual(engine['name'],'standalone psfgen executable')
            self.assertEqual(len(engine['executable_sha256']),64)
            self.assertTrue((Path(result['storage']['directory'])/'prepare.tcl').is_file())
        else:
            self.assertEqual(engine['version'],'1.0.5')
        saved = Path(result['storage']['directory'])
        self.assertEqual((saved/'source.pdb').read_text(),PDB)
        self.assertEqual((saved/'topologies'/'0-test.rtf').read_text(),RTF)
        self.assertTrue((saved/'psfgen.log').is_file())
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['bundle_base64']))) as bundle:
            self.assertEqual(bundle.read('source.pdb').decode(),PDB)
        uploaded = prepare(dict(mode='upload',pdb=result['pdb'],psf=result['psf']))
        self.assertEqual(uploaded['manifest']['pair'],result['manifest']['pair'])
        self.assertEqual(create_plan(dict(pdb=result['pdb'],psf=result['psf']))['preparation']['pair']['atom_count'],5)


if __name__ == '__main__':
    unittest.main()
