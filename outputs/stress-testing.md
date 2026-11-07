# Readiness stress tests and coordinate-output overhead

Measured locally on November 6, 2026, using OpenMM 8.6.1, the CPU platform with one thread, and the official psfgen 2.0 executable from NAMD 3.0.3. Inputs are the previously checked ubiquitin (1UBQ) and villin (1VII) preparations (the preparation workflow has also been compared against VMD), CHARMM36 protein topology, CHARMM36m protein parameters, and the CHARMM water stream. User force-field files and generated molecular artifacts remain outside Git.

## HTTP workflow checks

Each complete run used the existing bounded minimization and 100 NVT steps at 2 fs (0.2 ps), target 300 K. Implicit OBC2 uses 0.2 M screening; explicit TIP3 uses the existing periodic PME water box with no ions or neutralization.

| Protein | Environment | Coordinates / energy / temperature intervals (steps) | Wall time | Result |
|---|---|---|---:|---|
| Villin | Implicit OBC2 | 13 / 7 / 11 | 19.26 s | Passed |
| Ubiquitin | Implicit OBC2 | 7 / 6 / 10 | 54.56 s | Passed |
| Villin | Periodic TIP3, 9,044 particles | 101 / 101 / 101 | 62.69 s | Passed |
| Ubiquitin | Periodic TIP3, 18,046 particles | 1 / 2 / 3 | 190.72 s | Passed |

Checks verified exact scheduled energy/temperature steps, simulation timestamps (`step × 0.002 ps`), the most recent scheduled Cα frame, finite reported values, and total energy equal to potential plus kinetic energy. Minimization retains null simulation time and temperature. The 101-step case correctly has only step-zero dynamics outputs; its final 100-step PDB is still saved separately.

Both proteins were also generated again through the preparation API and reuploaded unchanged. Atom identities, types, charges, masses, every bonded-term class and coordinates matched the checked preparations exactly (maximum coordinate difference 0 Å); psfgen reported no warnings.

All direct downloads matched their ZIP entries. Live CSV and JSONL matched the persisted samples, including blanks/nulls for channels not sampled on that step. Prepared, solvated and final PSF/PDB pairs passed correspondence checks. A second simultaneous run was rejected in each case. Invalid intervals (zero, negative, fractional, boolean and over the limit) and a mismatched PSF/PDB were rejected before execution.

A separate ubiquitin implicit run was stopped during dynamics. It ended as cancelled, retained partial samples and coordinates, and its exports remained available. Each completed/cancelled run was also read through HTTP after removing the completed in-memory job, verifying disk recovery. A new server process and browser loaded the completed explicit ubiquitin result successfully.

## Browser findings and corrections

Reloading the browser during the actual every-step ubiquitin run reconnected to the same running job, showing a later snapshot at step 55 (0.11 ps) with its original 1 / 2 / 3-step intervals. No browser errors were reported. After completion, the latest energy is at step 100 (0.2 ps), while temperature is at step 99 (0.198 ps), as expected from the independent schedules.

The check exposed a display issue: on reconnect, disabled interval inputs showed browser defaults even though the run description and actual output used the correct settings. Active inputs now show the frozen run values and their correct timestep conversion. Completed-run controls are explicitly labeled as settings for the next run. The viewer header now identifies the loaded run and Cα count instead of saying no structure is loaded. A regression check covers the restored intervals and a run timestep different from the form's next-run timestep.

## Timing protocol

Coordinate extraction/output is timed separately from preparation, water packing and minimization. Each protein uses an existing explicit System/state pair. Every trial restores its starting state, uses LangevinMiddle at 2 fs and one CPU thread, warms up for five steps, restores the state again, and times 30 integration steps. Three repeats alternate the order of no coordinate reporter, coordinates every 10 steps, and coordinates every step. Energy and temperature reporting stay fixed at every 10 steps. The coordinate modes produce 0, 3 and 30 frames per trial.

These timings include coordinate retrieval, Cα extraction, JSON serialization and atomic latest-frame writes. They exclude HTTP polling, browser rendering, preparation/minimization, and full-trajectory writing. They assess reporting cost on these two systems, not all hardware or production-scale workloads. Stochastic integrator random streams are not reset by restoring a State, so this is a performance comparison, not a bitwise trajectory comparison. An initial longer timing pilot was stopped during warm-up before any timed results were collected; only the completed repeated trials are used below.

Median wall time for 30 steps, with the minimum–maximum across three repeats in parentheses:

| Protein | No coordinate output | Every 10 steps | Every step |
|---|---:|---:|---:|
| Villin | 8.21 s (8.07–11.11) | 7.50 s (7.50–12.78) | 7.89 s (7.67–9.96) |
| Ubiquitin | 16.54 s (15.49–20.98) | 17.85 s (16.10–20.93) | 17.76 s (16.50–20.54) |

Every-step coordinate output had a median 7.3% above the no-coordinate case for ubiquitin and 3.9% below it for villin. The intervals overlap substantially, and the ordering is not consistent between repeats. The lower villin median is not evidence that writing coordinates speeds up integration. These short trials do not establish a precise slowdown percentage.

A separate fixed-Context microbenchmark measured position retrieval, Cα extraction, JSON serialization and an atomic latest-frame write, without integration: 10 warm-up captures followed by 100 timed captures. Median costs were **14.08 ms for villin** and **27.93 ms for ubiquitin**; the 95th-percentile costs were 20.24 and 38.43 ms. This direct cost supports keeping the default at every 10 steps rather than writing every step. It excludes HTTP polling and browser rendering and is specific to this CPU setup.

No failures or nonfinite energies occurred in the 18 completed dynamics timing trials. The API runs prove that the viewer receives updates during dynamics, but do not isolate browser drawing cost or measure GPU performance.

## Scientific limits

Passing the stress checks establishes execution and output correctness for these bounded cases, not equilibration. Explicit ubiquitin's sampled temperature reached about 420.43 K despite the 300 K target, and implicit temperatures also drifted during the short relaxation. Villin with 101-step intervals has only its initial temperature sample, so that trace cannot assess temperature evolution. Longer controlled minimization and NVT equilibration remain necessary. Villin remains charged because ion addition is deferred.

Local evidence is retained under `work/stress-testing/2026-11-06/`: API runs, per-file hashes, the report, and live/fresh-server browser observations. Repeated timing records are under `timing/report.json`; `snapshot-cost.json` records the fixed-Context measurements and `preparation-checks.json` records regeneration/upload comparisons. These paths are excluded from Git. The reusable runner is `scripts/stress_readiness.py`; invoke it as `python -m scripts.stress_readiness --help` and supply checked preparation/environment directories plus local CHARMM inputs. Use `--benchmark-steps 30 --infrequent-coordinate-steps 10 --repeats 3` to reproduce the short timing protocol, or `--benchmark-only` to skip the complete readiness cases.
