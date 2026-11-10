# pgm — certified inference research

Two parts:

- `docs/` — the research record (prose only). This is the authoritative statement of what was established, what failed, and what is open.
  - `docs/handoff/` — the prose-only research handoff, version 5.2 (26 Oct 2026). Start at `docs/handoff/README.md` and
    `docs/handoff/START_NEW_CHAT.md`; ledgers: THEORY_LEDGER, EMPIRICAL_LEDGER, GRAVEYARD, HYPOTHESES_AND_RESEARCH_IDEAS, NEXT_DECISION;
    complete proof notes under `historical/v4` and `theory/extension-2026-10-25`; frozen experiment specifications under `reproduction/`.
  - `docs/lab-reports/` — byte-for-byte copies (183 files, with `INDEX.md` giving repo, commit, bytes, SHA-256) of every result report,
    closeout/audit document, ledger, manifest, source lock, results table and accounting record produced by the H4 lab (run1 → external
    benchmark → moment audit → closeout → centering pilot). This answers the handoff's `reports/REQUEST_MISSING_REPORTS.md`.
- `docs/prose-handoff-2026-11-09/` — the overseer's prose-only research handoff of 9 Nov 2026 (`INFERENCE_RESEARCH_PROSE_HANDOFF_2026-11-09.zip`,
  SHA-256 `033c9e8810e8b4de4d7bca11ad8cc93d705f7b482db8bf4119f7f90fbe8f4a4d`, 1,123,565 bytes; `PACKAGE_MANIFEST.txt` verifies 101/101). A different
  series from `docs/handoff/` (not extracted over it). Start at `00_START_HERE.txt`; `README_REPO_NOTE.md` (local) records what the packet predates:
  the BIDI native pilot result (E-MDI-40), GENERAL_BIDI_V1 (paused at cell 219) and the GENERAL_BIDI_V2 repair, all recorded under `code/runs/`.
- `docs/LEDGER_ADDITIONS_*.md` — append-only empirical ledger entries; the running MDI ledger is `LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md`
  (E-MDI-02 … E-MDI-40 and corrections).
- `code/` — the direct chain-query certificate pilot (26 Oct 2026): `code/README.md`, `code/dq/`, `code/native/`, `code/tests/`, and the
  durable campaign records under `code/runs/dq_pilot_2026-10-26/` (REPORT.md leads with the decision). The earlier `strongcompact`
  implementation was deleted on 26 Oct 2026 and exists only as prose in `docs/`.
- `docs/normalization-free-diagnostic-v1/` — the frozen spec packet for the normalization-free certificate clearance diagnostic (26/27 Oct 2026; code under
  `code/nf/`, records under `code/runs/nf_diag_2026-10-26/`, ledger entry `docs/LEDGER_ADDITIONS_nf_diagnostic_2026-10-26.md`: OLD_CHEAP_ALREADY_SUFFICIENT).
- `docs/direct-query-theory-pass-2026-10-26/` — the theory pass packet that specified the pilot (proofs, witness, Fourier baseline, frozen spec);
  `docs/LEDGER_ADDITIONS_direct_query_pilot_2026-10-26.md` — the pilot's scoped empirical entry (E-DQ-01).

Procedure for a new handoff version: re-extract it over `docs/handoff/`, verify its `CHECKSUMS.txt`, record the ZIP's SHA-256 in the commit
message, commit; `git diff` then shows what changed between versions.

Identities for the record: handoff v5.2 ZIP SHA-256 `237babe7042184d5d49f42ce58340d06dc8ddc7c912989bbe1da27c70aac708b` (1,044,412 bytes);
the extracted tree's own `CHECKSUMS.txt` verifies 187/187 files.
