"""Explicit solvent settings and isolated OpenMM compatibility checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import time
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
                salt_molar=number(settings, 'salt_molar', 0.2 if model in ('obc2','gbn2') else 0, 0, 2),
                padding_nm=number(settings, 'padding_nm', 1.0, 0.5, 5),
                temperature_k=number(settings, 'temperature_k', 300, 1, 500),
                nonbonded_method='PME' if model == 'charmm_tip3p' else 'NoCutoff',
                periodic=model == 'charmm_tip3p', add_ions=False, neutralize=False,
                nonbonded_cutoff_nm=1.2 if model == 'charmm_tip3p' else None,
                switch_distance_nm=1.0 if model == 'charmm_tip3p' else None,
                timestep_fs=number(settings, 'timestep_fs', 2, .1, 2))
    for channel in ('coordinates','energy','temperature'):
        key=channel+'_interval_steps'
        value=number(settings,key,10,1,100000)
        if not value.is_integer(): raise ValueError(f'{key} must be a whole number of simulation steps.')
        result[key]=int(value)
    if model == 'charmm_tip3p' and result['salt_molar']:
        raise ValueError('Explicit water currently adds no ions. Salt must be 0 M; neutralization is disabled.')
    if settings.get('add_ions') or settings.get('neutralize'):
        raise ValueError('Ion addition and neutralization are disabled in this workflow.')
    if model == 'deferred':
        result.update(salt_molar=None, padding_nm=None, nonbonded_method=None)
    return result


def observe_worker(command, repository, work, observer, cancel_event):
    """Poll flushed worker data without keeping the HTTP request open."""
    position=0; last_progress=None; last_frame=None
    def drain():
        nonlocal position,last_progress,last_frame
        coordinates=work/'coordinates.json'
        if coordinates.is_file():
            try: frame=json.loads(coordinates.read_text())
            except (ValueError,OSError): frame=None
            if frame and frame['sequence']!=last_frame:
                observer(dict(type='coordinates',data=frame)); last_frame=frame['sequence']
        progress=work/'progress.json'
        if progress.is_file():
            try: current=json.loads(progress.read_text())
            except (ValueError,OSError): current=None
            if current and current!=last_progress:
                observer(dict(type='progress',data=current)); last_progress=current
        samples=work/'measurements.jsonl'
        if samples.is_file():
            with samples.open('rb') as file:
                file.seek(position)
                for line in file:
                    if not line.endswith(b'\n'): break
                    observer(dict(type='sample',data=json.loads(line)))
                    position+=len(line)
    with (work/'worker.log').open('w') as log:
        process=subprocess.Popen(command,cwd=repository,stdout=log,stderr=subprocess.STDOUT,start_new_session=os.name=='posix')
        deadline=time.monotonic()+240
        def stop():
            if process.poll() is None:
                try:
                    if os.name=='posix': os.killpg(process.pid,signal.SIGTERM)
                    else: process.terminate()
                except ProcessLookupError: pass
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name=='posix': os.killpg(process.pid,signal.SIGKILL)
                    else: process.kill()
                    process.wait()
        try:
            while process.poll() is None:
                drain()
                if cancel_event is not None and cancel_event.is_set():
                    stop(); drain()
                    return subprocess.CompletedProcess(command,-1),True
                if time.monotonic()>deadline:
                    stop(); drain(); raise subprocess.TimeoutExpired(command,240)
                time.sleep(.1)
            drain()
        except BaseException:
            stop(); raise
    return subprocess.CompletedProcess(command,process.returncode,stdout='',stderr=(work/'worker.log').read_text(errors='replace')[-4000:]),False


def check_compatibility(payload, observer=None, cancel_event=None):
    pdb, psf = text_file(payload.get('pdb'), 'PDB'), text_file(payload.get('psf'), 'PSF')
    pair = validate_pair(pdb, psf)
    settings = solvent_settings(payload.get('settings', {}))
    parameters = uploaded_files(payload, 'parameters')
    topologies = uploaded_files(payload, 'topologies')
    water = uploaded_files(payload, 'water')
    result = dict(status='needs_input', settings=settings, pair=pair, simulation_ready=False,
                  notes=['Compatibility checks parameter coverage and finite energy; it does not validate protonation or simulation stability.',
                         'Protonation is fixed in the prepared PSF. A target pH does not retitrate it.'],
                  files={kind:[dict(name=f['name'],sha256=digest(f['text'])) for f in files]
                         for kind,files in [('topologies',topologies),('parameters',parameters),('water',water)]})
    if settings['solvent_model'] == 'deferred':
        result.update(status='deferred', message='Solvation and salt will be chosen after protein preparation and structure review. No solvent compatibility check has run.')
        return result
    if settings['solvent_model'] == 'charmm_tip3p' and not water:
        result.update(status='needs_input', message='Upload toppar_water_ions.str (CHARMM TIP3 water topology/parameters) to build the periodic water box. No ions will be added.',
                      required=['Supply the local CHARMM water stream file as well as matching protein parameters.'])
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
        config = dict(settings=settings, topologies=[], parameters=[], water=[], test_dynamics=payload.get('test_dynamics') is True)
        for kind, files in [('topologies',topologies),('parameters',parameters),('water',water)]:
            for i, item in enumerate(files):
                name = f'{kind}-{i}-{item["name"]}'
                (work/name).write_text(item['text'])
                config[kind].append(name)
        (work/'config.json').write_text(json.dumps(config))
        try:
            command=[python,'-m','molvis.compatibility_worker',str(work)]
            if observer:
                process,cancelled=observe_worker(command,repository,work,observer,cancel_event)
                if cancelled:
                    result.update(status='cancelled',message='OpenMM run cancelled. Partial measurements are retained in the live run record.')
                    return result
            else:
                process = subprocess.run(command, cwd=repository,
                                     capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            progress=json.loads((work/'progress.json').read_text()) if (work/'progress.json').is_file() else {}
            result.update(status='incomplete', message='OpenMM environment/readiness check exceeded 240 seconds; no successful readiness result was accepted.', progress=progress)
            return result
        except OSError:
            result.update(status='unavailable', message='OpenMM interpreter could not be started. Check MOLVIS_OPENMM_PYTHON.')
            return result
        if not (work/'result.json').is_file():
            result.update(status='failed', message='OpenMM worker did not return a check result.', diagnostic=(process.stderr+process.stdout)[-4000:])
            return result
        worker_result=json.loads((work/'result.json').read_text())
        worker_notes=worker_result.pop('notes',[])
        result.update(worker_result)
        result['notes'].extend(worker_notes)
        if process.returncode and result['status'] == 'compatible':
            result.update(status='failed', message='OpenMM worker exited unsuccessfully.')
        if result['status'] == 'compatible':
            from .environment_storage import save_environment
            result['storage'] = save_environment(work, result)
    return result
