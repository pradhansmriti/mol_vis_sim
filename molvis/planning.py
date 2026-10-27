"""Inspectable plans. This module never launches dynamics or repairs structures."""
import hashlib
import math
from datetime import datetime, timezone
from uuid import uuid4


def inspect_pdb(text):
    if not isinstance(text, str) or len(text.encode()) > 5_000_000:
        raise ValueError('Provide a PDB file smaller than 5 MB.')
    atoms, seen, residues = [], set(), set()
    models = 0
    for line in text.splitlines():
        record = line[:6].strip()
        if record == 'MODEL':
            models += 1
            if models > 1:
                raise ValueError('Multiple models found. Select one model before uploading.')
        if record not in ('ATOM', 'HETATM'):
            continue
        try:
            atom = dict(name=line[12:16].strip(), altloc=line[16:17].strip(),
                        residue=line[17:20].strip(), chain=line[21:22].strip(),
                        residue_id=line[22:27].strip(), segment_id=line[72:76].strip(), record=record,
                        xyz=[float(line[start:start+8]) for start in (30, 38, 46)])
        except ValueError as exc:
            raise ValueError('An atom has invalid PDB coordinates.') from exc
        if not all(math.isfinite(v) for v in atom['xyz']):
            raise ValueError('Atom coordinates must be finite.')
        key = (atom['chain'], atom['segment_id'], atom['residue_id'], atom['name'])
        if atom['altloc'] or key in seen:
            raise ValueError('Alternate or duplicate atom positions found. Resolve these before planning.')
        seen.add(key)
        residues.add((atom['chain'], atom['segment_id'], atom['residue_id'], atom['residue']))
        atoms.append(atom)
    if not atoms:
        raise ValueError('No ATOM or HETATM records found. Use fixed-column PDB format.')
    heterogens = sorted({a['residue'] for a in atoms if a['record'] == 'HETATM'})
    return dict(atoms=atoms, atom_count=len(atoms), residue_count=len(residues),
                chains=sorted({a['chain'] for a in atoms}), heterogens=heterogens,
                sha256=hashlib.sha256(text.encode()).hexdigest())


def number(settings, key, default, low, high):
    value = settings.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f'{key} must be a number.')
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{key} must be a number.') from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key} must be between {low} and {high}.')
    return value


def create_plan(payload):
    structure = inspect_pdb(payload.get('pdb', ''))
    pair = None
    if payload.get('psf') is not None:
        from .preparation import validate_pair
        pair = validate_pair(payload['pdb'], payload['psf'])
    settings = payload.get('settings', {})
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object.')
    temperature = number(settings, 'temperature_k', 300, 1, 500)
    duration = number(settings, 'duration_ps', 10, .001, 1000)
    equilibration = number(settings, 'equilibration_ps', 0, 0, 1000)
    timestep = number(settings, 'timestep_fs', 2, .1, 2)
    counts = []
    for time in (duration, equilibration):
        count = time * 1000 / timestep
        if not math.isclose(count, round(count), abs_tol=1e-7, rel_tol=0):
            raise ValueError('Durations must be an exact multiple of the timestep.')
        counts.append(round(count))
    steps = [dict(id=key, name=name, state='proposed', action=action)
             for key, name, action in [
                 ('inspect', 'Inspect structure', 'Check completeness, termini, chains and non-protein components.'),
                 ('prepare', 'Prepare protein', 'Review protonation and hydrogen addition; no automatic repair.'),
                 ('configure', 'Configure OpenMM', 'Validate templates and the proposed implicit-solvent settings.'),
                 ('minimize', 'Minimize energy', 'Review tolerance and iteration limit before execution.'),
             ]]
    if equilibration:
        steps.append(dict(id='equilibrate', name='Equilibrate', state='proposed',
                          action=f'{equilibration:g} ps preparatory dynamics', steps=counts[1]))
    steps.extend([dict(id='dynamics', name='Production dynamics', state='proposed',
                       action=f'{duration:g} ps requested dynamics', steps=counts[0]),
                  dict(id='analyze', name='Analyze and export', state='proposed',
                       action='Report traces and outputs; execution success does not establish convergence.')])
    if pair:
        steps[1].update(name='Review prepared PSF/PDB', action='Atom pairing checked; review protonation, patches and generated coordinates.')
        steps[2]['action'] = 'Load the PSF with matching CHARMM parameters; solvent and parameter compatibility remain unresolved.'
    return dict(schema_version=1, id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(),
                state='proposed', execution_available=False,
                request=str(payload.get('request', ''))[:2000],
                structure=structure,
                preparation=dict(mode='psf_pdb', pair=pair, simulation_ready=False) if pair else None,
                settings=dict(temperature_k=temperature, duration_ps=duration,
                              equilibration_ps=equilibration, timestep_fs=timestep,
                              production_steps=counts[0], equilibration_steps=counts[1],
                              engine='OpenMM', forcefield=['Matching CHARMM parameters required'] if pair else ['amber14-all.xml', 'implicit/obc2.xml'],
                              solvent='Unresolved for supplied PSF' if pair else 'implicit OBC2', constraints='HBonds', nonbonded_method='NoCutoff',
                              integrator='LangevinMiddle', friction_per_ps=1, seed=2026,
                              protonation='Unresolved — review before preparation'),
                decisions=['Confirm structure completeness and protonation.',
                           'Supply matching CHARMM parameters and select a compatible solvent model.' if pair else 'Review force field, solvent, and minimization settings.',
                           'Choose compute platform and reporting interval.',
                           'Confirm whether preparatory equilibration is appropriate.'] +
                          ([f'Resolve non-protein components: {", ".join(structure["heterogens"])}.']
                           if structure['heterogens'] else []),
                steps=steps,
                events=[dict(id=1, step_id='inspect', level='info',
                             message='PDB coordinates parsed; scientific validation is pending.')])
