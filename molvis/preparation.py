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
from .standalone_psfgen import executable_path, write_script, write_engine_record

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


def select_protein(pdb):
    """Protein-only selection for supported residues, retaining their hydrogens.

    Recognize unfamiliar residues with a peptide backbone too, so unsupported
    modified amino acids produce a review error instead of disappearing.
    This is a conservative local approximation of VMD's protein selection.
    """
    lines = pdb.splitlines()
    if sum(line[:6].strip() == 'MODEL' for line in lines) > 1:
        raise ValueError('Multiple models found. Select one model before uploading.')
    groups = {}
    def residue_key(line):
        return (line[21:22], line[72:76], line[22:27], line[17:20].strip())
    for line in lines:
        if line[:6].strip() in ('ATOM', 'HETATM'):
            groups.setdefault(residue_key(line), []).append(line)
    selected = {key for key, records in groups.items()
                if key[3] in PROTEIN or {'N', 'CA', 'C', 'O'} <= {line[12:16].strip() for line in records}}
    if not selected:
        raise ValueError('Protein selection is empty. Supply a PDB containing protein residues.')
    output, active = [], False
    for line in lines:
        record = line[:6].strip()
        if record in ('ATOM', 'HETATM') and residue_key(line) in selected:
            output.append(line)
            active = True
        elif record == 'TER' and active:
            output.append('TER')
            active = False
    excluded = {}
    for key, records in groups.items():
        if key not in selected:
            entry = excluded.setdefault(key[3], dict(residues=0, atoms=0))
            entry['residues'] += 1
            entry['atoms'] += len(records)
    protein = '\n'.join(output)+'\nEND\n'
    return protein, dict(selection='protein', implementation='Standard residue names or peptide-backbone recognition; supported standard proteins only.',
                         selected_atoms=sum(len(groups[key]) for key in selected),
                         selected_residues=len(selected), excluded_atoms=sum(item['atoms'] for item in excluded.values()),
                         excluded_by_residue=excluded, protein_pdb_sha256=digest(protein))


def map_terminal_oxygens(lines, last_patch, segid):
    """Change only CTER endpoint names; never modify the supplied coordinates."""
    if last_patch != 'CTER':
        return lines, []
    terminal_id = lines[-1][22:27].strip()
    terminal = [line for line in lines if line[22:27].strip() == terminal_id]
    names = {line[12:16].strip() for line in terminal}
    aliases = {'O': 'OT1', 'OXT': 'OT2'}
    for old, new in aliases.items():
        if old in names and new in names:
            raise ValueError(f'Ambiguous CTER oxygen names in segment {segid}, residue {terminal_id}: both {old} and {new} are present.')
    output, changes = [], []
    for line in lines:
        old = line[12:16].strip()
        if line[22:27].strip() == terminal_id and old in aliases:
            new = aliases[old]
            changes.append(dict(segment=segid, chain=line[21:22].strip(),
                                input_segment=line[72:76].strip(), residue_id=terminal_id,
                                residue=line[17:20].strip(), patch='CTER', source_name=old,
                                target_name=new, coordinates_angstrom=[float(line[i:i+8]) for i in (30,38,46)]))
            line = line[:12]+f'{new:^4}'+line[16:]
        output.append(line)
    return output, changes


def remove_input_hydrogens(lines):
    """Identify H/D/T by PDB element, falling back to the protein atom name."""
    kept, removed = [], []
    for line in lines:
        element = line[76:78].strip().upper()
        name = line[12:16].strip().lstrip('0123456789').upper()
        hydrogen = element in ('H', 'D', 'T') if element else name.startswith(('H', 'D', 'T'))
        if hydrogen:
            removed.append(dict(chain=line[21:22].strip(), input_segment=line[72:76].strip(),
                                residue_id=line[22:27].strip(), residue=line[17:20].strip(),
                                name=line[12:16].strip()))
        else:
            kept.append(line)
    return kept, removed


def verify_terminal_coordinates(pdb, changes):
    atoms = {(a['segment_id'], a['residue_id'], a['name']): a for a in inspect_pdb(pdb)['atoms']}
    maximum = 0.0
    for change in changes:
        atom = atoms.get((change['segment'], change['residue_id'], change['target_name']))
        expected = change['coordinates_angstrom']
        if atom is None or any(abs(a-b) > 0.00051 for a,b in zip(atom['xyz'],expected)):
            raise ValueError('psfgen did not preserve a mapped CTER oxygen coordinate; preparation was not accepted.')
        maximum = max(maximum, math.dist(atom['xyz'],expected))
    return dict(mapped_atoms=len(changes), coordinates_preserved=True, max_displacement_angstrom=maximum)


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
    source_pdb = pdb
    pdb, selection = select_protein(pdb)
    structure = inspect_pdb(pdb)
    if any(a['residue'] not in PROTEIN for a in structure['atoms']):
        raise ValueError('Protein selection contains unsupported modified residues. Prepare these externally and upload the PSF/PDB pair.')
    # Never connect across unreviewed chain breaks or rebuild a missing backbone.
    residues = {}
    segments = {}
    for atom in structure['atoms']:
        key = (atom['chain'], atom['segment_id'])
        residues.setdefault((*key, atom['residue_id']), set()).add(atom['name'])
        segments.setdefault(key, [])
    if len(segments) > 99:
        raise ValueError('At most 99 protein segments are supported.')
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
    hydrogens = options.get('hydrogens', 'retain')
    if hydrogens not in ('retain', 'rebuild'):
        raise ValueError('Choose retain or rebuild for input hydrogens.')
    options = dict(histidine=histidine, first=first, last=last, hydrogens=hydrogens)
    if payload.get('confirm_guess') is not True:
        raise ValueError('Confirm hydrogen/missing-atom coordinate generation and the displayed protonation and termini choices.')
    for key, lines in segments.items():
        terminal_id = lines[-1][22:27].strip()
        for residue_key, names in residues.items():
            if residue_key[:2] != key:
                continue
            oxygen_present = 'O' in names or (last == 'CTER' and residue_key[2] == terminal_id and 'OT1' in names)
            if not {'N', 'CA', 'C'} <= names or not oxygen_present:
                raise ValueError('A residue is missing backbone N/CA/C/O atoms. Repair missing residues or heavy atoms explicitly before generation.')
    with TemporaryDirectory(prefix='molvis-prep-') as directory:
        work = Path(directory)
        config = dict(options=options, topologies=[], segments=[])
        for i, item in enumerate(topology):
            name = f'topology-{i}.rtf'
            (work / name).write_text(item['text'])
            config['topologies'].append(name)
        mapping, terminal_changes, segment_files, removed_hydrogens = [], [], {}, []
        for i, (key, lines) in enumerate(segments.items()):
            name, segid = f'segment-{i}.pdb', f'P{i:03d}'
            if hydrogens == 'rebuild':
                lines, removed = remove_input_hydrogens(lines)
                removed_hydrogens.extend(removed)
            mapped_lines, changes = map_terminal_oxygens(lines, last, segid)
            terminal_changes.extend(changes)
            segment_files[name] = '\n'.join(mapped_lines)+'\nEND\n'
            (work / name).write_text(segment_files[name])
            config['segments'].append(dict(segid=segid, pdb=name))
            mapping.append(dict(chain=key[0], input_segment=key[1], output_segment=segid))
        (work / 'config.json').write_text(json.dumps(config))
        configured_executable = os.environ.get('MOLVIS_PSFGEN')
        executable = executable_path(configured_executable) if configured_executable else None
        if executable:
            write_script(work, config)
            command = [str(executable), 'prepare.tcl']
        else:
            worker = Path(__file__).with_name('preparation_worker.py')
            python = os.environ.get('MOLVIS_PREP_PYTHON', sys.executable)
            command = [python, str(worker), str(work)]
        with (work / 'psfgen.log').open('w') as log:
            try:
                process = subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('Preparation exceeded 120 seconds. No prepared pair was accepted.') from exc
            except OSError as exc:
                raise ValueError('Preparation backend could not be started. Check the configured psfgen executable or preparation Python.') from exc
        log = (work / 'psfgen.log').read_text(errors='replace')[-100_000:]
        if (work / 'engine-output.log').exists():
            log += (work / 'engine-output.log').read_text(errors='replace')[-100_000:]
        engine_error = re.search(r'(?im)^\s*(?:psfgen\)\s*)?(?:ERROR\b|FATAL\b|MOLVIS_PSFGEN_ERROR:)', log)
        if process.returncode or engine_error:
            if re.search(r'failed to parse autogenerate statement', log, re.I):
                message = ('psfgen could not read the topology’s AUTO statement. This can occur with the Python psfgen backend and CHARMM36 topology files. '
                           'Restart the server using a compatible standalone psfgen 2.x executable with --psfgen /path/to/psfgen, then retry preparation. '
                           'Keep the topology file unchanged. If the standalone executable also fails, check that the topology and psfgen versions are compatible.')
            elif 'No module named \'psfgen\'' in log:
                message = ('The preparation Python environment does not have psfgen installed. Install the preparation dependencies or restart the server with --psfgen /path/to/psfgen to use a standalone executable.')
            else:
                message = ('psfgen could not prepare the structure. Check the engine details for the first error and verify that the structure, topology files, and preparation settings are compatible.')
            raise ValueError(message + '\n\nEngine details:\n' + log[-6000:])
        if executable:
            write_engine_record(work, executable)
        for name in ('prepared.pdb', 'prepared.psf'):
            if not (work / name).is_file() or (work / name).stat().st_size > LIMIT:
                raise ValueError('psfgen did not produce a supported PSF/PDB pair.')
        result_pdb, psf = (work / 'prepared.pdb').read_text(), (work / 'prepared.psf').read_text()
        pair = validate_pair(result_pdb, psf)
        terminal_check = verify_terminal_coordinates(result_pdb, terminal_changes)
        detail = dict(options=options, segments=mapping, input_sha256=digest(source_pdb), selection=selection,
                      protonation=dict(method='manual topology and patches',
                                       automatic_ph_assignment=False,
                                       note='Target pH is recorded as context only. HIS and termini choices are applied; other residues retain their topology-defined states.'),
                      hydrogen_handling=dict(mode=hydrogens, removed_input_atoms=len(removed_hydrogens),
                                             removed_atoms=removed_hydrogens,
                                             note='Rebuilt coordinates follow the selected topology, protonation and termini; original input and protein selection are preserved.' if hydrogens == 'rebuild' else 'Input hydrogens retained; incompatible names can cause coordinate warnings.'),
                      terminal_oxygen_mappings=terminal_changes, terminal_coordinate_check=terminal_check,
                      topologies=[dict(name=f['name'], sha256=digest(f['text'])) for f in topology],
                      engine=json.loads((work / 'engine.json').read_text()), log=log)
        if executable:
            detail['script'] = (work / 'prepare.tcl').read_text()
        return preparation_result(result_pdb, psf, mode, parameters, pair, detail, topology, source_pdb=source_pdb, protein_pdb=pdb, segment_files=segment_files)


def preparation_result(pdb, psf, mode, parameters, pair, detail, topologies, source_pdb=None, protein_pdb=None, segment_files=None):
    preparation_id = str(uuid4())
    root = output_root()
    destination = root / preparation_id
    storage = dict(id=preparation_id, directory=str(destination),
                   pdb=str(destination / 'prepared.pdb'), psf=str(destination / 'prepared.psf'),
                   manifest=str(destination / 'manifest.json'), bundle=str(destination / 'preparation.zip'),
                   download_urls={name: f'/api/preparations/{preparation_id}/files/{name}'
                                  for name in ('prepared.pdb', 'prepared.psf', 'manifest.json', 'preparation.zip')})
    if protein_pdb is not None:
        storage['download_urls']['protein.pdb'] = f'/api/preparations/{preparation_id}/files/protein.pdb'
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
    if protein_pdb is not None:
        files['protein.pdb'] = protein_pdb
    for name, text in (segment_files or {}).items():
        files[f'segments/{name}'] = text
    if detail:
        files['psfgen.log'] = detail['log']
        if 'script' in detail:
            files['prepare.tcl'] = detail['script']
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
