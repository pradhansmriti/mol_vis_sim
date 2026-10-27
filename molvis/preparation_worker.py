"""Isolate the native standalone psfgen library from the HTTP server process."""
import importlib.metadata
import ctypes
import json
from pathlib import Path
import sys


def main(directory):
    try:
        from psfgen import PsfGen
    except ImportError as exc:
        raise RuntimeError('Install the server preparation environment: conda env create -f environment.yml. VMD is not required.') from exc
    work = Path(directory)
    config = json.loads((work / 'config.json').read_text())
    with (work / 'engine-output.log').open('w') as output:
        gen = PsfGen(output=output)
        for name in config['topologies']:
            gen.read_topology(str(work / name))
        gen.alias_residue(top_resname=config['options']['histidine'], pdb_resname='HIS')
        gen.alias_atom(resname='ILE', top_atomname='CD', pdb_atomname='CD1')
        for segment in config['segments']:
            filename = str(work / segment['pdb'])
            gen.add_segment(segid=segment['segid'], pdbfile=filename,
                            first=config['options']['first'], last=config['options']['last'])
            gen.read_coords(filename=filename, segid=segment['segid'])
        gen.guess_coords()
        gen.write_psf(filename=str(work / 'prepared.psf'), type='x-plor')
        gen.write_pdb(filename=str(work / 'prepared.pdb'))
        # Flush C stdio used by the extension before the file descriptor closes.
        ctypes.CDLL(None).fflush(None)
    try:
        version = importlib.metadata.version('psfgen')
    except importlib.metadata.PackageNotFoundError:
        version = 'unknown'
    (work / 'engine.json').write_text(json.dumps(dict(name='standalone Python psfgen', version=version)))


if __name__ == '__main__':
    main(sys.argv[1])
