"""Exercise real proteins through the HTTP API and benchmark coordinate reporting.

Supply previously checked preparation/environment directories and local force-field
files. All generated data stays in --output; inputs are never overwritten.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
from pathlib import Path
import statistics
import sys
import threading
import time
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile


def sha(data): return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ubiquitin',type=Path,required=True,help='Checked protein preparation directory')
    parser.add_argument('--villin',type=Path,required=True)
    parser.add_argument('--ubiquitin-environment',type=Path,required=True,help='Existing explicit environment with system.xml/state.xml')
    parser.add_argument('--villin-environment',type=Path,required=True)
    parser.add_argument('--toppar',type=Path,required=True)
    parser.add_argument('--psfgen',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--benchmark-steps',type=int,default=300)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--benchmark-only',action='store_true')
    parser.add_argument('--infrequent-coordinate-steps',type=int,default=100)
    args=parser.parse_args()
    if args.benchmark_steps<1 or args.repeats<1 or args.infrequent_coordinate_steps<1: parser.error('Benchmark steps and repeats must be positive.')
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    os.environ.update(MOLVIS_RUN_DIR=str(root/'live'),MOLVIS_ENVIRONMENT_DIR=str(root/'environments'),
                      MOLVIS_PSFGEN=str(args.psfgen.resolve()),MOLVIS_OPENMM_PYTHON=sys.executable,MOLVIS_OUTPUT_DIR=str(root/'preparations'))
    # Imported after the explicit output roots are configured.
    from http.server import ThreadingHTTPServer
    from molvis.__main__ import Handler
    from molvis import live_runs
    from molvis.preparation import validate_pair
    class QuietHandler(Handler):
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    (root/'server-url.txt').write_text(base)
    report=dict(protocol='Real 100-step readiness API runs; separate repeated fixed-state coordinate benchmarks.',
                tests=[],benchmarks=[],failures=[],inputs={})
    report['machine']=dict(os=platform.platform(),architecture=platform.machine(),python=sys.version,cpu_threads=1)
    report['inputs']['psfgen_sha256']=sha(args.psfgen.read_bytes())
    for name,directory in [('1UBQ',args.ubiquitin_environment),('1VII',args.villin_environment)]:
        report['inputs'][name+'_benchmark']={filename:sha((directory/filename).read_bytes()) for filename in ('system.xml','state.xml','solvated.psf')}
    def save(): (root/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    def request(path,payload=None):
        req=Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,
                    headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response: return response.read()
    def api(path,payload=None): return json.loads(request(path,payload))
    def upload(name):
        data=(args.toppar/name).read_bytes();report['inputs'][name]=sha(data)
        return dict(name=name,text=data.decode())
    topology=upload('top_all36_prot.rtf');parameter=upload('par_all36m_prot.prm');water=upload('toppar_water_ions.str')
    payloads={}
    for name,directory in [('1UBQ',args.ubiquitin),('1VII',args.villin)]:
        pdb=(directory/'prepared.pdb').read_text();psf=(directory/'prepared.psf').read_text()
        pair=validate_pair(pdb,psf);report['inputs'][name]=pair
        payloads[name]=dict(pdb=pdb,psf=psf,topologies=[topology],parameters=[parameter])
    def check_rejection(payload):
        try: api('/api/runs',payload)
        except HTTPError as error:
            assert error.code==400
            return json.loads(error.read())
        raise AssertionError('Invalid request was accepted')
    for value in (0,-1,1.5,True,100001):
        error=check_rejection(dict(payloads['1VII'],settings=dict(solvent_model='obc2',energy_interval_steps=value)))
        report['tests'].append(dict(test='invalid_interval',value=value,status='passed',error=error))
    bad=dict(payloads['1VII'],pdb=payloads['1UBQ']['pdb'],settings=dict(solvent_model='obc2'))
    report['tests'].append(dict(test='mismatched_pair',status='passed',error=check_rejection(bad)))
    def run_case(name,model,intervals,cancel=False):
        settings=dict(solvent_model=model,temperature_k=300,timestep_fs=2,
                      **{channel+'_interval_steps':n for channel,n in zip(('coordinates','energy','temperature'),intervals)})
        payload=dict(payloads[name],settings=settings,water=[water] if model=='charmm_tip3p' else [])
        started=time.monotonic();job=api('/api/runs',payload);identifier=job['id']
        print(f'START {name} {model} {intervals} cancel={cancel} {identifier}',flush=True)
        simultaneous=check_rejection(payload)
        seen=set(); stages=[];cancel_sent=False;live_samples=False;live_coordinates=False;max_bytes=0
        while True:
            raw=request(job['url']);max_bytes=max(max_bytes,len(raw));record=json.loads(raw)
            stage=record.get('progress',{}).get('stage')
            if not stages or stages[-1]!=stage: stages.append(stage)
            frame=record.get('coordinates')
            if frame: seen.add(frame['step'])
            active=record['status'] in ('queued','running','cancelling')
            if active:
                live_samples|=bool(record['samples']);live_coordinates|=bool(frame)
                if cancel and not cancel_sent and frame and frame['step']>=1:
                    api(job['url']+'/cancel',{});cancel_sent=True
            if not active: break
            if time.monotonic()-started>270: raise RuntimeError('API run exceeded harness deadline')
            time.sleep(.02 if cancel else .1)
        elapsed=time.monotonic()-started
        rows=record['samples']; dynamics=[r for r in rows if r['stage']=='dynamics']
        result=dict(test='cancel' if cancel else 'readiness',protein=name,model=model,id=identifier,
                    status=record['status'],elapsed_s=elapsed,intervals=settings,stages=stages,
                    live_samples=live_samples,live_coordinates=live_coordinates,observed_coordinate_steps=sorted(seen),
                    samples=len(rows),max_api_response_bytes=max_bytes,simultaneous_rejected=simultaneous,
                    result=record.get('result'))
        report['tests'].append(result);save()
        if cancel:
            assert cancel_sent and record['status']=='cancelled',record['status']
            assert rows and record.get('coordinates')
        else:
            assert record['status']=='completed',record.get('result')
            assert not record['result']['simulation_ready']
            for channel,field in [('energy','potential_energy_kj_mol'),('temperature','temperature_k')]:
                expected=list(range(0,101,settings[channel+'_interval_steps']))
                actual=[r['step'] for r in dynamics if r[field] is not None]
                assert actual==expected,(channel,actual,expected)
            assert frame['step']==100//intervals[0]*intervals[0],frame
            assert frame['sequence']==1+100//intervals[0],frame
            assert len(frame['atoms'])==(76 if name=='1UBQ' else 36)
        for sample in dynamics:
            assert math.isclose(sample['time_ps'],sample['step']*.002,abs_tol=1e-12)
            if sample['total_energy_kj_mol'] is not None:
                assert math.isclose(sample['total_energy_kj_mol'],sample['potential_energy_kj_mol']+sample['kinetic_energy_kj_mol'],abs_tol=1e-7)
        assert all(r['time_ps'] is None and r['temperature_k'] is None for r in rows if r['stage']=='minimization')
        downloaded=[json.loads(line) for line in request(job['url']+'/measurements.jsonl').decode().splitlines()]
        assert downloaded==rows
        csv_rows=list(csv.DictReader(io.StringIO(request(job['url']+'/measurements.csv').decode())))
        assert len(csv_rows)==len(rows)
        for saved,original in zip(csv_rows,rows):
            for field,value in original.items():
                assert saved[field]==('' if value is None else str(value)),(field,saved[field],value)
        if not cancel:
            urls=record['result']['storage']['download_urls']; contents={}
            for filename,url in urls.items(): contents[filename]=request(url)
            with zipfile.ZipFile(io.BytesIO(contents['environment.zip'])) as archive:
                for filename,data in contents.items():
                    if filename!='environment.zip': assert archive.read(filename)==data,filename
            psf=contents.get('solvated.psf',contents['prepared.psf']).decode()
            validate_pair(contents['readiness.pdb'].decode(),psf)
            if model=='charmm_tip3p':
                validate_pair(contents['solvated.pdb'].decode(),psf)
                assert record['result']['box']['water_molecules']>0
            result['download_hashes']={name:sha(data) for name,data in contents.items()}
        # Drop the finished in-memory job, then reconnect through HTTP to disk.
        live_runs._jobs[identifier]['thread'].join(5)
        with live_runs._lock: live_runs._jobs.pop(identifier)
        restored=api(job['url'])
        assert restored['samples']==rows and restored.get('coordinates')==frame
        assert restored['settings']==settings | {k:v for k,v in record['settings'].items() if k not in settings}
        result.update(checks='passed',reconnect_from_disk=True)
        save();print(f'PASS {name} {model} {record["status"]} {elapsed:.2f}s',flush=True)
    cases=[('1VII','obc2',(13,7,11)),('1UBQ','obc2',(7,6,10)),
           ('1VII','charmm_tip3p',(101,101,101)),('1UBQ','charmm_tip3p',(1,2,3))]
    try:
        if not args.benchmark_only:
            from molvis.validation import compare_pairs
            report['preparations']=[]
            for name,directory in [('1UBQ',args.ubiquitin),('1VII',args.villin)]:
                options=json.loads((directory/'manifest.json').read_text())['details']['options']
                generated=api('/api/prepare',dict(mode='generate',pdb=(directory/'source.pdb').read_text(),
                              topologies=[topology],parameters=[parameter],options=options,confirm_guess=True))
                comparison=compare_pairs(generated['storage']['directory'],directory)
                assert comparison['passed'],comparison
                uploaded=api('/api/prepare',dict(mode='upload',pdb=generated['pdb'],psf=generated['psf']))
                assert uploaded['pdb']==generated['pdb'] and uploaded['psf']==generated['psf']
                report['preparations'].append(dict(protein=name,status='passed',comparison=comparison,
                                                  generation_id=generated['storage']['id'],upload_id=uploaded['storage']['id']))
                save()
            for name,model,intervals in cases:
                try: run_case(name,model,intervals)
                except Exception as error:
                    report['failures'].append(dict(case=[name,model,intervals],error=f'{type(error).__name__}: {error}'));save()
                    print('FAIL',report['failures'][-1],flush=True)
            try: run_case('1UBQ','obc2',(1,1,1),cancel=True)
            except Exception as error:
                report['failures'].append(dict(case='cancel',error=f'{type(error).__name__}: {error}'));save()
        from openmm import app, unit
        import openmm as mm
        from molvis.telemetry import CoordinatePreview, Measurements
        report['openmm_version']=mm.__version__
        for name,directory in [('1VII',args.villin_environment),('1UBQ',args.ubiquitin_environment)]:
            system=mm.XmlSerializer.deserialize((directory/'system.xml').read_text())
            state_text=(directory/'state.xml').read_text()
            topology=app.CharmmPsfFile(str(directory/'solvated.psf')).topology
            integrator=mm.LangevinMiddleIntegrator(300*unit.kelvin,1/unit.picosecond,.002*unit.picosecond)
            integrator.setRandomNumberSeed(2026)
            simulation=app.Simulation(topology,system,integrator,mm.Platform.getPlatformByName('CPU'),{'Threads':'1'})
            for repeat in range(args.repeats):
                for interval in ([None,args.infrequent_coordinate_steps,1] if repeat%2==0 else [1,args.infrequent_coordinate_steps,None]):
                    simulation.context.setState(mm.XmlSerializer.deserialize(state_text));simulation.currentStep=0
                    simulation.reporters=[]
                    # Equal warm-up and initial state restoration for each measurement.
                    simulation.step(5)
                    simulation.context.setState(mm.XmlSerializer.deserialize(state_text));simulation.currentStep=0
                    with TemporaryDirectory(dir=root) as scratch:
                        work=Path(scratch);measurements=Measurements(work,300)
                        reporter=measurements.dynamics_reporter(10,10)
                        simulation.reporters=[reporter]
                        preview=None
                        if interval:
                            preview=CoordinatePreview(work,topology,interval)
                            simulation.reporters.append(preview)
                        before=time.perf_counter();simulation.step(args.benchmark_steps);elapsed=time.perf_counter()-before
                        measurements.close()
                        finite=math.isfinite(simulation.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole))
                        assert finite,'Nonfinite benchmark energy'
                        row=dict(protein=name,particles=system.getNumParticles(),repeat=repeat,coordinates_interval_steps=interval,
                                 dynamics_steps=args.benchmark_steps,elapsed_s=elapsed,finite_energy=finite,
                                 frames=preview.sequence if preview else 0)
                        report['benchmarks'].append(row);save();print('BENCH',json.dumps(row),flush=True)
            summary={}
            for interval in (None,args.infrequent_coordinate_steps,1):
                times=[r['elapsed_s'] for r in report['benchmarks'] if r['protein']==name and r['coordinates_interval_steps']==interval]
                summary[str(interval)]=dict(median_s=statistics.median(times),min_s=min(times),max_s=max(times))
            report.setdefault('benchmark_summary',{})[name]=summary;save()
            simulation.context.setState(mm.XmlSerializer.deserialize(state_text));simulation.currentStep=0
            captures=[]
            with TemporaryDirectory(dir=root) as scratch:
                for index in range(110):
                    preview=CoordinatePreview(Path(scratch),topology,1)
                    before=time.perf_counter();preview.capture(simulation,force=True)
                    if index>=10: captures.append((time.perf_counter()-before)*1000)
            report.setdefault('snapshot_cost',[]).append(dict(protein=name,samples=len(captures),
                median_ms=statistics.median(captures),p95_ms=sorted(captures)[94],max_ms=max(captures)))
            save()

    finally:
        server.shutdown();server.server_close();live_runs.shutdown();save()
    print('REPORT',root/'report.json',flush=True)
    if report['failures']: raise SystemExit(1)


if __name__=='__main__': main()
