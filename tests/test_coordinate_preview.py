"""Simulation-step output schedules must match actual engine states."""
import csv
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from molvis.telemetry import CoordinatePreview, Measurements


@unittest.skipUnless(importlib.util.find_spec('openmm'), 'OpenMM is optional')
class CoordinatePreviewTests(unittest.TestCase):
    def test_independent_step_intervals_and_actual_positions(self):
        import openmm as mm
        from openmm import app, unit
        topology=app.Topology();chain=topology.addChain('A');residue=topology.addResidue('ALA',chain)
        topology.addAtom('CA',app.element.carbon,residue)
        topology.addAtom('O',app.element.oxygen,residue)
        system=mm.System();system.addParticle(12);system.addParticle(16)
        simulation=app.Simulation(topology,system,mm.VerletIntegrator(.002),mm.Platform.getPlatformByName('Reference'))
        simulation.context.setPositions([[1,2,3],[4,5,6]]*unit.nanometer)
        with TemporaryDirectory() as directory:
            root=Path(directory);preview=CoordinatePreview(root,topology,7)
            measurements=Measurements(root,300)
            reporter=measurements.dynamics_reporter(6,10)
            preview.capture(simulation)
            first=json.loads((root/'coordinates.json').read_text())
            self.assertEqual(first['atoms'][0]['xyz'],[10,20,30])
            self.assertEqual(len(first['atoms']),1)
            with patch.object(simulation.context,'getState',side_effect=AssertionError('unnecessary coordinate read')):
                preview.capture(simulation)
                simulation.currentStep=1;preview.capture(simulation)
            simulation.currentStep=0
            reporter.report(simulation,simulation.context.getState(getEnergy=True))
            simulation.reporters.extend([preview,reporter])
            frames=[]
            original=preview.capture
            def capture(*args,**kwargs):
                original(*args,**kwargs)
                frames.append(json.loads((root/'coordinates.json').read_text()))
            with patch.object(preview,'capture',side_effect=capture): simulation.step(31)
            measurements.close()
            self.assertEqual([frame['step'] for frame in frames],[7,14,21,28])
            self.assertAlmostEqual(frames[-1]['time_ps'],.056)
            rows=[json.loads(line) for line in (root/'measurements.jsonl').read_text().splitlines()]
            self.assertEqual([r['step'] for r in rows if r['temperature_k'] is not None],[0,10,20,30])
            self.assertEqual([r['step'] for r in rows if r['potential_energy_kj_mol'] is not None],[0,6,12,18,24,30])
            for row in rows:
                self.assertAlmostEqual(row['time_ps'],row['step']*.002)
            with (root/'dynamics.csv').open() as file: saved=list(csv.DictReader(file))
            self.assertEqual([int(r['step']) for r in saved],[r['step'] for r in rows])
            self.assertEqual(next(r for r in saved if r['step']=='6')['temperature_k'],'')
            simulation.context.setPositions([[float('nan'),0,0],[0,0,0]]*unit.nanometer)
            simulation.currentStep=35
            with self.assertRaisesRegex(ValueError,'Nonfinite'): preview.capture(simulation)
