"""Explicit solvent settings and isolated OpenMM compatibility checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from .planning import number
from .preparation import text_file, uploaded_files, validate_pair, digest

SOLVENTS = {'deferred':'Decide solvation and salt later', 'vacuum':'Vacuum', 'obc2':'Implicit OBC2', 'gbn2':'Implicit GBn2',
            'charmm_tip3p':'Explicit CHARMM-modified TIP3P'}


def solvent_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object.')
    model = settings.get('solvent_model', 'deferred')
    if model not in SOLVENTS:
        raise ValueError('Choose deferred, vacuum, obc2, gbn2 or charmm_tip3p solvent.')
    result = dict(solvent_model=model, solvent_label=SOLVENTS[model],
                salt_molar=number(settings, 'salt_molar', 0, 0, 2),
                padding_nm=number(settings, 'padding_nm', 1.0, 0.5, 5),
                temperature_k=number(settings, 'temperature_k', 300, 1, 500),
                nonbonded_method='PME' if model == 'charmm_tip3p' else 'NoCutoff')
    if model == 'deferred':
        result.update(salt_molar=None, padding_nm=None, nonbonded_method=None)
    return result


def check_compatibility(payload):
    pdb, psf = text_file(payload.get('pdb'), 'PDB'), text_file(payload.get('psf'), 'PSF')
    pair = validate_pair(pdb, psf)
    settings = solvent_settings(payload.get('settings', {}))
    parameters = uploaded_files(payload, 'parameters')
    topologies = uploaded_files(payload, 'topologies')
    result = dict(status='needs_input', settings=settings, pair=pair, simulation_ready=False,
                  notes=['Compatibility checks parameter coverage and finite energy; it does not validate protonation or simulation stability.',
                         'Protonation is fixed in the prepared PSF. A target pH does not retitrate it.'],
                  files={kind:[dict(name=f['name'],sha256=digest(f['text'])) for f in files]
                         for kind,files in [('topologies',topologies),('parameters',parameters)]})
    if settings['solvent_model'] == 'deferred':
        result.update(status='deferred', message='Solvation and salt will be chosen after protein preparation and structure review. No solvent compatibility check has run.')
        return result
    if settings['solvent_model'] == 'charmm_tip3p':
        result.update(status='requires_preparation', message='OpenMM supports CHARMM-modified TIP3P, but this platform has not built or validated an explicit water box.',
                      required=['Build water box and neutralizing ions with the chosen padding and salt concentration.',
                                'Supply matching CHARMM water/ion topology and parameters; generic TIP3P files are not interchangeable.',
                                'Validate the solvated PSF/PDB and periodic box before using PME.'])
        return result
    if settings['solvent_model'] == 'vacuum' and settings['salt_molar']:
        raise ValueError('Vacuum cannot have a salt concentration. Set salt to 0 M or select solvent.')
    if not parameters:
        result['message'] = 'Upload matching CHARMM parameter files to test this PSF/PDB and solvent in OpenMM.'
        return result
    if pair['atom_count'] > 20000:
        raise ValueError('Interactive compatibility checks are limited to 20000 atoms. Validate larger systems offline.')
    repository = Path(__file__).resolve().parent.parent
    local_python = repository/'.venv'/'bin'/'python'
    python = os.environ.get('MOLVIS_OPENMM_PYTHON', str(local_python) if local_python.is_file() else sys.executable)
    with TemporaryDirectory(prefix='molvis-compatibility-') as directory:
        work = Path(directory)
        (work/'prepared.pdb').write_text(pdb)
        (work/'prepared.psf').write_text(psf)
        config = dict(settings=settings, topologies=[], parameters=[])
        for kind, files in [('topologies',topologies),('parameters',parameters)]:
            for i, item in enumerate(files):
                name = f'{kind}-{i}-{item["name"]}'
                (work/name).write_text(item['text'])
                config[kind].append(name)
        (work/'config.json').write_text(json.dumps(config))
        try:
            process = subprocess.run([python, '-m', 'molvis.compatibility_worker', str(work)], cwd=repository,
                                     capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            result.update(status='failed', message='OpenMM compatibility check exceeded 120 seconds.')
            return result
        except OSError:
            result.update(status='unavailable', message='OpenMM interpreter could not be started. Check MOLVIS_OPENMM_PYTHON.')
            return result
        if not (work/'result.json').is_file():
            result.update(status='failed', message='OpenMM worker did not return a check result.', diagnostic=(process.stderr+process.stdout)[-4000:])
            return result
        result.update(json.loads((work/'result.json').read_text()))
        if process.returncode and result['status'] == 'compatible':
            result.update(status='failed', message='OpenMM worker exited unsuccessfully.')
    return result
