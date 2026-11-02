"""Compare prepared molecular contents and export a matched VMD reference run."""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import subprocess

from .planning import inspect_pdb
from .preparation import prepare, validate_pair, digest

TERM_WIDTHS = {'NBOND':2, 'NTHETA':3, 'NPHI':4, 'NIMPHI':4, 'NCRTERM':8}


def parse_psf(text):
    lines = text.splitlines()
    headers = {}
    for i,line in enumerate(lines):
        match = re.match(r'^\s*(\d+)\s+!(NATOM|NBOND|NTHETA|NPHI|NIMPHI|NCRTERM)\b',line)
        if match:
            name = match[2]
            if name in headers:
                raise ValueError(f'Duplicate PSF section {name}.')
            headers[name] = (i,int(match[1]))
    if 'NATOM' not in headers:
        raise ValueError('PSF has no atom table.')
    start,count = headers['NATOM']
    atoms, indices = {}, {}
    for line in lines[start+1:start+count+1]:
        fields = line.split()
        if len(fields)<8:
            raise ValueError('Truncated PSF atom table.')
        index = int(fields[0]); key = tuple(fields[1:5])
        if index in indices or key in atoms:
            raise ValueError('Duplicate PSF atom identity or index.')
        charge,mass = float(fields[6]),float(fields[7])
        if not math.isfinite(charge) or not math.isfinite(mass) or mass<0:
            raise ValueError('Invalid PSF charge/mass.')
        atoms[key] = dict(type=fields[5],charge=charge,mass=mass)
        indices[index] = key
    if len(atoms)!=count or set(indices)!=set(range(1,count+1)):
        raise ValueError('Invalid PSF atom indices/count.')
    terms = {}
    for name,width in TERM_WIDTHS.items():
        if name not in headers:
            if name=='NCRTERM' and 'CMAP' not in lines[0].split():
                terms[name] = Counter(); continue
            raise ValueError(f'PSF is missing {name}.')
        start,count = headers[name]; values = []
        for row in lines[start+1:]:
            if '!' in row:
                break
            values.extend(int(value) for value in row.split())
        if len(values)!=count*width:
            raise ValueError(f'Incorrect number of indices in {name}.')
        tuples = []
        for i in range(0,len(values),width):
            try:
                item = tuple(indices[v] for v in values[i:i+width])
            except KeyError as exc:
                raise ValueError(f'Unknown atom index in {name}.') from exc
            if name in ('NBOND','NTHETA','NPHI'):
                item = min(item,item[::-1])
            tuples.append(item)
        terms[name] = Counter(tuples)
    return atoms,indices,terms


def load_pair(directory):
    root = Path(directory)
    pdb,psf = (root/'prepared.pdb').read_text(),(root/'prepared.psf').read_text()
    validate_pair(pdb,psf)
    atoms,indices,terms = parse_psf(psf)
    coordinates = {indices[i]:a['xyz'] for i,a in enumerate(inspect_pdb(pdb)['atoms'],1)}
    return atoms,coordinates,terms


def compare_pairs(application, reference, tolerance=0.002):
    a,ac,at = load_pair(application); b,bc,bt = load_pair(reference)
    identity_match = a.keys()==b.keys()
    attributes_match = identity_match and all(a[k]['type']==b[k]['type'] and
        abs(a[k]['charge']-b[k]['charge'])<=1e-6 and abs(a[k]['mass']-b[k]['mass'])<=1e-6 for k in a)
    distances = [math.dist(ac[k],bc[k]) for k in a if k in b]
    heavy = [math.dist(ac[k],bc[k]) for k in a if k in b and a[k]['mass']>3.5]
    term_matches = {name:at[name]==bt[name] for name in TERM_WIDTHS}
    coordinates_match = identity_match and bool(distances) and max(distances)<=tolerance
    return dict(passed=bool(attributes_match and coordinates_match and all(term_matches.values())),
                atom_identity_match=identity_match, atom_type_charge_mass_match=attributes_match,
                bonded_term_matches=term_matches,
                application_counts=dict(atoms=len(a),**{k:sum(v.values()) for k,v in at.items()}),
                reference_counts=dict(atoms=len(b),**{k:sum(v.values()) for k,v in bt.items()}),
                max_coordinate_difference_angstrom=max(distances,default=None),
                heavy_atom_rmsd_angstrom=math.sqrt(sum(d*d for d in heavy)/len(heavy)) if heavy else None,
                coordinate_tolerance_angstrom=tolerance)


def inspect_preparation(directory):
    root = Path(directory)
    atoms,coordinates,terms = load_pair(root)
    manifest = json.loads((root/'manifest.json').read_text())
    original = inspect_pdb((root/'protein.pdb').read_text())
    segment_lookup = {(s['chain'],s['input_segment']):s['output_segment'] for s in manifest['details']['segments']}
    aliases = {(m['segment'],m['residue_id'],m['source_name']):m['target_name'] for m in manifest['details']['terminal_oxygen_mappings']}
    missing,displacements = [],[]
    for atom in original['atoms']:
        if atom['name'].lstrip('0123456789').startswith(('H','D')):
            continue
        segid=segment_lookup[(atom['chain'],atom['segment_id'])]
        name=aliases.get((segid,atom['residue_id'],atom['name']),atom['name'])
        residue=manifest['details']['options']['histidine'] if atom['residue']=='HIS' else atom['residue']
        if residue=='ILE' and name=='CD1': name='CD'
        key=(segid,atom['residue_id'],residue,name)
        if key not in coordinates: missing.append(list(key))
        else: displacements.append(math.dist(atom['xyz'],coordinates[key]))
    lengths=[(math.dist(coordinates[a],coordinates[b]),a,b) for a,b in terms['NBOND']]
    warnings=[line for line in manifest['details']['log'].splitlines() if re.search(r'\b(?:Warning|ERROR|FATAL)\b',line,re.I)]
    # Broad geometry screening only; equilibrium bond lengths depend on parameters.
    unusual=[]
    for length,a,b in lengths:
        hydrogen=atoms[a]['mass']<3.5 or atoms[b]['mass']<3.5
        lo,hi=(0.7,1.4) if hydrogen else (1.1,2.3)
        if not lo<=length<=hi: unusual.append(dict(atoms=[a,b],length_angstrom=length))
    preserved=not missing and bool(displacements) and max(displacements)<=0.001
    return dict(atom_count=len(atoms), net_charge_e=sum(a['charge'] for a in atoms.values()),
                heavy_atom_coordinates_preserved=preserved, missing_input_heavy_atoms=missing,
                max_input_heavy_atom_displacement_angstrom=max(displacements,default=None),
                bonded_term_counts={k:sum(v.values()) for k,v in terms.items()},
                broad_bond_length_outliers=unusual, engine_diagnostics=warnings,
                simulation_ready=False, parameter_validation='not_run')


VMD_SCRIPT = '''# Run from this directory: vmd -dispdev text -e reference.tcl
# Reference uses VMD's own protein atom selection, independently of the app.
if {[catch {
package require psfgen 2.0
mol new source.pdb type pdb waitfor all
set molecule [molinfo top]
set protein [atomselect $molecule protein]
if {[$protein num] == 0} {error "No protein atoms selected"}
if {[llength [lsort -unique [$protein get chain]]] != 1} {error "Reference script currently supports one chain"}
set lastres [lindex [$protein get resid] end]
set oxygen [atomselect $molecule "protein and resid $lastres and name O"]
$oxygen set name OT1
set oxygen2 [atomselect $molecule "protein and resid $lastres and name OXT"]
$oxygen2 set name OT2
$protein writepdb segment.pdb
topology topology.rtf
pdbalias residue HIS HSE
pdbalias atom ILE CD1 CD
segment P000 {
 first NTER
 last CTER
 pdb segment.pdb
}
coordpdb segment.pdb P000
guesscoord
writepsf prepared.psf
writepdb prepared.pdb
set f [open reference-version.txt w]
puts $f "VMD [vmdinfo version]; psfgen [package require psfgen]"
close $f
} message]} {puts stderr $message; exit 1}
exit 0
'''


def run_cases(args):
    os.environ['MOLVIS_PSFGEN']=str(Path(args.psfgen).resolve())
    topology=Path(args.topology).read_text(); out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    report={}
    for item in args.case:
        name,filename=item.split('=',1)
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name): raise ValueError('Use a simple case name.')
        source=Path(filename).read_text()
        result=prepare(dict(mode='generate',pdb=source,topologies=[dict(name=Path(args.topology).name,text=topology)],
                            confirm_guess=True,options=dict(histidine='HSE',first='NTER',last='CTER',hydrogens=args.hydrogens)))
        case=out/name;case.mkdir(exist_ok=True)
        app=Path(result['storage']['directory'])
        ref=case/'vmd-reference';ref.mkdir(exist_ok=True)
        script = VMD_SCRIPT
        if args.hydrogens == 'rebuild':
            script = script.replace('set protein [atomselect $molecule protein]', 'set protein [atomselect $molecule "protein and not hydrogen"]')
        for filename,content in [('source.pdb',source),('topology.rtf',topology),('reference.tcl',script)]:
            (ref/filename).write_text(content)
        entry=dict(source_sha256=digest(source),topology_sha256=digest(topology),
                   application_directory=str(app),engine=result['manifest']['details']['engine'],
                   hydrogen_handling=result['manifest']['details']['hydrogen_handling'],
                   checks=inspect_preparation(app),vmd_comparison=dict(status='not_run',reason='VMD executable/reference not supplied'),
                   reference_directory=str(ref))
        if args.vmd:
            # Remove stale outputs so a failed reference run cannot look successful.
            for filename in ('prepared.pdb','prepared.psf','reference-version.txt'):
                (ref/filename).unlink(missing_ok=True)
            process=subprocess.run([str(Path(args.vmd).resolve()),'-dispdev','text','-e','reference.tcl'],cwd=ref,capture_output=True,text=True,timeout=120)
            (ref/'vmd.log').write_text(process.stdout+process.stderr)
            if process.returncode or not (ref/'reference-version.txt').is_file():
                entry['vmd_comparison']=dict(status='failed',reason='VMD reference generation did not complete; inspect vmd.log')
            else:
                comparison=compare_pairs(app,ref)
                entry['vmd_comparison']=dict(status='passed' if comparison['passed'] else 'failed',
                                             version=(ref/'reference-version.txt').read_text().strip(),**comparison)
        report[name]=entry
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(name, 'atoms=',entry['checks']['atom_count'],
              'heavy_atoms_preserved=',entry['checks']['heavy_atom_coordinates_preserved'],
              'diagnostics=',len(entry['checks']['engine_diagnostics']),
              'bond_outliers=',len(entry['checks']['broad_bond_length_outliers']),
              'VMD=',entry['vmd_comparison']['status'],flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--psfgen',required=True);run.add_argument('--topology',required=True)
    run.add_argument('--case',action='append',required=True,help='NAME=/path/to/input.pdb')
    run.add_argument('--output',default='work/preparation-validation');run.add_argument('--vmd')
    run.add_argument('--hydrogens', choices=['retain','rebuild'], default='retain')
    compare=sub.add_parser('compare');compare.add_argument('application');compare.add_argument('reference')
    args=parser.parse_args()
    if args.command=='run': run_cases(args)
    else:
        result=compare_pairs(args.application,args.reference)
        print(json.dumps(result,indent=2))
        if not result['passed']:raise SystemExit(1)


if __name__=='__main__': main()
