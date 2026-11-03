# Live OpenMM measurements

Implemented and checked locally on 2026-11-02 with OpenMM 8.6.1. This extends the existing bounded readiness run; it does not launch the proposed full production duration.

## Measurements and plots

- Minimization emits the **system potential energy**, temporary restraint energy, optimizer iteration, monotonic report index and maximum constraint error through OpenMM's MinimizationReporter. There is no invented simulation time or temperature for optimization.
- Dynamics use OpenMM's StateDataReporter for potential, kinetic and total energy, simulation time, step and instantaneous temperature. Its temperature calculation accounts for constraints and removed center-of-mass degrees of freedom. Values are sampled at step 0 and every 10 steps through step 100.
- The browser polls an asynchronous run record and redraws SVG traces as samples arrive. It shows a target-temperature reference line, point tooltips, units, a latest-values table and separate minimization/dynamics axes.
- The run retains its submitted settings even if the form changes. Refresh reconnects without starting another simulation. The Stop control terminates the worker process group and keeps partial data. Missing connections, failures, timeouts, cancellations and interrupted server sessions are distinct from successful completion.

The 20-iteration minimization argument is **per optimizer pass**, not a guarantee of 20 total reports: OpenMM may restart optimization as it strengthens constraint restraints. Potential energy need not decrease monotonically across those passes. The 240-second worker limit still bounds the readiness request.

## Real-run verification

Villin 1VII was run in the explicit periodic TIP3 box with no added ions, using the local CHARMM36 protein topology, CHARMM36m parameters and CHARMM water stream. Target 300 K, timestep 2 fs, one CPU thread, LangevinMiddle, seed 2026; 100 dynamics steps (0.2 ps).

The live API delivered samples **before completion**. The completed record contains **112 samples: 101 minimization reports (including the initial potential) and 11 dynamics samples**. The browser was observed during minimization with blank temperature/dynamics plots, then after completion with populated traces. Refresh restored the same measured values. CSV and JSONL exports matched all samples and retained null temperature/time entries for minimization.

The measured dynamics temperature ranged from about **298.10 to 355.80 K**, ending at **351.80 K** despite a 300 K target. This short relaxation is **not equilibrated**, and the plots correctly expose that rather than labeling finite execution as temperature stabilization. Longer minimization/relaxation and equilibration remain separate work.

Evidence: `work/live-monitor-check.json`; live record `runs/live/947853c8-6e0e-4290-94c0-cf6b603c2d71/`; completed environment `runs/environments/356e7eea-5847-4a57-86c6-0c0efbf7c3c2/`. These generated scientific data and user force-field inputs are excluded from Git. The README preview is refreshed from the actual interface and real measurements.

## Persistence and validation

Each live directory contains `run.json` and flushed `measurements.jsonl`. The API provides CSV/JSONL exports while active, after cancellation/failure, and after completion. Successful environment artifacts also contain `measurements.csv`, `measurements.jsonl` and OpenMM's `dynamics.csv` in their direct downloads and ZIP.

All **57 regression tests pass**. Coverage includes sample visibility before completion, one-active-run enforcement, stopping a native subprocess, cancellation with retained data, interrupted-state recovery, real OpenMM reporter values, constrained-temperature calculations on a known test system, energy sums, phase separation, API exports and origin checks. UI verification used real villin measurements; no simulated data fallback is used.

References: [OpenMM StateDataReporter](https://docs.openmm.org/latest/api-python/generated/openmm.app.statedatareporter.StateDataReporter.html) and [MinimizationReporter interpretation](https://docs.openmm.org/latest/api-c%2B%2B/generated/MinimizationReporter.html).
