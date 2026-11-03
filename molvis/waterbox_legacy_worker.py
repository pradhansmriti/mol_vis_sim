"""Optional Python psfgen adapter for adding water to an existing PSF."""
import ctypes
import json
from pathlib import Path
import sys

if __name__ == '__main__':
    from psfgen import PsfGen
    work=Path(sys.argv[1]); config=json.loads((work/'water-config.json').read_text())
    gen=PsfGen()
    gen.read_psf(str(work/'prepared.psf'),pdbfile=str(work/'prepared.pdb'))
    gen.read_topology(str(work/'water.rtf'))
    for segment in config['segments']:
        filename=str(work/segment['pdb'])
        gen.add_segment(segid=segment['segid'],pdbfile=filename,first='NONE',last='NONE')
        gen.read_coords(filename,segid=segment['segid'])
    gen.write_psf(str(work/'solvated.psf'),type='x-plor')
    gen.write_pdb(str(work/'solvated-raw.pdb'))
    ctypes.CDLL(None).fflush(None)
