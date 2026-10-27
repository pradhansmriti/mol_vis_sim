"""Standalone psfgen preparation and conservative PSF/PDB pairing checks."""
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import zipfile
from uuid import uuid4

from .planning import inspect_pdb

LIMIT = 5_000_000
PROTEIN = set('ALA ARG ASN ASP CYS GLN GLU GLY HIS HSD HSE HSP ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split())


def output_root():
    return Path(os.environ.get('MOLVIS_OUTPUT_DIR', str(Path(__file__).resolve().parent.parent / 'runs' / 'preparations'))).expanduser().resolve()


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def text_file(value, label):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > LIMIT or '\x00' in value:
        raise ValueError(f'{label} must be nonempty text smaller than 5 MB.')
    return value


def validate_pair(pdb, psf):
    structure = inspect_pdb(pdb)
    psf = text_file(psf, 'PSF')
    lines = psf.splitlines()
    if not lines[0].split() or lines[0].split()[0] != 'PSF':
        raise ValueError('Expected a text CHARMM/X-PLOR PSF file.')
    headers = [i for i, line in enumerate(lines) if '!NATOM' in line]
    if len(headers) != 1:
        raise ValueError('PSF must have one !NATOM section.')
    try:
        start = headers[0]
        count = int(lines[start].split()[0])
        if count != structure['atom_count']:
            raise ValueError('PSF/PDB atom counts differ.')
        records = lines[start+1:start+1+count]
        for i, (line, atom) in enumerate(zip(records, structure['atoms']), 1):
            fields = line.split()
            if len(fields) < 8 or int(fields[0]) != i:
                raise ValueError('Invalid or nonsequential PSF atom table.')
            if (fields[2], fields[3], fields[4]) != (atom['residue_id'], atom['residue'], atom['name']):
                raise ValueError(f'PSF/PDB atom order or identity differs at atom {i}.')
            if atom['segment_id'] and fields[1] != atom['segment_id']:
                raise ValueError(f'PSF/PDB segment differs at atom {i}.')
            charge, mass = float(fields[6]), float(fields[7])
            if not math.isfinite(charge) or not math.isfinite(mass) or mass < 0:
                raise ValueError('PSF charges and masses must be finite; masses cannot be negative.')
        if len(records) != count:
            raise ValueError('Truncated PSF atom table.')
    except (IndexError, TypeError) as exc:
        raise ValueError('Invalid PSF atom table.') from exc
    return dict(atom_count=count, pdb_sha256=digest(pdb), psf_sha256=digest(psf),
                validation='Atom count, ordered identity, segment IDs when present, charges and masses checked. Bonded terms and force-field parameters are not validated.')


def uploaded_files(payload, key, required=False):
    values = payload.get(key, [])
    if not isinstance(values, list) or len(values) > 12 or (required and not values):
        raise ValueError(f'Provide {"1–12" if required else "up to 12"} {key} files.')
    result = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError(f'Invalid {key} upload.')
        name = item.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', name) or name.startswith('.'):
            raise ValueError('Use simple filenames with letters, numbers, dots, underscores or hyphens.')
        result.append(dict(name=name, text=text_file(item.get('text'), name)))
    return result


def prepare(payload):
    mode = payload.get('mode')
    pdb = text_file(payload.get('pdb'), 'PDB')
    parameters = uploaded_files(payload, 'parameters')
    if mode == 'upload':
        psf = text_file(payload.get('psf'), 'PSF')
        pair = validate_pair(pdb, psf)
        return preparation_result(pdb, psf, mode, parameters, pair, {}, [])
    if mode != 'generate':
        raise ValueError('Choose generate or upload preparation mode.')
    topology = uploaded_files(payload, 'topologies', required=True)
    structure = inspect_pdb(pdb)
    if structure['heterogens'] or any(a['residue'] not in PROTEIN for a in structure['atoms']):
        raise ValueError('Generation currently supports standard proteins only. Prepare ligands, water, ions or modified residues externally, then upload the PSF/PDB pair.')
    # Never connect across unreviewed chain breaks or rebuild a missing backbone.
    residues = {}
    segments = {}
    for atom in structure['atoms']:
        key = (atom['chain'], atom['segment_id'])
        residues.setdefault((*key, atom['residue_id']), set()).add(atom['name'])
        segments.setdefault(key, [])
    if len(segments) > 99:
        raise ValueError('At most 99 protein segments are supported.')
    if any(not {'N', 'CA', 'C', 'O'} <= names for names in residues.values()):
        raise ValueError('A residue is missing backbone N/CA/C/O atoms. Repair missing residues or heavy atoms explicitly before generation.')
    if any(not re.fullmatch(r'-?\d+', key[2]) for key in residues):
        raise ValueError('Resolve residue insertion codes before generation.')
    for line in pdb.splitlines():
        if line[:6].strip() in ('ATOM', 'HETATM'):
            segments[(line[21:22].strip(), line[72:76].strip())].append(line)
    for key, lines in segments.items():
        order = list(dict.fromkeys(line[22:26].strip() for line in lines))
        if any(int(b) != int(a)+1 for a, b in zip(order, order[1:])):
            raise ValueError('A segment has a residue-number gap. Split or repair chain breaks before generation.')
        # TER within a single named segment would otherwise silently reconnect it.
    terminated = set()
    last = None
    for line in pdb.splitlines():
        if line[:6].strip() == 'TER' and last is not None:
            terminated.add(last)
        elif line[:6].strip() == 'ATOM':
            last = (line[21:22].strip(), line[72:76].strip())
            if last in terminated:
                raise ValueError('A TER-separated segment reuses a chain/segment ID. Assign distinct IDs before generation.')
    options = payload.get('options', {})
    if not isinstance(options, dict):
        raise ValueError('Preparation options must be an object.')
    histidine = options.get('histidine', 'HSE')
    if histidine not in ('HSE', 'HSD', 'HSP'):
        raise ValueError('Choose HSE, HSD or HSP for HIS residues.')
    first, last = options.get('first', 'NTER'), options.get('last', 'CTER')
    if first not in ('NTER', 'NONE') or last not in ('CTER', 'NONE'):
        raise ValueError('Choose NTER/CTER or NONE termini patches.')
    options = dict(histidine=histidine, first=first, last=last)
    if payload.get('confirm_guess') is not True:
        raise ValueError('Confirm hydrogen/missing-atom coordinate generation and the displayed protonation and termini choices.')
    with TemporaryDirectory(prefix='molvis-prep-') as directory:
        work = Path(directory)
        config = dict(options=options, topologies=[], segments=[])
        for i, item in enumerate(topology):
            name = f'topology-{i}.rtf'
            (work / name).write_text(item['text'])
            config['topologies'].append(name)
        mapping = []
        for i, (key, lines) in enumerate(segments.items()):
            name, segid = f'segment-{i}.pdb', f'P{i:03d}'
            (work / name).write_text('\n'.join(lines)+'\nEND\n')
            config['segments'].append(dict(segid=segid, pdb=name))
            mapping.append(dict(chain=key[0], input_segment=key[1], output_segment=segid))
        (work / 'config.json').write_text(json.dumps(config))
        worker = Path(__file__).with_name('preparation_worker.py')
        python = os.environ.get('MOLVIS_PREP_PYTHON', sys.executable)
        with (work / 'psfgen.log').open('w') as log:
            try:
                process = subprocess.run([python, str(worker), str(work)], stdout=log, stderr=subprocess.STDOUT, timeout=120, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('Preparation exceeded 120 seconds. No prepared pair was accepted.') from exc
            except OSError as exc:
                raise ValueError('Preparation Python is unavailable. Install the server environment from environment.yml.') from exc
        log = (work / 'psfgen.log').read_text(errors='replace')[-100_000:]
        if (work / 'engine-output.log').exists():
            log += (work / 'engine-output.log').read_text(errors='replace')[-100_000:]
        if process.returncode:
            raise ValueError('Standalone psfgen preparation failed. '+log[-6000:])
        for name in ('prepared.pdb', 'prepared.psf'):
            if not (work / name).is_file() or (work / name).stat().st_size > LIMIT:
                raise ValueError('psfgen did not produce a supported PSF/PDB pair.')
        result_pdb, psf = (work / 'prepared.pdb').read_text(), (work / 'prepared.psf').read_text()
        pair = validate_pair(result_pdb, psf)
        detail = dict(options=options, segments=mapping, input_sha256=digest(pdb),
                      topologies=[dict(name=f['name'], sha256=digest(f['text'])) for f in topology],
                      engine=json.loads((work / 'engine.json').read_text()), log=log)
        return preparation_result(result_pdb, psf, mode, parameters, pair, detail, topology, source_pdb=pdb)


def preparation_result(pdb, psf, mode, parameters, pair, detail, topologies, source_pdb=None):
    preparation_id = str(uuid4())
    root = output_root()
    destination = root / preparation_id
    storage = dict(id=preparation_id, directory=str(destination),
                   pdb=str(destination / 'prepared.pdb'), psf=str(destination / 'prepared.psf'),
                   manifest=str(destination / 'manifest.json'), bundle=str(destination / 'preparation.zip'),
                   download_urls={name: f'/api/preparations/{preparation_id}/files/{name}'
                                  for name in ('prepared.pdb', 'prepared.psf', 'manifest.json', 'preparation.zip')})
    manifest = dict(mode=mode, state='pair_checked', pair=pair, details=detail,
                    storage=storage,
                    parameters=[dict(name=f['name'], sha256=digest(f['text'])) for f in parameters],
                    simulation_ready=False,
                    notes=['Review generated coordinates and all protonation/termini choices.',
                           'Disulfide bonds and custom patches are not inferred; upload an externally prepared pair when needed.',
                           'Matching CHARMM parameter files and physical validation are required before simulation.'])
    files = {'prepared.pdb': pdb, 'prepared.psf': psf, 'manifest.json': json.dumps(manifest, indent=2)}
    if source_pdb is not None:
        files['source.pdb'] = source_pdb
    if detail:
        files['psfgen.log'] = detail['log']
    for kind, items in [('topologies', topologies), ('parameters', parameters)]:
        for i, item in enumerate(items):
            files[f'{kind}/{i}-{item["name"]}'] = item['text']
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name, text in files.items():
            bundle.writestr(name, text)
    # Publish a complete folder only after every file has been written. Failures
    # leave no successful-looking result, and unique IDs prevent overwrites.
    try:
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.pending-', dir=root) as staging:
            stage = Path(staging) / 'result'
            stage.mkdir()
            for name, text in files.items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding='utf-8')
            (stage / 'preparation.zip').write_bytes(archive.getvalue())
            stage.rename(destination)
    except OSError as exc:
        raise ValueError(f'Could not save preparation files under {root}. Check the server output directory and available disk space.') from exc
    return dict(pdb=pdb, psf=psf, manifest=manifest, structure=inspect_pdb(pdb),
                storage=storage,
                bundle_base64=base64.b64encode(archive.getvalue()).decode())
