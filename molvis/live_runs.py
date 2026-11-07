"""One bounded live run at a time, with persisted progress and measured samples."""
import json
import os
from pathlib import Path
import re
from shutil import copyfile
import threading
from uuid import uuid4

from .compatibility import check_compatibility, execute_worker, solvent_settings
from .preparation import validate_pair, text_file, uploaded_files

_lock=threading.RLock()
_jobs={}
_ids=re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')


def run_root():
    return Path(os.environ.get('MOLVIS_RUN_DIR',str(Path(__file__).resolve().parent.parent/'runs'/'live'))).resolve()


def persist(job):
    path=job['directory']/'run.json'; temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(job['record'],allow_nan=False,indent=2))
    temporary.replace(path)


def start_run(payload):
    validate_pair(text_file(payload.get('pdb'),'PDB'),text_file(payload.get('psf'),'PSF'))
    settings=solvent_settings(payload.get('settings',{}))
    if settings['solvent_model']=='deferred': raise ValueError('Choose a solvent model before starting a live run.')
    uploaded_files(payload,'parameters',required=True); uploaded_files(payload,'topologies')
    if settings['solvent_model']=='charmm_tip3p': uploaded_files(payload,'water',required=True)
    def run_worker(work, observe, cancel):
        return check_compatibility(dict(payload,test_dynamics=True), observer=observe,
                                   cancel_event=cancel, work_directory=work)
    return queue_run(settings, run_worker)


def resume_run(identifier, payload):
    with _lock:
        try:
            parent = read_run(identifier)
        except FileNotFoundError as exc:
            raise ValueError('Saved run not found.') from exc
        if not parent['can_resume']:
            raise ValueError('Choose a finished or interrupted run with a saved checkpoint.')
        source = run_root()/identifier/'worker'
        checkpoint = json.loads((source/'checkpoint.json').read_text())
        step = checkpoint['step']
        settings = solvent_settings(dict(parent['settings'], dynamics_steps=payload.get('dynamics_steps', 100)))
        history = [row for row in parent['samples'] if row['step'] is None or row['step'] <= step]
        resume = dict(run_id=identifier, step=step, time_ps=checkpoint['time_ps'])

        def run_worker(work, observe, cancel):
            work.mkdir()
            files = list(ARTIFACTS) + ['prepared.pdb', 'prepared.psf']
            if settings['periodic']:
                files.extend(['solvated.pdb', 'solvated.psf', 'box.json'])
            for name in files:
                copyfile(source/name, work/name)
            (work/'history.jsonl').write_text(encode_samples(history))
            config = dict(settings=settings, test_dynamics=True, resume=resume)
            (work/'config.json').write_text(json.dumps(config))
            previous = parent.get('result') or {}
            result = {key:previous[key] for key in ('pair', 'files', 'net_charge_e') if key in previous}
            result.update(settings=settings, simulation_ready=False, notes=previous.get('notes', []), resumed_from=resume)
            return execute_worker(work, settings, result, observe, cancel)

        return queue_run(settings, run_worker, history, resume)


def encode_samples(samples):
    return ''.join(json.dumps(row, allow_nan=False)+'\n' for row in samples)


def queue_run(settings, run_worker, history=(), resume=None):
    with _lock:
        if any(j['record']['status'] in ('queued','running','cancelling') for j in _jobs.values()):
            raise ValueError('A live run is already active. Wait for it or stop it before starting another.')
        identifier=str(uuid4()); directory=run_root()/identifier; directory.mkdir(parents=True)
        record=dict(id=identifier,status='queued',settings=settings,progress=dict(stage='queued'),result=None,
                    samples_url=f'/api/runs/{identifier}/measurements.jsonl',
                    note=f'Real measurements from a bounded {settings["dynamics_steps"]}-step NVT test; stabilization is not established.')
        if resume:
            record['resumed_from'] = resume
        job=dict(directory=directory,record=record,samples=list(history),cancel=threading.Event())
        (directory/'measurements.jsonl').write_text(encode_samples(history))
        persist(job)
        _jobs[identifier]=job
        def observe(event):
            with _lock:
                if event['type']=='progress': record['progress']=event['data']
                elif event['type']=='coordinates': record['coordinates']=event['data']
                else:
                    sample=event['data']
                    if history and sample['sequence'] <= history[-1]['sequence']:
                        return
                    job['samples'].append(sample)
                    with (directory/'measurements.jsonl').open('a') as file:
                        file.write(json.dumps(sample,allow_nan=False)+'\n')
                persist(job)
        def execute():
            with _lock: record['status']='running'; persist(job)
            try:
                result=run_worker(directory/'worker',observe,job['cancel'])
                with _lock:
                    record['result']=result
                    record['status']='completed' if result['status']=='compatible' else result['status']
            except Exception as exc:
                with _lock: record.update(status='failed',result=dict(status='failed',message=f'{type(exc).__name__}: {exc}'))
            finally:
                with _lock: persist(job)
        job['thread']=threading.Thread(target=execute,daemon=True); job['thread'].start()
        return dict(id=identifier,status='queued',url=f'/api/runs/{identifier}')


def read_run(identifier):
    if not _ids.fullmatch(identifier): raise ValueError('Invalid run ID.')
    with _lock:
        job=_jobs.get(identifier)
        if job:
            return json.loads(json.dumps(dict(job['record'],samples=job['samples'],**run_artifacts(identifier, job['record']['status'])),allow_nan=False))
        path=run_root()/identifier/'run.json'
        if not path.is_file(): raise FileNotFoundError('Run not found.')
        record=json.loads(path.read_text())
        if record['status'] in ('queued','running','cancelling'):
            record.update(status='interrupted',note='Server restarted; partial measurements retained. Run is not resumed automatically.')
        samples=run_root()/identifier/'measurements.jsonl'
        record['samples']=[json.loads(line) for line in samples.read_text().splitlines() if line.strip()]
        record.update(run_artifacts(identifier, record['status']))
        return record


def cancel_run(identifier):
    with _lock:
        if not _ids.fullmatch(identifier): raise ValueError('Invalid run ID.')
        job=_jobs.get(identifier)
        if job is None: raise ValueError('No active run with that ID.')
        if job['record']['status'] in ('queued','running','cancelling'):
            job['cancel'].set(); job['record']['status']='cancelling'; persist(job)
        return dict(id=identifier,status=job['record']['status'])


def shutdown():
    with _lock:
        jobs=list(_jobs.values())
        for job in jobs: job['cancel'].set()
    for job in jobs: job['thread'].join(timeout=5)


ARTIFACTS=('checkpoint.chk','checkpoint.json','state.xml','system.xml','integrator.xml')


def artifact_urls(identifier):
    return {name:f'/api/runs/{identifier}/files/{name}' for name in ARTIFACTS
            if (run_root()/identifier/'worker'/name).is_file()}


def run_artifacts(identifier, status):
    urls = artifact_urls(identifier)
    return dict(artifact_urls=urls,
                can_resume=status not in ('queued','running','cancelling') and all(name in urls for name in ARTIFACTS))
