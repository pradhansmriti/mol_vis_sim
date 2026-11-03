"""Add CHARMM TIP3 water while preserving the supplied solute PSF and coordinates."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from .standalone_psfgen import executable_path, safe_token, write_engine_record
from .validation import load_pair, parse_psf


def water_topology(text):
    """Extract data from a CHARMM stream; never execute its command preamble."""
    lines = text.splitlines()
    start = next((i+1 for i,line in enumerate(lines) if re.match(r'^\s*read\s+rtf\b',line,re.I)), 0)
    end = next((i+1 for i in range(start,len(lines)) if lines[i].split('!')[0].strip().upper()=='END'), None)
    if end is None:
        raise ValueError('Water file has no terminated topology section.')
    topology = '\n'.join(lines[start:end])+'\n'
    if not re.search(r'(?im)^\s*RESI\s+TIP3\s',topology):
        raise ValueError('Water topology must define CHARMM TIP3.')
    return topology


def generate_water_psf(work, segments):
    config = dict(segments=segments)
    executable = os.environ.get('MOLVIS_PSFGEN')
    if executable:
        executable = executable_path(executable)
        lines = ['package require psfgen 2.0','readpsf prepared.psf pdb prepared.pdb','topology water.rtf']
        for segment in segments:
            name, filename = safe_token(segment['segid']), safe_token(segment['pdb'])
            lines += [f'segment {name} {{ first NONE; last NONE; pdb {{{filename}}} }}',f'coordpdb {{{filename}}} {name}']
        lines += ['writepsf solvated.psf','writepdb solvated-raw.pdb',
                  'set f [open engine-version.txt w]','puts $f [package require psfgen]','close $f']
        script = 'if {[catch {\n'+'\n'.join(lines)+'\n} message]} {puts stderr "MOLVIS_PSFGEN_ERROR: $message"; exit 1}\nexit 0\n'
        (work/'water-prepare.tcl').write_text(script)
        command = [str(executable),'water-prepare.tcl']
    else:
        (work/'water-config.json').write_text(json.dumps(config))
        local = Path(__file__).resolve().parent.parent/'.prep-env'/'bin'/'python'
        python = os.environ.get('MOLVIS_PREP_PYTHON', str(local) if local.is_file() else sys.executable)
        command = [python,str(Path(__file__).with_name('waterbox_legacy_worker.py')),str(work)]
    with (work/'psfgen-water.log').open('w') as log:
        process = subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    log = (work/'psfgen-water.log').read_text(errors='replace')
    if process.returncode or re.search(r'(?im)^\s*(?:psfgen\)\s*)?(?:ERROR\b|FATAL\b|MOLVIS_PSFGEN_ERROR:)',log):
        raise ValueError('Water PSF generation failed: '+log[-4000:])
    if executable:
        write_engine_record(work,executable)
        return json.loads((work/'engine.json').read_text())
    return dict(name='standalone Python psfgen', log='psfgen-water.log')


def build_waterbox(work, psf, pdb, params, settings):
    from openmm import app, unit
    before_atoms,before_xyz,before_terms = load_pair(work)
    if any(key[2] in ('TIP3','HOH','WAT','SOD','CLA','NA','CL') for key in before_atoms):
        raise ValueError('Water-box building expects a solute-only PSF/PDB; existing water/ions are not removed automatically.')
    if any(not key[0] for key in before_atoms):
        raise ValueError('Assign segment IDs before building an explicit water box.')
    config = json.loads((work/'config.json').read_text())
    if len(config['water']) != 1:
        raise ValueError('Supply one CHARMM water stream file containing TIP3 topology and parameters.')
    (work/'water.rtf').write_text(water_topology((work/config['water'][0]).read_text()))
    solute_system = psf.createSystem(params,nonbondedMethod=app.NoCutoff,constraints=app.HBonds)

    class SoluteParameters:
        # Modeller only needs the existing solute System for charges/LJ radii.
        # Both ionicStrength=0 and neutralize=False make its ion path a no-op.
        def createSystem(self, topology, **kwargs):
            if topology.getNumAtoms() != solute_system.getNumParticles():
                raise ValueError('Unexpected solute change during water packing.')
            return solute_system

    positions = pdb.positions.value_in_unit(unit.nanometer)
    center = [(min(p[k] for p in positions)+max(p[k] for p in positions))/2 for k in range(3)]
    radius = max(math.dist(p,center) for p in positions)
    width = max(2*radius+settings['padding_nm'],2*settings['padding_nm'])
    if width <= 2*settings['nonbonded_cutoff_nm']:
        raise ValueError('Box is too small for the 1.2 nm PME cutoff. Increase water-box padding.')
    if width**3*100+len(before_atoms) > 45000:
        raise ValueError('Requested box exceeds the interactive 45000-atom estimate. Reduce padding or prepare it offline.')
    modeller = app.Modeller(psf.topology,pdb.positions)
    modeller.addSolvent(SoluteParameters(), model='tip3p', padding=settings['padding_nm']*unit.nanometer,
                        boxShape='cube', ionicStrength=0*unit.molar, neutralize=False)
    waters = list(modeller.topology.residues())[len(list(psf.topology.residues())):]
    if not waters or modeller.topology.getNumAtoms() > 45000:
        raise ValueError('No waters were packed or the box exceeds the 45000-atom interactive limit.')
    if not all(r.name=='HOH' and sorted(a.element.symbol for a in r.atoms())==['H','H','O'] for r in waters):
        raise ValueError('Solvation added components other than three-site water.')
    xyz = modeller.positions.value_in_unit(unit.angstrom)
    if any(math.dist(before,after)>1e-8 for before,after in zip(pdb.positions.value_in_unit(unit.angstrom),xyz[:len(before_atoms)])):
        raise ValueError('Water packing changed the supplied solute coordinates.')
    occupied = {key[0] for key in before_atoms}; segments=[]
    for offset in range(0,len(waters),9999):
        index = 0
        while f'W{index:03d}' in occupied: index+=1
        if index>999: raise ValueError('No available water segment IDs.')
        segid=f'W{index:03d}'; occupied.add(segid); filename=f'water-{index}.pdb'; records=[]
        for resid,residue in enumerate(waters[offset:offset+9999],1):
            hindex=0
            for atom in residue.atoms():
                if atom.element.symbol=='O': name='OH2'
                else: hindex+=1; name=f'H{hindex}'
                x,y,z=xyz[atom.index]
                records.append(f'ATOM  {len(records)+1:5d} {name:^4} TIP3W{resid:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00      {segid:<4}\n')
        (work/filename).write_text(''.join(records)+'END\n')
        segments.append(dict(segid=segid,pdb=filename))
    engine = generate_water_psf(work,segments)
    vectors = modeller.topology.getPeriodicBoxVectors().value_in_unit(unit.nanometer)
    box_vectors = [[float(v) for v in vector] for vector in vectors]
    length = box_vectors[0][0]*10
    header=f'CRYST1{length:9.3f}{length:9.3f}{length:9.3f}{90.:7.2f}{90.:7.2f}{90.:7.2f} P 1           1\n'
    (work/'solvated.pdb').write_text(header+(work/'solvated-raw.pdb').read_text())
    from .preparation import validate_pair
    validate_pair((work/'solvated.pdb').read_text(),(work/'solvated.psf').read_text())
    # Verify every solute attribute and topology term survived PSF merging.
    after_atoms,_,after_terms = load_solvated_pair(work)
    new_atoms={key:atom for key,atom in after_atoms.items() if key not in before_atoms}
    if len(new_atoms)!=3*len(waters) or any(key[2]!='TIP3' or key[3] not in ('OH2','H1','H2') for key in new_atoms):
        raise ValueError('Water topology must add exactly OH2/H1/H2 atoms for each TIP3 molecule.')
    if abs(sum(atom['charge'] for atom in new_atoms.values()))>1e-6:
        raise ValueError('Added water must be electrically neutral; no ions or charge changes are permitted.')
    if any(after_atoms.get(key)!=value for key,value in before_atoms.items()):
        raise ValueError('Solvation changed solute atom identities/types/charges/masses.')
    from collections import Counter
    for name, terms in before_terms.items():
        retained=Counter({term:count for term,count in after_terms[name].items() if all(key in before_atoms for key in term)})
        if retained!=terms: raise ValueError(f'Solvation changed solute {name} topology terms.')
    from .planning import inspect_pdb
    after_xyz={(a['segment_id'],a['residue_id'],a['residue'],a['name']):a['xyz'] for a in inspect_pdb((work/'solvated.pdb').read_text())['atoms']}
    if any(math.dist(value,after_xyz[key])>0.00051 for key,value in before_xyz.items()):
        raise ValueError('Solvation changed a solute coordinate.')
    report=dict(water_molecules=len(waters), added_ions=0, neutralize=False, ionic_strength_molar=0,
                box_shape='cube', box_vectors_nm=box_vectors, solute_atoms=len(before_atoms),
                solute_preserved=True, psfgen_engine=engine)
    (work/'box.json').write_text(json.dumps(report,indent=2))
    solvated=app.CharmmPsfFile(str(work/'solvated.psf'))
    solvated.setBox(*(vector[k]*unit.nanometer for k,vector in enumerate(box_vectors)))
    system=solvated.createSystem(params,nonbondedMethod=app.PME,nonbondedCutoff=1.2*unit.nanometer,
                                 switchDistance=1.0*unit.nanometer,constraints=app.HBonds,rigidWater=True)
    return system,app.PDBFile(str(work/'solvated.pdb')).positions,report


def load_solvated_pair(work):
    from .planning import inspect_pdb
    atoms,indices,terms=parse_psf((work/'solvated.psf').read_text())
    coordinates={indices[i]:a['xyz'] for i,a in enumerate(inspect_pdb((work/'solvated.pdb').read_text())['atoms'],1)}
    return atoms,coordinates,terms
