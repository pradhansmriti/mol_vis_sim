import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from molvis.setup_check import setup_report


class SetupCheckTests(unittest.TestCase):
    def test_unconfigured_environment_reports_actions_without_loading_example(self):
        with patch.dict(os.environ, {}, clear=True), patch('molvis.setup_check.python_module_available', return_value=False):
            rows = dict((name, (status, message)) for name, status, message in setup_report(lambda: self.fail('example loader called')))
        self.assertEqual(rows['Preparation'][0], 'Needs setup')
        self.assertIn('--psfgen', rows['Preparation'][1])
        self.assertEqual(rows['OpenMM'][0], 'Needs setup')
        self.assertEqual(rows['Guided example'][0], 'Not configured')

    def test_bad_example_and_executable_are_reported(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'MOLVIS_PSFGEN': str(Path(folder) / 'missing'), 'MOLVIS_EXAMPLE_DIR': folder}), patch('molvis.setup_check.python_module_available', return_value=True):
            rows = dict((name, status) for name, status, _ in setup_report(lambda: (_ for _ in ()).throw(ValueError('Missing files'))))
        self.assertEqual(rows, {'Preparation': 'Needs setup', 'OpenMM': 'Available', 'Guided example': 'Needs setup'})

    def test_cli_check_does_not_start_server(self):
        env = dict(os.environ)
        for name in ('MOLVIS_PSFGEN', 'MOLVIS_PREP_PYTHON', 'MOLVIS_EXAMPLE_DIR'):
            env.pop(name, None)
        result = subprocess.run([sys.executable, '-m', 'molvis', '--check-setup'], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Guided example: Not configured', result.stdout)
        self.assertNotIn('Workspace:', result.stdout)


if __name__ == '__main__':
    unittest.main()
