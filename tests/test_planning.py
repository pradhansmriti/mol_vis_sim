import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from molvis.planning import create_plan, inspect_pdb
from molvis.__main__ import Handler


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

    def test_plan_endpoint_and_invalid_json(self):
        status, data = self.request('POST', '/api/plan', json.dumps({'pdb': atom()}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['settings']['production_steps'], 5000)
        self.assertEqual(self.request('POST', '/api/plan', '{')[0], 400)
        self.assertEqual(self.request('POST', '/api/plan', '[]')[0], 400)

    def test_cross_site_request_rejected(self):
        self.assertEqual(self.request('POST', '/api/plan', '{}', {'Origin':'https://example.com'})[0], 403)


if __name__ == '__main__':
    unittest.main()
