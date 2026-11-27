# External benchmark data recovery

The historical CBI-EXTERNAL-48-v1 panel has been reconstructed from its original deterministic selector (`code/bench/inventory.py` at pgm `5ae02ff`) using the official UAI2022 Tuning and Final MAR archives, and the 12 named bnlearn BIF networks. No inference outcomes were used in selection. The original selector and converter are unchanged copies in `recovery_scripts/`.

`BENCHMARK_INPUTS.json` is the execution inventory. Its `tasks` array is the 46 available historical tasks; `extensions` contains nine later external successes; `synthetic_regressions` contains the separate G4 preservation task. Each row carries absolute model/evidence paths and SHA256. Download hashes, source URLs, source paths, historical canonical hashes, and structural metadata are retained. `PANEL_SELECTION.json` and `INVENTORY.json` are the unchanged selector outputs.

The 48-slot design has one unfilled Pedigree slot and one unfilled CSP slot: each family has only three distinct eligible inputs. These are visible shortfalls, not solver failures.

Three forced historical anchors (Grids_11, Pedigree_11, Promedus_12) match the original selector's pinned raw hashes. The overlapping DGP9 preservation inputs were checked against that packet's model/evidence hashes. All 42 downloaded-UAI overlaps against selected or retained packet inputs match in both files. The original full historical frozen inventory was not available locally, so reconstructing the full panel by its original deterministic rule is distinguished from directly checking every original frozen manifest row.

The bnlearn conversion independently checks all 1,180,871 CPT entries. Original decimal values are preserved as exact rationals. Several BIF CPT rows have decimal row-sum defects; these are recorded rather than renormalized, matching the historical converter's semantics. Evidence is the original no-evidence task (`0` plus newline), matching the retained MILDEW packet exactly. MUNIN1's current official URL is under `munin4/munin1.bif.gz`; two attempted paths returned 404 before the published link was resolved.

The nine external extension tasks are Alchemy_11, DBN_14, mastermind_03_08_04-0003, ObjectDetection_43, mastermind_03_08_05-0003, or_chain_186.fg, or_chain_209.fg, linkage_13 and Promedus_36. Duplicates of primary tasks were removed by model+evidence hashes. G4_near_c3_theta17-20_span3 is a constructed regression input and must not be pooled into the external denominator.

To rerun metadata selection after restoring sources:

```
PYTHONPATH=/path/to/pgm/code python recovery_scripts/inventory.py /path/to/external_benchmark_data
python recovery_scripts/build_manifest.py
```

The second command currently binds the local DGP9 packet location in its source; execution inputs themselves are all copied under `inputs/`, so benchmark execution requires neither the original workstation nor those restoration paths.

This recovery performed downloads, archive extraction, exact parsing, conversion verification, hashing and deterministic selection. It performed no inference or benchmark cell.
