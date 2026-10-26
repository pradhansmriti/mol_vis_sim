# Protein simulation agent

Design repository for an interactive workspace that turns a supplied protein and a natural-language simulation request into an inspectable workflow.

Status: agreed interface concept and interactive mockup. No simulation backend is implemented, and no MD run has been executed.

## Agreed experience
Example request: “Run ubiquitin for 10 ps in implicit solvent at 300 K.”

The agent proposes the required steps and meaningful options, executes the configured workflow, and reports what is happening now and what comes next. The interface assumes familiarity with MD; contextual explanations and tutorial links are available when useful.

## Selected single-screen layout
- Large viewer on the left, workflow on the right.
- Viewer tabs: Structure, Temperature, Energy.
- Compact run settings below the viewer and workflow.
- Activity logs along the bottom: concise updates and detailed execution records.
- Current step and upcoming step remain visible while inspecting the structure or plots.

The structure view follows selected workflow stages and saved trajectory frames. Temperature and energy plots show reported samples versus timesteps or simulation time. Temperature includes a target reference; energy offers potential, kinetic, and total quantities. These plots support equilibration assessment without automatically declaring convergence.

## Changeable starting choices
Protein simulations and OpenMM are the starting choices, reflecting the user's experience. Ubiquitin is the first example. The NAMD tutorial is a protocol reference and replication benchmark; it does not dictate a teaching-first interface.

Requested dynamics duration is shown separately from any preparatory equilibration. Preparation changes and consequential scientific choices must be visible. Execution success and scientific validation are separate states.

## Files
- `design/workspace-preview.html`: open in a browser to explore the interface. It contains a schematic protein and illustrative logs/plot data, not actual simulation outputs. Some preview styling may require an internet connection.
- `design/workspace-source.html`: editable source for the preview.
- `simulation-workspace-spec.md`: current behavior and prototype acceptance criteria.
- `agent-design-notes.md`: current direction and changeable choices.
- `tutorial-workflow-map.md`: earlier tutorial coverage inventory; its teaching-first framing has been superseded.

## First implementation goal
Provide one end-to-end ubiquitin example: structure input, inspectable plan and settings, stage-linked visualization, current/next step, both log levels, reported temperature/energy traces, and reproducible outputs. Audit exact tutorial files, parameters, and OpenMM equivalence before claiming protocol replication.

## Reference
NAMD tutorial, Unix/MacOSX, April 2017 (proposed baseline):
https://www.ks.uiuc.edu/Training/Tutorials/namd/namd-tutorial-html/

## Repository and next step
The project is connected to [pradhansmriti/mol_vis_sim](https://github.com/pradhansmriti/mol_vis_sim).

Next: continue implementation planning from the saved workspace design.
