# Basic tutorial: prepare and test a protein

This walkthrough uses the local workspace to prepare or upload a protein, inspect it, and run a short OpenMM readiness test. The workspace proposes a workflow from the settings you select; the simulation-goal text is saved as context and is not interpreted as instructions. A readiness test is not production dynamics or evidence of equilibration.

The longest documented protein dynamics test is one 4.0 ps ubiquitin run, including a checkpoint continuation. The workspace has not been validated for equilibration or long-time production runs, and production execution is not connected. See the [4.0 ps results](../outputs/four-ps-continuation.md).

## Before you start

Follow [Run locally](../README.md#run-locally) to install OpenMM and start the server. For generation, also configure standalone psfgen and have a protein PDB, a compatible CHARMM topology, and matching parameters available locally. Alternatively, use an existing matched PDB/PSF pair and its matching parameters. Force-field files are not supplied with the project.

Open `http://127.0.0.1:8765` (or the port you selected). If you have configured the prepared ubiquitin example as described in the README, **Try an example** walks through a short implicit-solvent test. Otherwise choose **Use your own structure** and follow the steps below.

## 1. Prepare and inspect

1. In **Prepare simulation files**, choose either **Generate PSF + PDB** or **Upload an existing PSF + PDB pair**. Supply the requested files and matching parameters.
2. For generation, review histidine, terminal patches and hydrogen handling, then confirm permission to guess missing coordinates. Resolve gaps, alternate positions and special patches before generation. Select **Generate PSF + PDB**; for an existing pair use the upload action instead.
3. Inspect the result in **Structures**. Select the original, protein selection or prepared pair as available; drag to rotate and scroll to zoom. Download the preparation bundle and manifest to retain the inputs and preparation record.

## 2. Choose a test and propose a workflow

1. Open **Later: solvation, salt and OpenMM compatibility**. For a first test, select **Implicit OBC2** and keep its default ionic screening if appropriate for your experiment. This represents screening; it does not add discrete ions.
2. Set temperature and timestep, then select **Check OpenMM compatibility**. Resolve any missing files or parameter errors before continuing. A compatible result only establishes that this configuration passed the bounded checks.
3. Select **Propose workflow** to review the steps and **Export plan** to save them. Production and equilibration durations in the plan are not executed by the readiness test.

## 3. Run and review

1. Set the NVT test length and output intervals before starting. The default 100 steps at 2 fs represent 0.2 ps; the maximum is 1,000 steps per run. At 2 fs, an interval of 10 steps records every 0.02 ps.
2. Select **Run + plot readiness**. Watch minimization, then temperature and energy in **Simulation output**. Hover over plotted points for values. The latest coordinate snapshot is a preview, not a trajectory.
3. Download the available measurements and run artifacts. A saved checkpoint can be continued with **Resume from checkpoint**, subject to OpenMM's system, version, platform and hardware compatibility requirements. **Stop run** retains partial measurements.

Check for errors and nonfinite values, but do not infer equilibration from a completed short test or a single temperature reading. For explicit water, the current implementation adds no ions or counterions. Review the force field, protonation, system charge and protocol separately before production. See the [readiness results](../outputs/stress-testing.md) and [2 ps ubiquitin test](../outputs/two-ps-nvt.md) for examples and limitations.
