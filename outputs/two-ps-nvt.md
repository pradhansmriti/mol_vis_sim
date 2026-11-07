# Ubiquitin: 2 ps NVT test

Completed on November 6, 2026. Ubiquitin (1UBQ) was prepared with CHARMM36 protein topology and CHARMM36m parameters. The explicit periodic TIP3 water box contained 5,605 waters and 18,046 total particles, with a 5.678 nm side and no added ions. OpenMM 8.6.1 ran on one CPU thread; water topology preparation used standalone psfgen 2.0.

After bounded minimization (20 iterations per optimizer pass), LangevinMiddle ran 1,000 steps at 2 fs, target 300 K, friction 1/ps, seed 2026. Coordinates, energy and temperature were sampled every 10 steps. The worker completed in about 12.6 minutes, including setup and minimization. The trace contains 141 minimization samples (including the initial energy) and 101 dynamics samples.

| Measurement | Result |
|---|---:|
| Simulated time | 2.00 ps |
| Peak sampled temperature | 417.7 K |
| Mean sampled temperature, first 0.5 ps | 379.2 K |
| Mean sampled temperature, last 0.5 ps | 327.4 K |
| Final sampled temperature | 326.6 K |
| Final potential energy | −230,185.2 kJ/mol |

The system cooled substantially after the initial heating. It was still about 27 K above target at the final sample, so this run does not establish thermal equilibration. Finite execution and readable artifacts are the checks that passed here.

The completed PSF/PDB pair passed correspondence checks. CSV and JSONL matched the recorded samples, and direct downloads matched the environment ZIP. The final binary checkpoint was loaded into the matching CPU System and integrator and restored step 1,000 at 2 ps. Portable state XML, System and integrator XML, checkpoint, final PDB, and measurements are saved. The browser reconnected during dynamics and restored the frozen run length and output intervals.

Local run: `runs/live/76786f03-d7eb-4321-b141-961478b2400b/`. Final environment: `runs/environments/358ded33-3cee-419f-8c63-8657cb46dff5/`. Verification and download hashes: `work/two-ps-check.json`. Generated artifacts and local force-field inputs are excluded from Git.

Binary checkpoints require a matching OpenMM System, platform, version and hardware; portable State XML does not preserve the full random-number-generator state. See the [OpenMM checkpoint documentation](https://docs.openmm.org/latest/api-python/generated/openmm.app.checkpointreporter.CheckpointReporter.html).
