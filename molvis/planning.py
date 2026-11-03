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
                        residue=line[17:21].strip(), chain=line[21:22].strip(),
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
    from .compatibility import solvent_settings, check_compatibility
    solvent = solvent_settings(settings)
    preparation_options = payload.get('preparation_options', {})
    if not isinstance(preparation_options, dict):
        raise ValueError('preparation_options must be an object.')
    protonation = 'Fixed by the supplied PSF; protonation and pH assignment are not inferred.' if pair else 'Review before preparation.'
    if pair and preparation_options:
        histidine = preparation_options.get('histidine')
        first, last = preparation_options.get('first'), preparation_options.get('last')
        if histidine not in ('HSE','HSD','HSP') or first not in ('NTER','NONE') or last not in ('CTER','NONE'):
            raise ValueError('Invalid preparation protonation choices.')
        protonation = f'Prepared with HIS→{histidine}, {first}/{last}; no automatic titration.'
    compatibility = dict(status='not_checked', simulation_ready=False,
                         message='Check the selected solvent and matching parameters in OpenMM.')
    if payload.get('check_compatibility') is True:
        if not pair:
            raise ValueError('Prepare a PSF/PDB pair before checking OpenMM compatibility.')
        compatibility = check_compatibility(payload)
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
                 ('configure', 'Configure OpenMM', f'Validate parameters for {solvent["solvent_label"]}.'),
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
        steps[2]['action'] = f'{solvent["solvent_label"]}: {compatibility["message"]}'
    if solvent['solvent_model'] == 'charmm_tip3p':
        steps.insert(2, dict(id='solvate', name='Build periodic water box (no ions)', state='proposed',
                            action=f'CHARMM-modified TIP3P; cubic padding {solvent["padding_nm"]:g} nm; PME, 1.2 nm cutoff / 1.0 nm switching. No Na+, Cl-, or neutralization.'))
    if solvent['solvent_model'] == 'deferred':
        steps.insert(2, dict(id='environment', name='Choose solvation and salt later', state='proposed',
                             action='After reviewing the prepared structure, choose solvent, salt, and any explicit water box before OpenMM validation.'))
    return dict(schema_version=1, id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(),
                state='proposed', execution_available=False,
                readiness_test_available=bool(pair),
                run_information=dict(complete_for_bounded_test=compatibility['status']=='compatible',
                                     environment_status=compatibility['status'], ensemble='NVT',
                                     production_runner_connected=False,
                                     note='A compatible System plus temperature, timestep, friction, seed and duration specifies an NVT run. Bounded readiness testing is separate from scientific equilibration and production review.'),
                compatibility=compatibility,
                request=str(payload.get('request', ''))[:2000],
                structure=structure,
                preparation=dict(mode='psf_pdb', pair=pair, options=preparation_options, simulation_ready=False) if pair else None,
                settings=dict(temperature_k=temperature, duration_ps=duration,
                              equilibration_ps=equilibration, timestep_fs=timestep,
                              production_steps=counts[0], equilibration_steps=counts[1],
                              engine='OpenMM', forcefield=['Matching CHARMM parameters required'] if pair else ['Select compatible force-field files before preparation'],
                              solvent=solvent['solvent_label'], solvent_model=solvent['solvent_model'],
                              salt_molar=solvent['salt_molar'], padding_nm=solvent['padding_nm'] if solvent['solvent_model']=='charmm_tip3p' else None,
                              periodic=solvent['periodic'], add_ions=False, neutralize=False,
                              nonbonded_cutoff_nm=solvent['nonbonded_cutoff_nm'], switch_distance_nm=solvent['switch_distance_nm'],
                              constraints='HBonds', nonbonded_method=solvent['nonbonded_method'],
                              integrator='LangevinMiddle', friction_per_ps=1, seed=2026,
                              protonation=protonation),
                decisions=['Confirm structure completeness and protonation.',
                           f'Selected solvent: {solvent["solvent_label"]}. Compatibility: {compatibility["status"]}. Matching CHARMM parameters are required.' if pair else 'Review force field, solvent, and minimization settings.',
                           'Choose compute platform and reporting interval.',
                           'Confirm whether preparatory equilibration is appropriate.'] +
                          ([f'Resolve non-protein components: {", ".join(structure["heterogens"])}.']
                           if structure['heterogens'] else []),
                steps=steps,
                events=[dict(id=1, step_id='inspect', level='info',
                             message='PDB coordinates parsed; scientific validation is pending.')])
