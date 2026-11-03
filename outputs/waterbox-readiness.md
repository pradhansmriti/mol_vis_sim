# Periodic water and OpenMM execution readiness

Local validation: 2026-11-02, OpenMM 8.6.1 and official standalone psfgen 2.0 (NAMD 3.0.3). Protein inputs use CHARMM36 `top_all36_prot.rtf` and CHARMM36m `par_all36m_prot.prm`. Explicit water additionally requires the user's local `toppar_water_ions.str`. These force-field files remain outside Git; other compatible inputs can be selected and checked.

## Implemented choices

- Environment selection remains deferred until after protein preparation and structure review.
- Implicit OBC2/GBn2 default to **0.2 M ionic screening**. This adds no discrete ions. The selected value is recorded in the manifest and plan. These are OpenMM generalized Born models, not the identical NAMD GBIS implementation.
- Explicit CHARMM TIP3 water builds a cubic periodic box with default padding 1.0 nm. Both **neutralization and ionic-strength ion addition are disabled**: no Na+, Cl-, or counterions are created. Explicit salt must be 0 M; attempts to request ions or neutralization are rejected.
- Explicit dynamics use PME with a 1.2 nm nonbonded cutoff, switching from 1.0 nm, HBonds constraints and rigid water. The exact box vectors are recorded and applied to the OpenMM System. Small boxes incompatible with the cutoff are rejected.

Water packing uses OpenMM Modeller with the supplied PSF-derived System's charges/LJ radii. There is no silent switch to an XML protein force field. The CHARMM stream topology is parsed as data, then psfgen reads the original PSF/coordinates and adds TIP3 water segments without guessing protein coordinates. All original solute identities, atom types, charges, masses, bonds, angles, dihedrals, impropers and CMAP terms are checked for preservation. Water is required to have exactly OH2/H1/H2 atoms and zero net charge. The output PDB carries CRYST1; the manifest preserves full-precision box vectors.

## Measured results

Both proteins passed System creation, finite energy/force checks, bounded minimization and **100 NVT integration steps at 2 fs (0.2 ps)**, at 300 K with LangevinMiddle friction 1/ps and seed 2026. CPU platform, one thread.

| Environment | Ubiquitin 1UBQ | Villin 1VII |
|---|---:|---:|
| Implicit OBC2, 0.2 M screening | Passed | Passed |
| Explicit TIP3 water + PME | Passed | Passed |
| Water molecules | 5605 | 2816 |
| Total explicit particles | 18046 | 9044 |
| Cubic box side (nm) | 5.677540 | 4.529974 |
| Added ions | 0 | 0 |
| Solute net charge (e) | approximately 0 | +2 |
| Solute topology/coordinate preservation during solvation | Passed | Passed |

The first ubiquitin explicit readiness attempt used a 100-iteration minimization argument and exceeded the 240-second worker timeout. A separate timing check isolated the cost of minimization. The default argument is now **20 iterations per optimizer pass**, followed by the same 100 dynamics steps; constraint enforcement can cause additional passes, as documented in [the live measurements report](live-measurements.md). Ubiquitin passed this test in about 158 seconds. Villin's reported explicit result used the earlier 100-iteration argument and also passed. Implicit results likewise used that earlier argument. No minimizer convergence or equilibration claim is made. Timeouts now return `incomplete` and record the last reached stage rather than claiming a compatibility failure or success.

Local evidence: `work/waterbox-readiness.json` and its referenced immutable `runs/environments/<id>/` directories. The earlier timeout is retained in the evidence JSON. The live API was also tested for actual villin water-box building and a direct PDB download.

## Are the inputs sufficient to run?

**Yes for an NVT execution test**, once the selected System successfully loads: the PSF/PDB, matching protein/water parameters, solvent model, periodic box and PME settings (explicit), screening concentration (implicit), constraints, temperature, timestep, friction, seed, and requested duration specify the run. The successful short dynamics tests demonstrate actual initialization and integration, not just compatible labels. Pressure is not required for NVT; an NPT workflow would additionally need pressure/barostat settings and validation.

This is not production readiness. Longer relaxation and equilibration, structural/protonation review, output/reporting intervals, and production-run controls still need to be connected and reviewed. Villin remains charged (+2 e) because no counterions are added; review that periodic electrostatic choice before production. The interface retains `simulation_ready=false` and `execution_available=false` for full production, while exposing a separately labeled bounded readiness test.

## Storage and limits

Successful checks save a new `runs/environments/<id>/` directory. It includes the original prepared pair, explicit solvated PSF/PDB when applicable, `system.xml`, `manifest.json`, and `environment.zip`. Readiness tests additionally save `readiness.pdb` and `state.xml`. The interface provides direct download links. Original preparation files and archives are never overwritten. All generated files and user force-field inputs remain excluded from Git.

Workers are limited to 240 seconds; solute input is limited to 20000 atoms, and water packing has a conservative 45000-atom estimate/output limit. Larger systems should be prepared and validated offline. Integration tests exercise actual water packing, solute preservation, zero-ion enforcement, PDB/PSF correspondence including four-character TIP3 names, bounded dynamics, parameter failures and download access controls.

All **51 regression tests pass**. A separate real-villin water-box check also passed through the legacy standalone Python psfgen adapter, preserving solute terms and adding zero ions; this fallback still needs no VMD installation. The README preview was refreshed to show the periodic-water controls and bounded readiness test.

References: [OpenMM Modeller solvent construction](https://docs.openmm.org/latest/api-python/generated/openmm.app.modeller.Modeller.html), [CHARMM PSF System API](https://docs.openmm.org/latest/api-python/generated/openmm.app.charmmpsffile.CharmmPsfFile.html), and [official psfgen read/merge guide](https://www.ks.uiuc.edu/Research/vmd/plugins/psfgen/ug.pdf).
