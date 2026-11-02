# Two-protein preparation validation

Local run: 2026-11-02. Engine: official standalone psfgen 2.0 distributed with NAMD 3.0.3. Topology: locally supplied CHARMM36 `top_all36_prot.rtf`. Settings: protein selection, HIS→HSE, NTER/CTER, terminal O/OXT→OT1/OT2 mapping, coordinate guessing enabled.

Inputs: ubiquitin [1UBQ](https://www.rcsb.org/structure/1UBQ) and the small villin headpiece [1VII](https://www.rcsb.org/structure/1VII). Villin's supplied structure includes hydrogens, making it a useful naming compatibility test.

| Check | Ubiquitin 1UBQ | Villin 1VII | Villin without input hydrogens (control) |
|---|---:|---:|---:|
| Residues | 76 | 36 | 36 |
| Prepared atoms | 1231 | 596 | 596 |
| Net charge (e) | approximately 0 | +2 | +2 |
| Missing input heavy atoms | 0 | 0 | 0 |
| Maximum input heavy-atom displacement (Å) | 0 | 0 | 0 |
| Broad bond-length outliers | 0 | 0 | 0 |
| psfgen warning/error lines | 0 | Hydrogen naming and guessing warnings | 0 |
| Actual VMD comparison | Passed | Passed | Passed |
| Maximum coordinate difference from VMD (Å) | 0 | 0 | 0 |

Villin with its original hydrogens reports unmapped names such as H/H1/H2/H3 and HB3, failed angle-based guesses, and 52 poorly guessed hydrogen coordinates (zero non-hydrogen atoms). Removing input hydrogens in a separate control eliminates these diagnostics. This supports a deliberate hydrogen rebuilding option as the next preparation improvement. The platform's default hydrogen handling has not been changed by these tests.

All three outputs have valid PSF/PDB atom correspondence and parseable bond, angle, proper dihedral, improper, and CMAP sections. Ubiquitin has 1237 bonds, 2257 angles, 3293 proper dihedrals, 212 impropers, and 74 CMAP terms; villin has 602, 1091, 1588, 94, and 34 respectively. Bond screening uses broad ranges (0.7–1.4 Å for hydrogen-containing bonds, 1.1–2.3 Å for other bonds); it is not parameter-based geometry validation and does not check clashes or stereochemistry.

## VMD reference comparison

After VMD became available, all three cases were compared with actual VMD-generated reference pairs. The downloaded bundle is `vmd2.0.0a7-pre2-macarm`; its runtime reports **VMD 2.0.0a7; psfgen 2.0**. It was run in text mode from the mounted disk image with `VMDDIR` pointing to the bundle's `Contents/vmd2/lib` directory. Reference Tcl scripts use VMD's own `protein` selection and the same topology, aliases, terminal mapping, and patches.

All atom identities, types, charges, masses, bonds, angles, proper dihedrals, impropers, and CMAP terms match. Every coordinate agrees at the written PDB precision (maximum difference and heavy-atom RMSD both 0 Å) for both original proteins and the hydrogen-free villin control. Villin's original-hydrogen case produces the identical sequence of 200 psfgen diagnostic lines in VMD, including the 52 poorly guessed hydrogens. This behavior is reproducible in VMD's bundled core and is not specific to our standalone integration. The hydrogen-free control matches VMD without psfgen warnings.

The comparator matches atoms by segment/residue/name instead of file byte order, checks atom types, charges and masses, and compares bonded terms with multiplicity. Coordinates must agree within 0.002 Å; heavy-atom RMSD is also reported without structural alignment. Bond, angle, and proper dihedral reversals are treated as equivalent; improper and CMAP ordering is retained. A failed comparison exits nonzero. Matching files would still not establish complete force-field coverage or simulation readiness.

## Local evidence and remaining checks

- Main report: `work/preparation-validation/report.json` (source and topology SHA256 hashes, engine provenance, diagnostics, output paths).
- Hydrogen control: `work/preparation-validation/hydrogen-control/report.json`.
- Ubiquitin outputs: `runs/preparations/8400e2d4-6f71-4671-8d6f-121b074b0842/`.
- Villin outputs: `runs/preparations/5178c1f6-8138-479a-b1f7-b2481a36a730/`.
- Hydrogen-free villin outputs: `runs/preparations/981fef7c-47ef-4c43-a41b-beebb1742f24/`.
- VMD scripts: `work/preparation-validation/{1UBQ,1VII}/vmd-reference/reference.tcl`.

OpenMM parameter loading, energy evaluation, and minimization have not been run. OpenMM is not installed in the current interpreter. Do not label these preparations simulation-ready yet. The regression suite passes 34 tests with the official standalone backend, including comparator tests for atom reordering, coordinate/charge/connectivity changes, and malformed topology indices.
