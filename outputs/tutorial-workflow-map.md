# Ubiquitin learning agent: workflow map v0.1

## Goal and provisional choices
Teach a person how MD works by reproducing each step of the NAMD ubiquitin tutorial in an inspectable workflow. Start with proteins and OpenMM; keep both configurable.

Working reference: NAMD Tutorial, Unix/MacOSX, April 2017:
https://www.ks.uiuc.edu/Training/Tutorials/namd/namd-tutorial-html/
This is the proposed baseline. Archive and checksum its input bundle before implementation; parameter-level equivalence has not yet been audited.

## Tutorial coverage
| Stage | Tutorial coverage | Agent deliverable | Learning checkpoint / validation |
|---|---|---|---|
| 0. Orientation | Programs, getting started, required files | Environment check and source manifest | Explain coordinates, connectivity, parameters, configuration, trajectory, and log |
| 1. Protein preparation | PSF generation | Inspected ubiquitin structure and topology | Explain hydrogens, residues, termini, and force-field assignment; check atom identities and parameter coverage |
| 2. Solvent preparation | Water sphere and water box | Separate prepared systems | Explain boundary conditions; inspect geometry, composition, and box definition |
| 3. Explicit-solvent runs | Nonperiodic sphere and periodic box | Separate executable protocols and run records | Explain minimization and equilibration; check numerical stability and expected run settings |
| 4. Implicit-solvent run | Generalized Born branch | Independently specified solvent model and run | Explain omitted explicit water and model assumptions; audit compatibility |
| 5. First analysis | Logs and two protein RMSD selections | Linked plots and selection definitions | Explain alignment and flexible-tail effects; verify atom correspondence |
| 6. Equilibrium analysis | Residue RMSD, energy and temperature distributions, specific heat | Reproducible analyses with units and assumptions | Explain sampling and estimator limits; avoid declaring convergence from one plot |
| 7. Nonequilibrium analysis | Heat diffusion and temperature/velocity echo exercises | Controlled perturbation protocols and comparisons | Explain initial states, interventions, and response; preserve restart details |
| 8. Steered MD | Water removal, constant-velocity and constant-force pulling | Explicit atom selections, pulling protocols, force/distance plots | Explain imposed forces and unfolding; verify units, direction, restraints, and selections |
| 9. Reproduction review | Supporting formats and complete exercise record | Coverage checklist and learner report | Distinguish executed, checked, translated, and unresolved steps |

## Interaction at each step
1. Explain the scientific purpose in plain language.
2. Show the tutorial source, inputs, and planned action.
3. Expose scientific settings with defaults and reasons.
4. Execute the action and preserve its exact settings.
5. Show outputs and checks with evidence.
6. Explain what the results support and where uncertainty remains.
7. Offer continuation, inspection, or revision from that point.

Run controls and teaching text should be separate from the simulation engine adapter. Show a short explanation by default, with expandable scientific and implementation details.

## Translation policy
Maintain one record per original tutorial step: source location, original settings, OpenMM action, differences, validation evidence, and status. Do not silently replace an unsupported method. Classify differences as equivalent representation, intentional protocol change, or unresolved mismatch. A runnable adaptation alone does not establish replication.

Compare systems, settings, and suitable physical/statistical observations rather than requiring identical trajectories. Define quantitative acceptance criteria only after auditing the actual tutorial protocol and analysis assumptions.

## Minimum step record
- Stable step ID and source section
- Dependencies and input file hashes
- Scientific settings and units
- Engine, package versions, execution platform, and random seeds
- Executable action and generated artifacts
- Checks, observations, limitations, and user decisions
- State: pending, ready, running, needs attention, or complete

A completed step requires outputs and checks. Scientific agreement is recorded separately so execution success cannot be mistaken for validation.

## First implementation slice
Complete orientation, protein preparation, and solvent preparation, then one explicit-solvent minimization/equilibration path and its initial analysis. Keep the sphere, box, implicit-solvent, nonequilibrium, and pulling branches on the coverage checklist. Choose the first run branch after auditing source fidelity and implementation effort.

## Next design task
Audit the source files and configurations, then specify the first preparation step: exact inputs, generated files, engine mapping, learner-facing explanation, and failure recovery. No simulation has been executed or validated yet.
