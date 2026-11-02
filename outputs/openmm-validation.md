# Hydrogen rebuilding and OpenMM checks

Tested locally on 2026-11-02 with official standalone psfgen 2.0 (NAMD 3.0.3), VMD 2.0.0a7 / psfgen 2.0, and OpenMM 8.6.1. The protein topology is CHARMM36 `top_all36_prot.rtf`; the parameter file is CHARMM36m `par_all36m_prot.prm`. Neither file is bundled with the repository. Other compatible force-field inputs can be supplied explicitly.

## Preparation option

The interface now offers retaining or rebuilding input hydrogens. Retaining remains the default for compatibility. Rebuilding excludes H/D/T atoms from the engine inputs, preserving original source and protein-selection files and all heavy-atom coordinates. It records the removed atoms and selected mode in the preparation manifest. Uploaded existing pairs are unchanged.

Both original proteins were prepared again through the new `hydrogens=rebuild` option and compared to VMD using its independent `protein and not hydrogen` selection:

| Check | Ubiquitin 1UBQ | Villin 1VII |
|---|---:|---:|
| Removed input hydrogens | 0 | 301 |
| Prepared atoms | 1231 | 596 |
| psfgen diagnostic lines | 0 | 0 |
| Heavy-atom displacement before minimization (Å) | 0 | 0 |
| VMD topology/attribute comparison | Passed | Passed |
| Maximum coordinate difference from VMD (Å) | 0 | 0 |

Evidence: `work/preparation-next/report.json`, with reference scripts and VMD logs in each case's `vmd-reference/` directory. Output preparation IDs are `3b49d2a2-44b4-46da-87c2-4201ea17a536` (ubiquitin) and `d4318a81-06f9-4ae2-be56-5bb831c9284e` (villin).

## OpenMM result

The separate diagnostic follows the official [OpenMM CHARMM loading workflow](https://docs.openmm.org/latest/userguide/application/02_running_sims.html). It loaded those rebuilt PSF/PDB pairs with the local topology and parameters, including CMAP. Both Systems were created successfully with no missing parameter errors.

Settings: CPU platform with one thread; isolated protein in vacuum; NoCutoff; no constraints, restraints, solvent, periodic box or dynamics. Minimization was bounded at 200 iterations with a requested force tolerance of 10 kJ/mol/nm. The integrator is not stepped.

| Metric | Ubiquitin 1UBQ | Villin 1VII |
|---|---:|---:|
| Initial potential energy (kJ/mol) | −764.657 | 4496.156 |
| Final potential energy (kJ/mol) | −7687.639 | −1886.207 |
| Initial force RMS per Cartesian component (kJ/mol/nm) | 3539.418 | 1044.009 |
| Final force RMS per Cartesian component (kJ/mol/nm) | 15.690 | 37.998 |
| Final maximum atom force (kJ/mol/nm) | 232.199 | 386.547 |
| Heavy-atom RMS displacement from prepared input (Å) | 0.805 | 1.359 |

Energies and forces are finite and energies decreased. These are diagnostic vacuum results, not comparable solution free energies. Minimizer convergence is not asserted; residual forces remain. Coordinates move during minimization by design, and original preparation files remain unchanged. No dynamics, equilibration, clash/stereochemistry review, or solvent simulation is claimed. `simulation_ready` stays false.

Outputs are saved separately in `work/openmm-validation/1UBQ/` and `work/openmm-validation/1VII/`: reports with file hashes and settings, `minimized.pdb`, matching `prepared.psf`, and serialized System/State XML. Nothing overwrites the preparation archive or its downloadable files.

## Remaining work

1. Review prepared geometry, protonation, terminal patches, and any special chemistry for the actual target protein.
2. Add a reviewed choice of solvent model, water box, ions, and periodic boundary settings with compatible CHARMM parameters.
3. Run restrained relaxation/minimization and staged equilibration in that intended environment, then inspect stability before production dynamics.
4. Connect validated execution to the interface with explicit settings, status, output downloads, and energy/temperature traces.

Regression coverage includes hydrogen filtering, preservation of original files and heavy atoms, actual psfgen rebuilding, actual OpenMM parameter loading/minimization on a small synthetic test system, refusal to overwrite results, and failure reporting for missing force-field terms.
