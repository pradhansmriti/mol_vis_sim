"""Environment builder and explicitly requested bounded OpenMM readiness test."""
import json
import math
from pathlib import Path
import sys
import time


def atomic_write(path, content):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_bytes(content)
    temporary.replace(path)


def run(work):
    started=time.monotonic()
    def progress(stage, **values):
        temporary=work/'progress.tmp'
        temporary.write_text(json.dumps(dict(stage=stage,elapsed_seconds=time.monotonic()-started,**values)))
        temporary.replace(work/'progress.json')
    progress('loading parameters')
    try:
        import openmm as mm
        from openmm import app, unit
    except ImportError:
        return dict(status='unavailable', message='Install requirements-simulation.txt and configure MOLVIS_OPENMM_PYTHON to use that environment.')
    config = json.loads((work/'config.json').read_text())
    settings = config['settings']
    resume = config.get('resume')
    if resume:
        progress('loading checkpoint')
        saved = json.loads((work/'checkpoint.json').read_text())
        if saved['openmm_version'] != mm.__version__ or saved['platform'] != 'CPU':
            raise ValueError('Checkpoint requires the original OpenMM version and CPU platform.')
        box = json.loads((work/'box.json').read_text()) if settings['periodic'] else None
        topology = app.CharmmPsfFile(str(work/('solvated.psf' if box else 'prepared.psf'))).topology
        system = mm.XmlSerializer.deserialize((work/'system.xml').read_text())
        integrator = mm.XmlSerializer.deserialize((work/'integrator.xml').read_text())
        simulation = app.Simulation(topology, system, integrator, mm.Platform.getPlatformByName('CPU'), {'Threads':'1'})
        simulation.loadCheckpoint(str(work/'checkpoint.chk'))
        time_ps = simulation.context.getState().getTime().value_in_unit(unit.picosecond)
        if simulation.currentStep != resume['step'] or not math.isclose(time_ps, saved['time_ps'], abs_tol=1e-9):
            raise ValueError('Checkpoint step or time differs from the saved run metadata.')
        report = dict(status='compatible', openmm_version=mm.__version__, platform='CPU', threads=1,
                      particles=system.getNumParticles(), box=box, resumed_from=resume)
    else:
        simulation, report, box = build_simulation(work, settings, config, progress, mm, app, unit)
    context, system, integrator, topology = simulation.context, simulation.system, simulation.integrator, simulation.topology
    if config.get('test_dynamics'):
        from .telemetry import Measurements, CoordinatePreview
        history = [json.loads(line) for line in (work/'history.jsonl').read_text().splitlines()] if resume else []
        measurements=Measurements(work,settings['temperature_k'],history)
        preview=CoordinatePreview(work,topology,settings['coordinates_interval_steps'])
        start_step = simulation.currentStep
        steps = settings['dynamics_steps']
        end_step = start_step + steps
        if not resume:
            measurements.emit('minimization',report_index=0,potential_energy_kj_mol=report['potential_energy_kj_mol'])
            progress('bounded minimization')
            mm.LocalEnergyMinimizer.minimize(context,10*unit.kilojoule_per_mole/unit.nanometer,20,measurements.minimization_reporter())
            context.setVelocitiesToTemperature(settings['temperature_k']*unit.kelvin,2026)
        progress('NVT integration',step=start_step,total_steps=end_step)
        preview.capture(simulation,force=True)
        reporter=measurements.dynamics_reporter(settings['energy_interval_steps'],settings['temperature_interval_steps'])
        if not resume:
            reporter.report(simulation,context.getState(getEnergy=True))
        simulation.reporters.append(reporter)
        simulation.reporters.append(preview)
        def checkpoint():
            for name,content in [('checkpoint.chk',context.createCheckpoint()),
                                 ('state.xml',mm.XmlSerializer.serialize(context.getState(getPositions=True,getVelocities=True,getEnergy=True)).encode()),
                                 ('checkpoint.json',json.dumps(dict(step=simulation.currentStep,time_ps=simulation.currentStep*settings['timestep_fs']/1000,openmm_version=mm.__version__,platform='CPU')).encode())]:
                atomic_write(work/name,content)
        atomic_write(work/'system.xml',mm.XmlSerializer.serialize(system).encode())
        atomic_write(work/'integrator.xml',mm.XmlSerializer.serialize(integrator).encode())
        checkpoint()
        while simulation.currentStep<end_step:
            simulation.step(min(100,end_step-simulation.currentStep))
            checkpoint()
            progress('NVT integration',step=simulation.currentStep,total_steps=end_step,
                     time_ps=simulation.currentStep*settings['timestep_fs']/1000)

        measurements.close()
        state=context.getState(getEnergy=True,getForces=True,getPositions=True,getVelocities=True)
        energy=state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
        xyz=state.getPositions().value_in_unit(unit.angstrom)
        forces=state.getForces().value_in_unit(unit.kilojoule_per_mole/unit.nanometer)
        if not math.isfinite(energy) or not all(math.isfinite(v) for group in (xyz,forces) for vector in group for v in vector):
            raise ValueError('Readiness dynamics produced nonfinite coordinates, forces or energy.')
        from .openmm_validation import coordinates_pdb
        original=work/('solvated.pdb' if box else 'prepared.pdb')
        (work/'readiness.pdb').write_text(coordinates_pdb(original.read_text(),xyz))
        report.update(readiness=dict(passed=True,minimization_max_iterations=0 if resume else 20,start_step=start_step,end_step=end_step,dynamics_steps=steps,
                                     timestep_fs=settings['timestep_fs'],duration_ps=steps*settings['timestep_fs']/1000,
                                     final_potential_energy_kj_mol=energy,ensemble='NVT',seed=2026,
                                     friction_per_ps=1,elapsed_seconds=time.monotonic()-started,
                                     note='Bounded execution smoke test, not equilibration or production validation.'),
                      message=f'OpenMM ran bounded minimization and {steps} NVT steps with finite results. Equilibration is not established; production execution is not connected.')
        if resume:
            report['message'] = f'Continued NVT from checkpoint step {start_step} to {end_step}.'
        report['measurements']=dict(samples=measurements.sequence,
                                    coordinates_interval_steps=settings['coordinates_interval_steps'],
                                    energy_interval_steps=settings['energy_interval_steps'],
                                    temperature_interval_steps=settings['temperature_interval_steps'],
                                    temperature_source='OpenMM StateDataReporter, including constraint-adjusted degrees of freedom',
                                    minimization_axis='optimizer reports; iteration index may restart during constraint enforcement',
                                    dynamics_axis='simulation time in ps')
    if not config.get('test_dynamics'):
        atomic_write(work/'system.xml',mm.XmlSerializer.serialize(system).encode())
    progress('complete')
    return report


def build_simulation(work, settings, config, progress, mm, app, unit):
    psf = app.CharmmPsfFile(str(work/'prepared.psf'))
    pdb = app.PDBFile(str(work/'prepared.pdb'))
    params = app.CharmmParameterSet(*(str(work/name) for name in config['topologies']+config['parameters']+config.get('water',[])))
    positions=pdb.positions; box=None
    if settings['solvent_model']=='charmm_tip3p':
        progress('building water box')
        from .waterbox import build_waterbox
        system,positions,box=build_waterbox(work,psf,pdb,params,settings)
    else:
        model = {'vacuum':None, 'obc2':app.OBC2, 'gbn2':app.GBn2}[settings['solvent_model']]
        system = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=app.HBonds,
                              implicitSolvent=model, implicitSolventSaltConc=settings['salt_molar']*unit.molar,
                              temperature=settings['temperature_k']*unit.kelvin)
    if system.getNumParticles() != len(positions):
        raise ValueError('OpenMM particle count differs from prepared coordinates.')
    integrator = mm.LangevinMiddleIntegrator(settings['temperature_k']*unit.kelvin,1/unit.picosecond,settings['timestep_fs']*unit.femtoseconds)
    integrator.setRandomNumberSeed(2026)
    topology=app.CharmmPsfFile(str(work/'solvated.psf')).topology if box else psf.topology
    simulation=app.Simulation(topology,system,integrator,mm.Platform.getPlatformByName('CPU'),{'Threads':'1'})
    context=simulation.context
    context.setPositions(positions)
    progress('evaluating initial energy')
    state = context.getState(getEnergy=True, getForces=True)
    energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    forces = state.getForces().value_in_unit(unit.kilojoule_per_mole/unit.nanometer)
    if not math.isfinite(energy) or not all(math.isfinite(v) for force in forces for v in force):
        raise ValueError('OpenMM produced nonfinite energy or forces for these coordinates.')
    report=dict(status='compatible', message='OpenMM created the selected system and evaluated finite energy and forces. No minimization or dynamics ran.',
                openmm_version=mm.__version__, particles=system.getNumParticles(), potential_energy_kj_mol=energy,
                platform='CPU', threads=1, constraints='HBonds', box=box,
                net_charge_e=sum(float(atom.charge) for atom in psf.atom_list),
                implicit_salt_note='Default is 0.2 M ionic screening; the selected concentration is recorded above. No discrete ions are added. OpenMM OBC2/GBn2 are not NAMD GBIS.' if settings['solvent_model'] in ('obc2','gbn2') else None)
    if box:
        report['notes']=['Explicit water uses PME periodic boundaries with no Na+, Cl-, or neutralization ions.']
        if abs(report['net_charge_e'])>1e-4:
            report['notes'].append(f'Solute net charge remains {report["net_charge_e"]:.4g} e; review charged periodic-system electrostatics before production.')
    return simulation, report, box


if __name__ == '__main__':
    work = Path(sys.argv[1])
    try:
        result = run(work)
    except Exception as exc:
        result = dict(status='failed', message=f'{type(exc).__name__}: {exc}')
    (work/'result.json').write_text(json.dumps(result, allow_nan=False))
