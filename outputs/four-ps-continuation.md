# Ubiquitin checkpoint continuation to 4 ps

On November 10, 2026, the saved [2 ps explicit-water ubiquitin run](two-ps-nvt.md) was resumed for 1,000 additional steps at 2 fs, using its original System, integrator and 10-step output intervals. The 18,046-particle periodic system has no added ions or neutralization. OpenMM 8.6.1 ran on the CPU platform with one thread. This is one continuation, not an independent replicate or a production protocol.

The run completed at step 2,000 (4 ps). Its 201 dynamics samples cover steps 0–2,000 every 10 steps without gaps or duplicate steps; all reported temperature and energy values were finite. The final checkpoint loaded into the matching System and integrator and restored step 2,000 at 4 ps.

| Window (ps) | Mean temperature (K) | Mean potential energy (kJ/mol) |
|---|---:|---:|
| 2.0–2.5 | 318.28 | −231,064.5 |
| 2.5–3.0 | 311.76 | −233,156.1 |
| 3.0–3.5 | 306.76 | −234,524.0 |
| 3.5–4.0 | 306.33 | −234,763.0 |

Windows include their first sample and exclude the last, using step numbers to define boundaries. At 4 ps the sampled temperature was 303.58 K and potential energy was −234,426.9 kJ/mol. The later temperature means are closer to the 300 K target, while the window means of potential energy continued to decrease. These short windows do not establish equilibrium or stability.

The 76 protein Cα atoms in the 2 ps and 4 ps endpoint PDBs have an optimally aligned RMSD of 0.569 Å. This compares only two saved endpoints, using their rounded PDB coordinates; it cannot describe intervening structural changes. The live coordinate preview is not a trajectory.

Local continuation: `runs/live/20811dca-f771-4eb5-bd8e-e105ea291ca2/`; original: `runs/live/76786f03-d7eb-4321-b141-961478b2400b/`. These generated artifacts are excluded from Git. More systems, independent replicates, longer controlled relaxation, trajectory-based structural analysis, and a reviewed ionic environment remain necessary before production use.

As a separate software check on the same date, all 67 Python regression tests passed with OpenMM and standalone psfgen configured, including the 12 tests skipped without a native backend. The OpenMM integration tests use synthetic parameters; their success is not a scientific validation of this protein.
