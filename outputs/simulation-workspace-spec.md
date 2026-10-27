# Protein simulation workspace — concept v0.2

## Product intent
Supply a protein and describe a simulation. The agent turns that request into an inspectable workflow, presents meaningful choices, executes the agreed configuration, and shows progress and results. Assume familiarity with MD; explanations are brief and contextual, with optional source links.

## Starting choices
- Protein systems; initial example: ubiquitin.
- OpenMM as initial engine.
- CHARMM36 protein topology `top_all36_prot.rtf` as the starting choice for PSF/PDB preparation; our local protein parameters are `par_all36m_prot.prm` (CHARMM36m). Users supply local files through the uploader. Other compatible topologies remain selectable. CHARMM36 separates protein and lipid topologies; older combined files such as `top_all27_prot_lipid.inp` contain CHARMM22 protein / CHARMM27 lipid definitions. This prototype uses only the protein topology.
- Both remain changeable.
- NAMD tutorial as a reference and replication benchmark, not a mandatory lesson sequence.

## Example interaction
Request: “Run 10 ps of ubiquitin in implicit solvent at 300 K.”

The agent resolves the supplied structure and proposes a plan. Show explicitly whether 10 ps means the requested dynamics segment or includes preparatory dynamics. Proposed default: 10 ps refers to the requested dynamics segment; minimization and any equilibration are listed separately with their own cost/duration.

Suggested plan, subject to protocol validation:
1. Inspect the structure and report missing components or ambiguities.
2. Prepare the protein, documenting changes and protonation assumptions.
3. Configure a compatible force field and implicit-solvent model, integrator, temperature, timestep, and output settings.
4. Minimize using visible stopping settings.
5. Perform any selected equilibration as a separate stage.
6. Run the requested 10 ps segment at 300 K.
7. Summarize outputs and basic quality checks.

The exact settings and whether equilibration is needed are protocol decisions, not hard-coded consequences of this example. No run has been launched.

## Options and decisions
Present a compact configuration with suggested values and editable choices. Surface decisions that materially change the system or protocol: structure selection, unresolved residues, protonation, force field/solvent compatibility, restraints, preparation/equilibration, duration, and compute target. Show routine settings in expanded details. Do not silently repair ambiguous structures or change an agreed scientific protocol after a failure.

## Workspace layout
- Request and settings: input protein, goal, resolved configuration, and plan.
- Visualizer: selected structure, preparation changes, selected atoms, and saved trajectory frames.
- Workflow: completed steps, current step, upcoming step, and progress where measurable.
- Activity: concise events by default, with a detailed log available.
- Results: trajectory, final structure, plots, and downloadable run record.

Selecting a step shows its associated structure or artifacts. During execution, show the latest saved frame and its simulation time. Label historical/selected frames clearly so they cannot be mistaken for a live state. Preparation stages can show changed atoms or residues; minimization can show before/after structures; dynamics can show saved frames.

## Progress display
For each step show: name, state, brief action, start/end time, and relevant outputs. Dynamics progress includes completed versus requested steps and simulated time. Display an ETA only when there is enough measured throughput to support it. The upcoming step reflects the actual dependency chain; unexpected problems place dependent work on hold.

States: proposed, ready, running, complete, needs attention, failed, cancelled. Support inspection before execution and pause/resume/cancel where the engine and checkpoint state permit.

## Two log levels
Concise activity log: meaningful events, preparation changes, stage transitions, progress milestones, warnings, and output links.

Detailed execution log: timestamps, complete resolved settings and units, package/engine versions, platform, seeds, source/input hashes, preparation transformations, runner output, errors, checkpoints, and analysis records. Keep it synchronized with the concise log through common step/event IDs.

Illustrative concise events, not actual run output:
- Structure inspected; preparation choices ready for review.
- Prepared protein saved; changes available in the visualizer.
- Minimization running.
- Dynamics: 4 / 10 ps complete; latest saved frame at 4 ps.
- Dynamics complete; generating summary.

## Agent and execution responsibilities
The agent interprets requests, proposes options, explains events, and helps resolve problems. A structured workflow runner executes validated actions, records artifacts, and reports state. The visualizer and logs consume the same workflow events. Scientific checks remain separate from execution success; a short completed trajectory does not establish convergence.

## First prototype acceptance criteria
A user can provide ubiquitin, request the illustrative run, inspect/edit the proposed settings, start it, see the current/upcoming step, select stage-associated structures, inspect short and detailed logs, play saved frames, and retrieve outputs with a reproducible run record. Problems appear at the relevant step with actionable details.

## Next implementation design
Define the single-screen workspace and the structured run/step/event records, then implement the first end-to-end ubiquitin example. Audit tutorial-to-OpenMM fidelity separately where replication is claimed.

## Selected layout and monitoring (v0.3)
Viewer-first layout selected: large viewer, workflow on the right, compact settings below, logs along the bottom. Viewer tabs: Structure, Temperature, Energy. Plot reported samples against timesteps or simulation time; show units, stage boundaries, target temperature, and the latest sample time. Energy quantity selector: potential, kinetic, total. Plots update from run records and help assess equilibration; they must not automatically imply convergence. Illustrative mockup data is clearly labeled.
