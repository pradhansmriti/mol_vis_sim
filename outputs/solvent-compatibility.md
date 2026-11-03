# Solvent and protonation options

Local checks on 2026-11-02 use OpenMM 8.6.1 and the rebuilt ubiquitin/villin pairs documented in [the minimization report](openmm-validation.md). Inputs were local CHARMM36 `top_all36_prot.rtf` and CHARMM36m `par_all36m_prot.prm`.

| Selected environment | Ubiquitin 1UBQ | Villin 1VII |
|---|---|---|
| Vacuum, 0 M | System and finite energy/forces passed | System and finite energy/forces passed |
| OBC2, 0.15 M implicit screening | Passed | Passed |
| GBn2, 0.15 M implicit screening | Passed | Passed |
| Explicit CHARMM-modified TIP3P | Requires water/ion and periodic-box preparation | Requires water/ion and periodic-box preparation |

All checked systems used NoCutoff and HBonds constraints, CPU with one thread. This compatibility check only creates a System and evaluates the prepared coordinates; it does not minimize, equilibrate, run dynamics, or prove the scientific suitability of a solvent/force-field combination. Implicit salt is a screening term and introduces no explicit ions. The local evidence report is `work/solvent-compatibility.json`, including PSF/PDB hashes, parameter/topology hashes and exact settings.

The table above records the earlier compatibility-only checks. Periodic water building and execution tests have since been added; see [the current water-box/readiness report](waterbox-readiness.md).

## What the interface does

- Generation records HIS state, termini patches and hydrogen handling. The target-pH field has been removed; no pKa calculation is performed. HSE is neutral epsilon-protonated histidine, HSD is neutral delta-protonated, and HSP is doubly protonated (+1). Only residues named HIS use this global choice; already named variants are retained. Nonstandard/site-specific chemistry needs external preparation.
- Solvation and salt default to Decide later, in a collapsed later-stage section after structure review. No solvent method, salt or box is assigned to a deferred plan. When ready, the solvent selector offers vacuum, OBC2, GBn2, and CHARMM-modified TIP3P. Implicit screening defaults to 0.2 M; explicit water and vacuum use 0 M with no added ions. Water-box padding is shown for explicit solvent.
- The compatibility button sends the actual current PSF/PDB and uploaded force-field files to a worker with a 240-second timeout and 20000-atom solute input limit. Missing files report `needs_input`; missing OpenMM reports `unavailable`; loading/energy failures report `failed`. Successful implicit/vacuum checks report `compatible`, while `simulation_ready` stays false.
- Explicit solvent requires the local CHARMM TIP3 stream file, builds a cubic periodic box, merges water using psfgen while checking all original solute attributes and terms, then creates a PME System. Neutralization and ion addition are disabled. Outputs are separate from the original preparation. The optional readiness button minimizes and advances 100 NVT steps; production execution remains unavailable.
- Plans record solvent, salt, explicit padding, prepared protonation choices, the fresh compatibility result and file hashes. Setting changes invalidate the displayed result. Production execution remains disabled; the separate bounded readiness test is explicitly labeled.

The implementation follows the official [OpenMM CHARMM System API](https://docs.openmm.org/latest/api-python/generated/openmm.app.charmmpsffile.CharmmPsfFile.html) and [force-field and water-model guidance](https://docs.openmm.org/latest/userguide/application/02_running_sims.html). The installed 8.6.1 implementation explicitly supports GBn2 for CHARMM PSF loading; both real-protein checks above exercise it.

Initial validation: all 45 regression tests passed, including actual worker checks for all three implemented environments, missing parameter failures, explicit-solvent blocking, invalid settings, manual protonation records, and API origin checks. Browser verification covered protein preparation with uploaded topology/parameters, implicit compatibility success, explicit preparation requirements, fresh checks during workflow proposal, and enabled plan export. Numeric field wheel changes are prevented so scrolling cannot silently change a previously checked setting; both input and change events invalidate results.
