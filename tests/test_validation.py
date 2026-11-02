from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from molvis.validation import compare_pairs, parse_psf
from test_preparation import PDB, PSF


def fixture(order=(1,2,3,4)):
    # Locate atom records rather than depend on whitespace in the fixture header.
    lines=PSF.splitlines();start=next(i for i,l in enumerate(lines) if '!NATOM' in l)
    atom_lines=lines[start+1:start+5]
    mapping={old:new for new,old in enumerate(order,1)}
    records=[]
    for new,old in enumerate(order,1):
        fields=atom_lines[old-1].split();fields[0]=str(new);records.append(' '.join(fields))
    sections={'NBOND':[(1,2),(2,3),(3,4)],'NTHETA':[(1,2,3),(2,3,4)],
              'NPHI':[(1,2,3,4)],'NIMPHI':[(1,3,2,4)],'NCRTERM':[]}
    psf='PSF CMAP\n\n4 !NATOM\n'+'\n'.join(records)+'\n'
    for name,terms in sections.items():
        psf+=f'\n{len(terms)} !{name}\n'
        psf+=' '.join(str(mapping[i]) for term in terms for i in term)+'\n'
    pdb_lines=PDB.splitlines()[:4]
    return '\n'.join(pdb_lines[i-1] for i in order)+'\nEND\n',psf


class ValidationTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def write_pair(self,name,pdb,psf):
        root=self.root/name;root.mkdir()
        (root/'prepared.pdb').write_text(pdb);(root/'prepared.psf').write_text(psf)
        return root

    def test_reordered_atoms_preserve_identity_based_topology_comparison(self):
        a=self.write_pair('a',*fixture());b=self.write_pair('b',*fixture((4,2,1,3)))
        self.assertTrue(compare_pairs(a,b)['passed'])

    def test_changed_charge_and_connectivity_fail(self):
        pdb,psf=fixture();a=self.write_pair('a',pdb,psf)
        charge=self.write_pair('charge',pdb,psf.replace('0.0 12.0','1.0 12.0',1))
        self.assertFalse(compare_pairs(a,charge)['atom_type_charge_mass_match'])
        bond=self.write_pair('bond',pdb,psf.replace('1 2 2 3 3 4','1 3 2 3 3 4'))
        self.assertFalse(compare_pairs(a,bond)['bonded_term_matches']['NBOND'])

    def test_coordinate_change_fails(self):
        pdb,psf=fixture();a=self.write_pair('a',pdb,psf)
        lines=pdb.splitlines();lines[0]=lines[0][:30]+f'{9.:8.3f}'+lines[0][38:]
        b=self.write_pair('b','\n'.join(lines),psf)
        self.assertFalse(compare_pairs(a,b)['passed'])

    def test_malformed_or_unknown_indices_are_rejected(self):
        _,psf=fixture()
        for invalid in (psf.replace('1 2 2 3 3 4','1 99 2 3 3 4'),psf.replace('3 !NBOND','4 !NBOND')):
            with self.assertRaises(ValueError):parse_psf(invalid)


if __name__=='__main__':unittest.main()
