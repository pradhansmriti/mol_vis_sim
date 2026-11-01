"""Controlled Tcl adapter for an official standalone psfgen 2.x executable."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


def executable_path(value):
    located = shutil.which(value)
    path = Path(located or value).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Configured psfgen executable was not found or is not executable.')
    return path


def safe_token(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', value) or value.startswith('.'):
        raise ValueError('Invalid internal psfgen script token.')
    return value


def write_script(work, config):
    options = config['options']
    if options['histidine'] not in ('HSE', 'HSD', 'HSP') or options['first'] not in ('NTER', 'NONE') or options['last'] not in ('CTER', 'NONE'):
        raise ValueError('Unsupported psfgen preparation settings.')
    lines = ['package require psfgen 2.0']
    lines += [f'topology {{{safe_token(name)}}}' for name in config['topologies']]
    lines += [f'pdbalias residue HIS {options["histidine"]}', 'pdbalias atom ILE CD1 CD']
    for segment in config['segments']:
        segid, filename = safe_token(segment['segid']), safe_token(segment['pdb'])
        lines += [f'segment {segid} {{', f'  first {options["first"]}',
                  f'  last {options["last"]}', f'  pdb {{{filename}}}', '}',
                  f'coordpdb {{{filename}}} {segid}']
    lines += ['guesscoord', 'writepsf prepared.psf', 'writepdb prepared.pdb',
              'set versionfile [open engine-version.txt w]',
              'puts $versionfile [package require psfgen]', 'close $versionfile']
    script = 'if {[catch {\n'+ '\n'.join(lines) + '\n} message]} {\n  puts stderr "MOLVIS_PSFGEN_ERROR: $message"\n  exit 1\n}\nexit 0\n'
    (work / 'prepare.tcl').write_text(script, encoding='utf-8')


def write_engine_record(work, executable):
    try:
        version = (work / 'engine-version.txt').read_text().strip()
    except OSError as exc:
        raise ValueError('psfgen did not report its version; preparation was not accepted.') from exc
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version) or int(version.split('.')[0]) < 2:
        raise ValueError('The standalone backend requires psfgen 2.0 or newer.')
    record = dict(name='standalone psfgen executable', version=version,
                  executable=str(executable), executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
    (work / 'engine.json').write_text(json.dumps(record), encoding='utf-8')
