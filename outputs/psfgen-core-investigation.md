# Standalone psfgen core investigation — 2026-10-29

## Official download follow-up — 2026-11-01

The user downloaded the official **NAMD 3.0.3 MacOS universal multicore binary
distribution**, rather than the source archive. It includes a standalone universal
`psfgen` executable (Apple Silicon and Intel), so building from source may not be
necessary on this machine.

- Download archive SHA256:
  `775e3b2e5c95932c160d2ee490b03401fcac4f3d9e13fc7c85a118ab3e68c2c3`.
- Archive member: `NAMD_3.0.3_MacOS-universal-multicore/psfgen`, 2,861,571 bytes.
- Member SHA256:
  `7878f0f6f55a27f3404b2c7f1345418202836023469783e4e2c1ac5aa408f495`.
- These are locally computed hashes for reproducibility, not signatures or an
  independently verified upstream checksum.

Initial startup was terminated before version output. The executable carried
the macOS download-quarantine attribute. After the user reported approving it,
the extracted `psfgen` file was no longer present in the Downloads package folder.
The archive still contains it. Official-runtime verification and the ubiquitin
comparison remain pending locating/restoring the executable. No quarantine flags
were removed and no macOS security settings were changed by the agent.

The app now has an optional controlled Tcl subprocess adapter selected with
`--psfgen /absolute/path/to/psfgen` or `MOLVIS_PSFGEN`. The adapter requires 2.0+,
records executable/version provenance, saves its script, and rejects engine
errors even on a zero process exit. Adapter and regression tests pass (26 tests);
this is not a claim that the downloaded binary has been validated. The active
backend has not been switched.

## Conclusion

A standalone psfgen 2.0 executable is a viable replacement backend for the
current Python psfgen 1.0.5 wrapper. An isolated Apple Silicon build completed
without VMD and parsed our unmodified CHARMM36 protein topology without the
`AUTO ANGLES DIHE PATCH` diagnostic. It requires Tcl as a backend runtime;
visitors would still not need to install VMD or Tcl.

This is a feasibility result, not a production dependency upgrade. The active
application still uses Python psfgen 1.0.5. No topology files were edited, no
simulation was run, and the website demo was not changed.

## Sources checked

- [Eigenstate/psfgen](https://github.com/Eigenstate/psfgen): latest tag and
  repository HEAD were v1.0.5 / `a6d9ca1` during this investigation. Its parser
  handles ANGL and DIHE but reports other AUTO tokens as errors. There is no
  newer published wrapper release to install directly.
- [VMD psfgen plugin](https://www.ks.uiuc.edu/Research/vmd/plugins/psfgen/):
  upstream identifies the core as version 2.0.
- [NAMD 3.0.3 announcement](https://tcbg.illinois.edu/Research/namd/3.0.3/announce.html):
  explicitly includes the psfgen 2.0 update.
- Eigenstate/vmd-python source at
  `65f10e87983d0ebd8e761a2a8499df5bf654373e` still contains the older 1.7 plugin;
  replacing our wrapper from that repository would not supply the desired core.
- For the isolated build, used the psfgen source in
  [lmcad-unicamp/PI-HPC-Bench](https://github.com/lmcad-unicamp/PI-HPC-Bench/tree/ba755284721f6129657ffcce53361ee269e23344/namd2/psfgen/src),
  pinned to `ba755284721f6129657ffcce53361ee269e23344`.
  The files have UIUC revision headers dated 2020-03-10; Tcl reports 2.0.
  This is a third-party mirror, not verified as the newest VMD distribution.
  It establishes feasibility but should not become the production dependency
  without obtaining/verifying an official source distribution.

## Build experiment

Sources and binary were kept in `/private/tmp/molvis-psfgen2/`. Compile the
source `.c` files except the legacy `psfgen_wrap.c` using `cc -O2 -DNEWPSFGEN`,
the source include directory, macOS SDK Tcl headers, and `-ltcl8.5 -lm`.
The source's `tcl_main.c` provides the standalone entry point. No VMD graphics,
molfile plugins, or Python extension were required. Build finished without
compiler diagnostics. `package require psfgen` returned `2.0`.

The newer parser recognizes PATC and DRUD tokens by explicitly continuing past
them. This removes the diagnostic; it does not establish CHARMM-style automatic
regeneration after arbitrary patches. Patch handling still needs explicit tests.

## Ubiquitin comparison

Used the local `1UBQ.pdb`, protein-only selection, the original unmodified local
`top_all36_prot.rtf`, HIS→HSE and ILE CD1→CD aliases, and NTER/CTER patches.
Compared against saved preparation `6daae194-c296-47e3-80ce-ac00ad8cf091`.

| Check | Existing Python wrapper | Standalone 2.0 experiment |
|---|---:|---:|
| AUTO/PATCH parser diagnostic | Present | Absent |
| Atoms | 1,231 | 1,231 |
| Bonds | 1,237 | 1,237 |
| Angles | 2,257 | 2,257 |
| Dihedrals | 3,293 | 3,293 |
| Impropers | 212 | 212 |
| CMAP cross-terms | 74 | 74 |

Atom definitions, ordered bond/angle/improper/CMAP indices, and the dihedral
tuple multiset match. Dihedral ordering differs. The generated PDB is byte-for-byte
identical (SHA256 `7b1248df07246e92fcd70478531e207ee78dab2c8fec8a75fb6455068fcb0e84`).
The pair passes the existing ordered-atom identity check.

Terminal O/OXT coordinate-assignment warnings persist. The newer run does not
print the old poorly-guessed-coordinate warnings, despite producing identical
coordinates. Fewer log warnings must not be mistaken for improved geometry.

## Integration direction

1. Obtain an official psfgen 2.0 source distribution and pin its provenance/hash.
2. Build/package only the standalone executable and its Tcl runtime in the backend.
3. Add a subprocess adapter that produces a controlled Tcl script from our
   validated preparation settings, checks the actual version, and records it.
4. Compare atom definitions, bonded terms, termini and patch behavior, not just
   atom counts or exit status. Check engine diagnostics separately from return code.
5. Resolve terminal coordinate naming and validate matching CHARMM parameters
   and geometry before enabling simulation.

The Python wrapper's C API is not a drop-in match for the newer source: for
example, `topo_mol_error_handler` has a changed callback signature. A small
standalone process adapter avoids porting and maintaining that extension.
