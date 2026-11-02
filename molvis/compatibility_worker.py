"""Worker for a single parameter/energy check; never runs dynamics."""
import json
import math
from pathlib import Path
import sys


def run(work):
    try:
        import openmm as mm
        from openmm import app, unit
    except ImportError:
        return dict(status='unavailable', message='Install requirements-simulation.txt and configure MOLVIS_OPENMM_PYTHON to use that environment.')
    config = json.loads((work/'config.json').read_text())
    settings = config['settings']
    psf = app.CharmmPsfFile(str(work/'prepared.psf'))
    pdb = app.PDBFile(str(work/'prepared.pdb'))
    params = app.CharmmParameterSet(*(str(work/name) for name in config['topologies']+config['parameters']))
    model = {'vacuum':None, 'obc2':app.OBC2, 'gbn2':app.GBn2}[settings['solvent_model']]
    system = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=app.HBonds,
                              implicitSolvent=model, implicitSolventSaltConc=settings['salt_molar']*unit.molar,
                              temperature=settings['temperature_k']*unit.kelvin)
    if system.getNumParticles() != len(pdb.positions):
        raise ValueError('OpenMM particle count differs from prepared coordinates.')
    integrator = mm.VerletIntegrator(0.001*unit.picoseconds)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName('CPU'), {'Threads':'1'})
    context.setPositions(pdb.positions)
    state = context.getState(getEnergy=True, getForces=True)
    energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    forces = state.getForces().value_in_unit(unit.kilojoule_per_mole/unit.nanometer)
    if not math.isfinite(energy) or not all(math.isfinite(v) for force in forces for v in force):
        raise ValueError('OpenMM produced nonfinite energy or forces for these coordinates.')
    return dict(status='compatible', message='OpenMM created the selected system and evaluated finite energy and forces. No minimization or dynamics ran.',
                openmm_version=mm.__version__, particles=system.getNumParticles(), potential_energy_kj_mol=energy,
                platform='CPU', threads=1, constraints='HBonds')


if __name__ == '__main__':
    work = Path(sys.argv[1])
    try:
        result = run(work)
    except Exception as exc:
        result = dict(status='failed', message=f'{type(exc).__name__}: {exc}')
    (work/'result.json').write_text(json.dumps(result, allow_nan=False))
