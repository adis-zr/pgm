# Reproduce the raw audit

Use the qualified project Python environment. Extract the original archive into `<data>/PGM_STEP2_RUN_2026-11-27_f74f7f3/` and the supplement archive into `<data>/PGM_STEP2_SUPPLEMENT_RUN_step2-supplement-v1/`. Each archive already contains its run directory. The unchanged archives are under `documentation/consolidation/step2/archive/`.

Set `PGM_REVIEW_ROOT` to the repository root and `PGM_AUDIT_DATA_ROOT` to `<data>`, then run `audit_raw.py`. It reads original result/receipt/launch files and committed model inputs; it executes no solver. Its output JSON is written beside the script. Keep that recomputation separate from the archived review output if using a newer code revision.

Native artifact and archive identity results are separately recorded in NATIVE_ARTIFACT_CHECK.json and ARCHIVES.json. The script performs the raw probability/contract/receipt/launch/completion/consistency audit; it does not rebuild native artifacts or recompute unknown exact marginals.
