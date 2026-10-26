# MD agent — working design notes

## Current product direction
An interactive simulation workspace for users who already understand MD. A user supplies a protein and a natural-language simulation goal. The agent suggests a concrete workflow, exposes meaningful options, executes it, and makes progress and results visible.

Proteins and OpenMM are changeable starting choices. Ubiquitin is the first example system. The NAMD ubiquitin tutorial is a reference and replication benchmark; teaching MD fundamentals is not the core product experience. Link relevant tutorial sections where useful.

## Example request
“Run 10 ps of ubiquitin in implicit solvent at 300 K.”
This is an illustrative request, not an instruction to launch a simulation yet.

## Core interface
- Protein/trajectory visualizer linked to the selected workflow step.
- Workflow showing completed, current, and upcoming steps.
- Concise activity log and expandable detailed execution log.
- Visible simulation settings, assumptions, options, and artifacts.

See simulation-workspace-spec.md for the current specification. tutorial-workflow-map.md is the earlier reference coverage map; its teaching-first interaction is superseded by this direction.
