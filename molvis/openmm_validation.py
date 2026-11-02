"""Local CHARMM parameter and bounded vacuum minimization diagnostic."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from .validation import load_pair


def file_record(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def finite_metrics(state, unit):
    energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    forces = state.getForces().value_in_unit(unit.kilojoule_per_mole / unit.nanometer)
    components = [float(v) for force in forces for v in force]
    if not math.isfinite(energy) or not components or not all(math.isfinite(v) for v in components):
        raise ValueError('OpenMM returned nonfinite energy or forces.')
    return dict(potential_energy_kj_mol=energy,
                force_rms_per_component_kj_mol_nm=math.sqrt(sum(v*v for v in components)/len(components)),
                maximum_atom_force_kj_mol_nm=max(math.sqrt(sum(v*v for v in force)) for force in forces))


def coordinates_pdb(original, positions):
    """Preserve PSF-compatible PDB names/order/segments while changing positions."""
    output, index = [], 0
    for line in original.splitlines():
        if line[:6].strip() in ('ATOM', 'HETATM'):
            xyz = positions[index]; index += 1
            if not all(math.isfinite(v) and -999.999 <= v <= 9999.999 for v in xyz):
                raise ValueError('Minimized coordinate cannot be represented in PDB format.')
            line = line[:30]+''.join(f'{v:8.3f}' for v in xyz)+line[54:]
        output.append(line)
    if index != len(positions):
        raise ValueError('Minimized coordinate count differs from PDB.')
    return '\n'.join(output)+'\n'


def validate(preparation, topologies, parameters, output, max_iterations=200, tolerance=10.0, platform='CPU'):
    if not isinstance(max_iterations, int) or not 1 <= max_iterations <= 10000:
        raise ValueError('Use 1–10000 minimization iterations.')
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('Force tolerance must be finite and positive.')
    if not topologies or not parameters:
        raise ValueError('Supply topology and parameter files explicitly.')
    import openmm as mm
    from openmm import app, unit

    preparation = Path(preparation).resolve()
    atoms, initial_coordinates, _ = load_pair(preparation)
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    report = dict(status='started', diagnostic='isolated protein in vacuum; no solvent, periodic box, restraints or dynamics',
                  simulation_ready=False, openmm_version=mm.__version__,
                  inputs=dict(pdb=file_record(preparation/'prepared.pdb'), psf=file_record(preparation/'prepared.psf'),
                              topologies=[file_record(p) for p in topologies], parameters=[file_record(p) for p in parameters]),
                  settings=dict(nonbonded_method='NoCutoff', constraints=None, platform=platform,
                                max_iterations=max_iterations, force_tolerance_kj_mol_nm=tolerance))
    try:
        psf = app.CharmmPsfFile(str(preparation/'prepared.psf'))
        pdb = app.PDBFile(str(preparation/'prepared.pdb'))
        params = app.CharmmParameterSet(*(str(Path(p).resolve()) for p in [*topologies, *parameters]))
        system = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
        if system.getNumParticles() != len(atoms) or len(pdb.positions) != len(atoms):
            raise ValueError('OpenMM particle count differs from validated PSF/PDB pair.')
        report.update(parameter_coverage='system_created', particles=system.getNumParticles(),
                      forces=[system.getForce(i).__class__.__name__ for i in range(system.getNumForces())])
        integrator = mm.VerletIntegrator(0.001*unit.picoseconds)
        selected_platform = mm.Platform.getPlatformByName(platform)
        properties = {'Threads':'1'} if platform == 'CPU' else {}
        report['settings']['platform_properties'] = properties
        context = mm.Context(system, integrator, selected_platform, properties)
        context.setPositions(pdb.positions)
        before = context.getState(getEnergy=True, getForces=True)
        report['before'] = finite_metrics(before, unit)
        mm.LocalEnergyMinimizer.minimize(context, tolerance*unit.kilojoule_per_mole/unit.nanometer, max_iterations)
        after = context.getState(getEnergy=True, getForces=True, getPositions=True)
        report['after'] = finite_metrics(after, unit)
        positions = after.getPositions().value_in_unit(unit.angstrom)
        report['heavy_atom_rms_displacement_angstrom'] = math.sqrt(
            sum(math.dist(xyz, positions[i])**2 for i,(key,xyz) in enumerate(initial_coordinates.items()) if atoms[key]['mass']>3.5)
            / sum(a['mass']>3.5 for a in atoms.values()))
        if report['after']['potential_energy_kj_mol'] > report['before']['potential_energy_kj_mol']+1e-6:
            raise ValueError('Minimization increased the potential energy.')
        minimized = coordinates_pdb((preparation/'prepared.pdb').read_text(), positions)
        from .preparation import validate_pair
        validate_pair(minimized, (preparation/'prepared.psf').read_text())
        (root/'minimized.pdb').write_text(minimized)
        (root/'prepared.psf').write_bytes((preparation/'prepared.psf').read_bytes())
        (root/'system.xml').write_text(mm.XmlSerializer.serialize(system))
        (root/'state.xml').write_text(mm.XmlSerializer.serialize(after))
        report.update(status='passed', result='Finite energies/forces and non-increasing energy under bounded minimization; convergence is not asserted.')
        del context, integrator
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        (root/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', required=True)
    parser.add_argument('--topology', action='append', required=True)
    parser.add_argument('--parameters', action='append', required=True)
    parser.add_argument('--output', required=True, help='New output directory; existing folders are never overwritten')
    parser.add_argument('--max-iterations', type=int, default=200)
    parser.add_argument('--tolerance', type=float, default=10.0, help='Force tolerance in kJ/mol/nm')
    parser.add_argument('--platform', choices=['CPU', 'Reference'], default='CPU')
    args = parser.parse_args()
    result = validate(args.preparation, args.topology, args.parameters, args.output,
                      args.max_iterations, args.tolerance, args.platform)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
