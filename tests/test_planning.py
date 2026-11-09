import json
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from molvis.planning import create_plan, inspect_pdb
from molvis.__main__ import Handler
from molvis import live_runs
from test_preparation import PDB, PSF, generation_payload


def atom(serial=1, x=1.0, altloc=' '):
    return f'ATOM  {serial:5d}  CA {altloc}ALA A{serial:4d}    {x:8.3f}{2.:8.3f}{3.:8.3f}  1.00 20.00           C  '


class PlanningTests(unittest.TestCase):
    def test_duration_and_preparation_are_separate(self):
        plan = create_plan({'pdb': atom(), 'settings': {'equilibration_ps': 2}})
        self.assertEqual(plan['settings']['production_steps'], 5000)
        self.assertEqual(plan['settings']['equilibration_steps'], 1000)
        self.assertFalse(plan['execution_available'])
        self.assertTrue(all(step['state'] == 'proposed' for step in plan['steps']))
        self.assertEqual(len(plan['structure']['sha256']), 64)

    def test_equilibration_is_not_silently_added(self):
        plan = create_plan({'pdb': atom()})
        self.assertNotIn('equilibrate', [s['id'] for s in plan['steps']])

    def test_reject_invalid_protocol_values(self):
        for settings in ({'temperature_k': 'nan'}, {'duration_ps': -1},
                         {'duration_ps': .003, 'timestep_fs': 2},
                         {'timestep_fs': 3}, {'temperature_k': True},
                         {'duration_ps': 'infinity'}, {'duration_ps': None}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                create_plan({'pdb': atom(), 'settings': settings})

    def test_reject_ambiguous_or_invalid_structures(self):
        for pdb in ('', 'not a PDB', atom(altloc='A'), atom()+'\n'+atom(),
                    'MODEL        1\n'+atom()+'\nENDMDL\nMODEL        2\n'+atom(),
                    atom(x=float('nan'))):
            with self.subTest(pdb=pdb), self.assertRaises(ValueError):
                inspect_pdb(pdb)

    def test_heterogens_are_decisions_not_silently_removed(self):
        pdb = atom().replace('ATOM  ', 'HETATM').replace('ALA', 'HOH')
        plan = create_plan({'pdb': pdb})
        self.assertEqual(plan['structure']['heterogens'], ['HOH'])
        self.assertIn('HOH', plan['decisions'][-1])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = TemporaryDirectory()
        cls.addClassCleanup(cls.output.cleanup)
        env = patch.dict(os.environ, {'MOLVIS_OUTPUT_DIR':cls.output.name,'MOLVIS_ENVIRONMENT_DIR':cls.output.name+'/environments','MOLVIS_RUN_DIR':cls.output.name+'/live'})
        env.start()
        cls.addClassCleanup(env.stop)
        cls.addClassCleanup(live_runs.shutdown)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_static_routes_and_traversal(self):
        for path in ('/', '/app.js', '/style.css'):
            self.assertEqual(self.request('GET', path)[0], 200)
        self.assertEqual(self.request('GET', '/../README.md')[0], 404)

    def test_guided_example_configuration(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'MOLVIS_EXAMPLE_DIR': folder}):
            status, data = self.request('GET', '/api/example')
            self.assertEqual(status, 404)
            self.assertIn('prepared.pdb', json.loads(data)['error'])
            for name, content in [('prepared.pdb', PDB), ('prepared.psf', PSF), ('par_all36m_prot.prm', '* test')]:
                (Path(folder) / name).write_text(content)
            status, data = self.request('GET', '/api/example')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)['pdb'], PDB)
            with patch('molvis.__main__.start_run', return_value={'id': 'example'}) as start:
                self.assertEqual(self.request('POST', '/api/example/run', '{}')[0], 202)
                self.assertEqual(start.call_args.args[0]['parameters'][0]['text'], '* test')

    def test_plan_endpoint_and_invalid_json(self):
        status, data = self.request('POST', '/api/plan', json.dumps({'pdb': atom()}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['settings']['production_steps'], 5000)
        self.assertEqual(self.request('POST', '/api/plan', '{')[0], 400)
        self.assertEqual(self.request('POST', '/api/plan', '[]')[0], 400)

    def test_cross_site_request_rejected(self):
        self.assertEqual(self.request('POST', '/api/plan', '{}', {'Origin':'https://example.com'})[0], 403)
        self.assertEqual(self.request('POST', '/api/compatibility', '{}', {'Origin':'https://example.com'})[0], 403)
        self.assertEqual(self.request('POST', '/api/readiness', '{}', {'Origin':'https://example.com'})[0], 403)
        self.assertEqual(self.request('POST', '/api/runs', '{}', {'Origin':'https://example.com'})[0], 403)
        self.assertEqual(self.request('POST', '/api/runs/12345678-1234-1234-1234-123456789abc/cancel', '{}', {'Origin':'https://example.com'})[0], 403)

    def test_live_run_endpoints_and_measurement_exports(self):
        def worker(payload,observer,cancel_event,work_directory):
            work_directory.mkdir(parents=True)
            (work_directory/'checkpoint.chk').write_bytes(b'checkpoint-test')
            (work_directory/'config.json').write_text('private worker configuration')
            observer(dict(type='sample',data=dict(sequence=1,stage='dynamics',step=10,time_ps=.02,temperature_k=301)))
            return dict(status='compatible',message='done')
        with patch('molvis.live_runs.check_compatibility',side_effect=worker):
            status,data=self.request('POST','/api/runs',json.dumps(dict(pdb=PDB,psf=PSF,settings=dict(solvent_model='vacuum'),parameters=[dict(name='test.prm',text='* test')])))
            self.assertEqual(status,202)
            identifier=json.loads(data)['id'];live_runs._jobs[identifier]['thread'].join(3)
        status,data=self.request('GET','/api/runs/'+identifier)
        self.assertEqual(status,200);self.assertEqual(json.loads(data)['samples'][0]['temperature_k'],301)
        status,data=self.request('GET','/api/runs/'+identifier+'/measurements.csv')
        self.assertEqual(status,200);self.assertIn(b'temperature_k',data);self.assertIn(b'301',data)
        status,data=self.request('GET','/api/runs/'+identifier+'/measurements.jsonl')
        self.assertEqual(json.loads(data)['step'],10)
        self.assertEqual(self.request('GET','/api/runs/'+identifier+'/files/checkpoint.chk'),(200,b'checkpoint-test'))
        self.assertEqual(self.request('GET','/api/runs/'+identifier+'/files/config.json')[0],404)
        self.assertEqual(self.request('GET','/?run='+identifier)[0],200)

    def test_unknown_live_run_and_invalid_start(self):
        self.assertEqual(self.request('GET','/api/runs/12345678-1234-1234-1234-123456789abc')[0],404)
        self.assertEqual(self.request('POST','/api/runs','{}')[0],400)

    def test_environment_download_allowlist_and_bytes(self):
        root=Path(self.output.name)/'environments'/'12345678-1234-1234-1234-123456789abc'
        root.mkdir(parents=True)
        (root/'solvated.pdb').write_bytes(b'CRYST1 test\n')
        route='/api/environments/'+root.name+'/files/'
        self.assertEqual(self.request('GET',route+'solvated.pdb'),(200,b'CRYST1 test\n'))
        self.assertEqual(self.request('GET',route+'private.key')[0],404)
        self.assertEqual(self.request('GET',route+'../../README.md')[0],404)

    def test_readiness_without_environment_does_not_run_dynamics(self):
        status,data=self.request('POST','/api/readiness',json.dumps(dict(pdb=PDB,psf=PSF)))
        self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['status'],'deferred')
        self.assertNotIn('readiness',json.loads(data))

    def test_compatibility_endpoint_needs_parameters(self):
        status, data = self.request('POST','/api/compatibility',json.dumps(dict(pdb=PDB,psf=PSF,settings=dict(solvent_model='obc2'))))
        self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['status'],'needs_input')

    def test_preparation_upload_endpoint(self):
        status, data = self.request('POST', '/api/prepare', json.dumps(dict(mode='upload',pdb=PDB,psf=PSF)))
        self.assertEqual(status,200)
        result = json.loads(data)
        status, data = self.request('POST', '/api/plan', json.dumps(dict(pdb=result['pdb'],psf=result['psf'])))
        self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['preparation']['pair']['atom_count'],4)
        self.assertEqual(self.request('POST', '/api/prepare', json.dumps(dict(mode='upload',pdb=PDB,psf='bad')))[0],400)
        self.assertEqual(self.request('POST', '/api/prepare', '{}', {'Origin':'https://example.com'})[0],403)

    def test_direct_downloads_match_persistent_files(self):
        status, data = self.request('POST', '/api/prepare', json.dumps(dict(mode='upload',pdb=PDB,psf=PSF)))
        self.assertEqual(status,200)
        result = json.loads(data)
        urls = result['storage']['download_urls']
        self.assertEqual(self.request('GET',urls['prepared.pdb']),(200,PDB.encode()))
        self.assertEqual(self.request('GET',urls['prepared.psf']),(200,PSF.encode()))
        self.assertEqual(json.loads(self.request('GET',urls['manifest.json'])[1]),result['manifest'])
        connection = HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('GET',urls['preparation.zip'])
        response = connection.getresponse()
        self.assertEqual(response.status,200)
        self.assertEqual(response.getheader('Content-Disposition'),'attachment; filename="preparation.zip"')
        self.assertEqual(response.getheader('Content-Type'),'application/zip')
        self.assertTrue(response.read().startswith(b'PK'))
        connection.close()
        self.assertEqual(self.request('GET',urls['prepared.pdb'].replace('prepared.pdb','../../README.md'))[0],404)
        self.assertEqual(self.request('GET','/api/preparations/00000000-0000-0000-0000-000000000000/files/prepared.pdb')[0],404)

    @unittest.skipUnless(os.environ.get('MOLVIS_PSFGEN') or importlib.util.find_spec('psfgen'), 'No native psfgen backend is configured')
    def test_native_generation_endpoint(self):
        status, data = self.request('POST', '/api/prepare', json.dumps(generation_payload()))
        self.assertEqual(status,200,data.decode())
        result = json.loads(data)
        self.assertEqual(result['manifest']['pair']['atom_count'],5)
        self.assertEqual(result['manifest']['mode'],'generate')


if __name__ == '__main__':
    unittest.main()
