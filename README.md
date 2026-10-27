# Protein simulation workspace

The agreed product design, specification, and interactive preview are in [outputs/README.md](outputs/README.md).

## Run locally

Requires Python 3.10 or newer. Existing PSF/PDB uploads and planning use the standard library. Generation uses the standalone Python `psfgen` library in the backend; VMD and Tcl are not required.

```sh
python3 -m molvis
```

Open http://127.0.0.1:8765. Prepare the files using one of the two routes below, then edit the settings and select **Propose workflow**. The viewer projects actual Cα coordinates and supports drag rotation and scroll zoom. Export saves the proposed configuration, file hashes, prepared PDB/PSF text, steps, and preparation record as JSON.

## Prepare files before planning

**Starting topology: CHARMM36 protein file `top_all36_prot.rtf`.** Select your local copy in the topology uploader. Our local distribution pairs it with the CHARMM36m protein parameters `par_all36m_prot.prm`. Files are supplied by the user, not bundled or downloaded automatically; other compatible topologies can still be selected.

**Protein/lipid file note:** In our CHARMM36 distribution, protein and lipid topologies are separate: `top_all36_prot.rtf` and `top_all36_lipid.rtf`. Protein-only preparation needs just the protein topology. Older distributions provide a combined file such as `top_all27_prot_lipid.inp`, containing CHARMM22 protein and CHARMM27 lipid definitions.

Other compatible CHARMM-format topology files can be uploaded instead, with their corresponding parameter files and appropriate residue aliases/patch choices. The uploaded contents determine the preparation; the filename is not hard-coded. Other force-field families remain possible future choices, but require a compatible preparation/runner path. A PSF contains topology information and does not replace the force-field parameter files required to run a simulation.

- **Generate PSF + PDB:** upload a protein PDB and the matching CHARMM residue topology files (`.rtf`). Review the HIS alias (HSE/HSD/HSP), first/last residue patches (NTER/CTER or NONE), and coordinate-guessing consent. The standalone backend splits chains/segments, maps ILE CD1 to CHARMM CD, builds atoms, assigns coordinates, and writes an X-PLOR PSF and matching PDB. Explicitly named histidine variants are retained. Missing backbone atoms, residue-number gaps, reused TER-separated segment IDs, insertion codes, alternate positions, and nonstandard residues require external resolution. Disulfide/custom patches are not inferred. No solvation or minimization occurs.
- **Upload existing files:** provide the PSF and PDB from the same preparation. Files are retained unchanged. Checks cover atom count, ordered residue/atom identity, segment IDs when present, finite charges/masses and coordinates. Bonded terms and parameter compatibility are not yet validated.

Both routes accept optional parameter-file uploads, retained in the downloadable ZIP for the future runner. Download PDB/PSF individually or a preparation bundle containing files, hashes, options, segment mapping, topology/parameter uploads and the engine log when generated. A checked pair is **not** marked simulation-ready. Matching CHARMM parameters, solvent selection and scientific validation remain required; PSF input is never assigned Amber14/OBC2 settings automatically.

For generation, install the backend dependency in an isolated environment (a C compiler is needed to build its extension):

```sh
python3 -m venv .prep-env
.prep-env/bin/python -m pip install -r requirements-preparation.txt
.prep-env/bin/python -m molvis
```

Alternatively use `conda env create -f environment.yml` and `conda run -n molvis python -m molvis`. The source dependency is version/hash pinned. The conda recipe builds from source so it can support platforms without a prebuilt psfgen package. For a separate preparation interpreter, set `MOLVIS_PREP_PYTHON` to its absolute Python path before starting the server. Browser users need no VMD installation; a hosted deployment must install the library on its server.

Generation runs in a temporary scratch directory in an isolated worker process with a 120-second timeout. After a successful pair check, both generation and upload routes persist their files in a unique folder:

```text
mol_vis_sim/runs/preparations/<preparation-id>/
  prepared.pdb
  prepared.psf
  manifest.json
  preparation.zip
  source.pdb          # original input, for generated pairs
  psfgen.log          # for generated pairs
  topologies/        # supplied topology files, for generation
  parameters/        # supplied parameter files, when provided
```

The interface shows the absolute server folder after preparation, and the response and manifest record the paths. Each preparation gets a new ID; earlier outputs are not overwritten. Files survive closing the page or restarting the server. They are excluded from Git and remain until manually removed. **Download PDB**, **Download PSF**, **Download manifest**, and **Download all files (ZIP)** serve the saved files directly, saving additional copies to the browser's configured download location. Download URLs are included in the response/manifest and remain usable while the server is running with the same output root and files are retained. In the current local setup, the server folder is on your computer; in a hosted deployment, it would be on the server.

The default root is `<repository>/runs/preparations`, independent of the launch directory. Set `MOLVIS_OUTPUT_DIR` before starting the server to use a different root. The server must have write access. Results are published only when the complete folder has been saved; a write failure returns an error rather than claiming success. Temporary scratch files are removed after each request. Each input file is limited to 5 MB, the request to 30 MB, and topology/parameter uploads to 12 files of each kind. Topology and parameter data are not executed as scripts. The server remains bound to loopback.

This implementation supports preparation, planning and structure inspection. It does not interpret natural-language requests, validate a complete simulation parameter set, or execute OpenMM. Temperature/energy data and trajectory controls will become available with the runner. A parsed PDB is not a scientifically validated structure. Multiple models, alternate locations, and duplicate atoms require explicit resolution; non-protein components are retained in existing pairs and flagged for review. mmCIF is not yet supported.

The default request names ubiquitin as an example; it does not identify the uploaded protein. Supply your own ubiquitin PDB to plan that example. Production duration is separate from the optional preparatory equilibration duration. No equilibration is silently added.

## Checks

```sh
python3 -m unittest discover -s tests -v
.prep-env/bin/python -m unittest discover -s tests -v
node --check web/app.js
```

## Next implementation

The native-generation test runs when psfgen is installed, and is skipped in the dependency-free environment. It uses a synthetic topology for testing only, generates an added atom, checks the pair, reuploads it, and creates a plan.

Connect a validated OpenMM runner to these plan/step/event records: CHARMM parameter validation, preparation review, minimization, optional equilibration, production, trajectory and state reporters, and reproducibility metadata. Add temperature and energy tabs driven by recorded samples. Scientific validation remains separate from execution success.

Proposed force-field and solvent settings follow the supported combinations described in the [OpenMM application guide](https://docs.openmm.org/latest/userguide/application/02_running_sims.html). They have not yet been validated against a ubiquitin run or the NAMD tutorial.

Preparation uses the [standalone Python psfgen API](https://psfgen.robinbetz.com/api.html) ([source](https://github.com/Eigenstate/psfgen)). ParmEd was considered for conversion, but exporting topology alone does not replace residue construction and coordinate generation. CHARMM workflows still require matching parameter files, as described in the OpenMM guide above.

The older combined topology and parameter filenames follow the [NAMD topology tutorial](https://www.ks.uiuc.edu/Training/Tutorials/tutorialfiles/topology/TCBGTUTORIAL_TOPOLOGY_UPDATED2026.pdf). The presence of lipid definitions does not expand the current generator beyond its standard-protein input support.
