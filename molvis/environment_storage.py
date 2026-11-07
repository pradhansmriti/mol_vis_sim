"""Persist complete environment/readiness artifacts separately from preparation."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import zipfile

DOWNLOADS = ('prepared.pdb','prepared.psf','solvated.pdb','solvated.psf','system.xml','manifest.json','environment.zip',
             'readiness.pdb','state.xml','checkpoint.chk','checkpoint.json','integrator.xml','measurements.jsonl','measurements.csv','dynamics.csv')


def environment_root():
    return Path(os.environ.get('MOLVIS_ENVIRONMENT_DIR', str(Path(__file__).resolve().parent.parent/'runs'/'environments'))).expanduser().resolve()


def save_environment(work, result):
    root = environment_root(); root.mkdir(parents=True, exist_ok=True)
    identifier = str(uuid4()); destination = root/identifier
    files = {name:(work/name).read_bytes() for name in DOWNLOADS if name not in ('manifest.json','environment.zip') and (work/name).is_file()}
    storage = dict(id=identifier,directory=str(destination),
                   download_urls={name:f'/api/environments/{identifier}/files/{name}' for name in [*files,'manifest.json','environment.zip']})
    files['manifest.json'] = json.dumps(dict(result,storage=storage),indent=2,allow_nan=False).encode()
    try:
        with TemporaryDirectory(prefix='.pending-',dir=root) as scratch:
            stage = Path(scratch)/'result'; stage.mkdir()
            for name, data in files.items(): (stage/name).write_bytes(data)
            for name in ('psfgen-water.log','water-prepare.tcl','box.json'):
                if (work/name).is_file(): (stage/name).write_bytes((work/name).read_bytes())
            with zipfile.ZipFile(stage/'environment.zip','w',zipfile.ZIP_DEFLATED) as bundle:
                for path in stage.iterdir():
                    if path.name != 'environment.zip': bundle.write(path,path.name)
            stage.rename(destination)
    except OSError as exc:
        raise ValueError('Could not save the complete environment output folder.') from exc
    return storage
