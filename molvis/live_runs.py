"""One bounded live run at a time, with persisted progress and measured samples."""
import json
import os
from pathlib import Path
import re
import threading
from uuid import uuid4

from .compatibility import check_compatibility, solvent_settings
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
    with _lock:
        if any(j['record']['status'] in ('queued','running','cancelling') for j in _jobs.values()):
            raise ValueError('A live run is already active. Wait for it or stop it before starting another.')
        identifier=str(uuid4()); directory=run_root()/identifier; directory.mkdir(parents=True)
        record=dict(id=identifier,status='queued',settings=settings,progress=dict(stage='queued'),result=None,
                    samples_url=f'/api/runs/{identifier}/measurements.jsonl',
                    note='Real measurements from a bounded 100-step readiness run; stabilization is not established.')
        job=dict(directory=directory,record=record,samples=[],cancel=threading.Event())
        _jobs[identifier]=job; (directory/'measurements.jsonl').write_text(''); persist(job)
        def observe(event):
            with _lock:
                if event['type']=='progress': record['progress']=event['data']
                elif event['type']=='coordinates': record['coordinates']=event['data']
                else:
                    sample=event['data']; job['samples'].append(sample)
                    with (directory/'measurements.jsonl').open('a') as file:
                        file.write(json.dumps(sample,allow_nan=False)+'\n')
                persist(job)
        def execute():
            with _lock: record['status']='running'; persist(job)
            try:
                result=check_compatibility(dict(payload,test_dynamics=True),observer=observe,cancel_event=job['cancel'])
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
            return json.loads(json.dumps(dict(job['record'],samples=job['samples']),allow_nan=False))
        path=run_root()/identifier/'run.json'
        if not path.is_file(): raise FileNotFoundError('Run not found.')
        record=json.loads(path.read_text())
        if record['status'] in ('queued','running','cancelling'):
            record.update(status='interrupted',note='Server restarted; partial measurements retained. Run is not resumed automatically.')
        samples=run_root()/identifier/'measurements.jsonl'
        record['samples']=[json.loads(line) for line in samples.read_text().splitlines() if line.strip()]
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
