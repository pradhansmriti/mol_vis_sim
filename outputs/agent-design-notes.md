# MD agent — working design notes

## Current product direction
An interactive simulation workspace for users who already understand MD. A user supplies a protein and a natural-language simulation goal. The agent suggests a concrete workflow, exposes meaningful options, executes it, and makes progress and results visible.

Proteins and OpenMM are changeable starting choices. Ubiquitin is the first example system. The NAMD ubiquitin tutorial is a reference and replication benchmark; teaching MD fundamentals is not the core product experience. Link relevant tutorial sections where useful.

The starting topology for the PSF/PDB preparation path is the combined protein/lipid file `top_all27_prot_lipid.inp`, with matching tutorial parameters `par_all27_prot_lipid.inp`. It contains CHARMM22 protein / CHARMM27 lipid definitions, not CHARMM36. Users must have the CHARMM topology files locally and upload them; the file is not bundled or automatically fetched. The user will provide a local copy for now. CHARMM36 and other compatible CHARMM-format topologies can be selected with matching parameters and aliases/patches. Other force-field families remain design choices that need a compatible implementation path. The uploaded files determine the actual preparation; the tutorial topology is not enforced by filename.

## Example request
“Run 10 ps of ubiquitin in implicit solvent at 300 K.”
This is an illustrative request, not an instruction to launch a simulation yet.

## Core interface
- Protein/trajectory visualizer linked to the selected workflow step.
- Workflow showing completed, current, and upcoming steps.
- Concise activity log and expandable detailed execution log.
- Visible simulation settings, assumptions, options, and artifacts.

See simulation-workspace-spec.md for the current specification. tutorial-workflow-map.md is the earlier reference coverage map; its teaching-first interaction is superseded by this direction.

The combined topology includes lipid definitions, but generation currently accepts standard proteins only; lipid systems need external preparation and PSF/PDB upload.
