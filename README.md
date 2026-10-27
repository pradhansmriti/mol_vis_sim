# Protein simulation workspace

The agreed product design, specification, and interactive preview are in [outputs/README.md](outputs/README.md).

## Run locally

Requires Python 3.10 or newer. No third-party dependencies are needed for this planning prototype.

```sh
python3 -m molvis
```

Open http://127.0.0.1:8765. Upload a fixed-column PDB, edit the explicit settings, and select **Propose workflow**. The viewer projects actual Cα coordinates and supports drag rotation and scroll zoom. Export saves the proposed configuration, structure hash, original PDB text, steps, and decisions as JSON. Uploads are processed locally in memory and are not written to disk.

This first implementation supports planning and structure inspection. It does not interpret natural-language requests, repair structures, validate force-field templates, or execute OpenMM. Temperature/energy data and trajectory controls will become available with the runner. A parsed PDB is not a scientifically validated structure. Multiple models, alternate locations, and duplicate atoms require explicit resolution before planning; non-protein components are retained and flagged for review. PDB files are limited to 5 MB; mmCIF is not yet supported.

The default request names ubiquitin as an example; it does not identify the uploaded protein. Supply your own ubiquitin PDB to plan that example. Production duration is separate from the optional preparatory equilibration duration. No equilibration is silently added.

## Checks

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
```

## Next implementation

Connect a validated OpenMM runner to these plan/step/event records: preparation review, template validation, minimization, optional equilibration, production, trajectory and state reporters, and reproducibility metadata. Add temperature and energy tabs driven by recorded samples. Scientific validation remains separate from execution success.

Proposed force-field and solvent settings follow the supported combinations described in the [OpenMM application guide](https://docs.openmm.org/latest/userguide/application/02_running_sims.html). They have not yet been validated against a ubiquitin run or the NAMD tutorial.
