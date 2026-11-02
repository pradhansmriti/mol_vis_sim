# C-terminal oxygen naming correction — 2026-11-02

## Reason

PDB structures such as 1UBQ name the terminal carboxyl oxygens `O` and `OXT`.
The selected CHARMM `CTER` patch uses `OT1` and `OT2`. Without a terminal-specific
mapping, psfgen discarded their measured coordinates and guessed replacements.
In our earlier ubiquitin output both C–O distances became 1.000 Å instead of
the input distances of 1.247 and 1.239 Å. This was a coordinate-assignment problem,
separate from the AUTO/PATCH parser compatibility issue.

## Correction

- Before psfgen runs, map `O → OT1` and `OXT → OT2` only in the final residue of
  each segment whose selected last-residue patch is `CTER`.
- Change only the atom-name columns of the backend input. All coordinates and
  other PDB columns are retained. Internal carbonyl oxygen names are unchanged.
- With `NONE`, no terminal mapping is performed. Already named `OT1`/`OT2` atoms
  are retained. Conflicting old/new names in the same terminal residue are
  rejected for review instead of silently dropping atoms.
- After generation, verify that every renamed oxygen is present with the
  original coordinates, within 0.00051 Å per coordinate to allow PDB rounding.
  A missing or displaced mapped oxygen causes preparation to fail.
- Shared preprocessing supports both official standalone psfgen and the optional
  legacy Python backend. Uploaded PSF/PDB pairs are never renamed.

## Record and saved files

`manifest.json` records each mapping with its chain, segment, residue, original
and target atom names, and original coordinates. `terminal_coordinate_check`
records the mapped-atom count and maximum displacement.

The original upload remains in `source.pdb`, and `protein.pdb` retains the
protein-only selection with original atom names. Exact renamed inputs are saved
under `segments/segment-*.pdb` and included in the download ZIP. The activity log
summarizes the terminal mapping. Source files on the user's computer are not edited.

## Verification

Official psfgen 2.0 from NAMD 3.0.3 regenerated 1UBQ with the unmodified local
CHARMM36 topology and HSE/NTER/CTER choices. The pair has 1,231 atoms. Both GLY76
oxygen coordinates were preserved exactly (maximum displacement 0.0 Å); the
C–O distances remain 1.247 and 1.239 Å. The O/OXT assignment warnings disappeared.
psfgen reported 629 guessed coordinates, all hydrogen, and zero guessed heavy
atoms. Outputs are saved in preparation `cc098830-fcda-420a-8f03-b47019caf73d`.

The 30-test suite passes separately with both backends. Tests cover internal
oxygen preservation, NONE, already mapped names, ambiguous names, failure when
coordinates change, and real generation with a synthetic CTER topology.

This correction does not replace parameter validation, geometry checks, or
energy minimization. Preparation remains explicitly marked not simulation-ready.
