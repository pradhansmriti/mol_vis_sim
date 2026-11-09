"""Report local setup prerequisites without starting a server or a simulation."""
import os
from pathlib import Path
import subprocess
import sys

from .standalone_psfgen import executable_path


def python_module_available(python, module):
    try:
        result = subprocess.run([str(python), '-c', f'import {module}'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=20, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def setup_report(example_loader):
    rows = []
    executable = os.environ.get('MOLVIS_PSFGEN')
    if executable:
        try:
            executable_path(executable)
            rows.append(('Preparation', 'Available', 'Standalone psfgen executable found. Its version and topology compatibility are checked during preparation.'))
        except ValueError:
            rows.append(('Preparation', 'Needs setup', 'The configured psfgen executable was not found or is not executable. Check --psfgen or MOLVIS_PSFGEN.'))
    else:
        prep_python = os.environ.get('MOLVIS_PREP_PYTHON', sys.executable)
        if python_module_available(prep_python, 'psfgen'):
            rows.append(('Preparation', 'Available', 'Python psfgen found. For CHARMM36 AUTO parser errors, use standalone psfgen 2.x with --psfgen.'))
        else:
            rows.append(('Preparation', 'Needs setup', 'Use --psfgen /path/to/psfgen, or install requirements-preparation.txt in the preparation Python environment.'))

    local_python = Path(__file__).resolve().parent.parent / '.venv' / 'bin' / 'python'
    simulation_python = os.environ.get('MOLVIS_OPENMM_PYTHON', str(local_python) if local_python.is_file() else sys.executable)
    if python_module_available(simulation_python, 'openmm'):
        rows.append(('OpenMM', 'Available', f'OpenMM imports successfully using {simulation_python}.'))
    else:
        rows.append(('OpenMM', 'Needs setup', 'Install requirements-simulation.txt in .venv, or set MOLVIS_OPENMM_PYTHON to an interpreter with OpenMM.'))

    if not os.environ.get('MOLVIS_EXAMPLE_DIR'):
        rows.append(('Guided example', 'Not configured', 'Use --example-dir /path/to/example-folder; see the README for the required files.'))
    else:
        try:
            example = example_loader()
            from .preparation import validate_pair
            validate_pair(example['pdb'], example['psf'])
            rows.append(('Guided example', 'Available', 'Files can be read and the PDB/PSF pair passes basic checks. Parameter compatibility is checked by OpenMM.'))
        except ValueError as exc:
            rows.append(('Guided example', 'Needs setup', str(exc)))
    return rows
