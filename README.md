# pgm — certified inference research

Two parts:

- `docs/` — the research record (prose only). This is the authoritative statement of what was established, what failed, and what is open.
  - `docs/handoff/` — the prose-only research handoff, version 5.2 (26 Oct 2026). Start at `docs/handoff/README.md` and
    `docs/handoff/START_NEW_CHAT.md`; ledgers: THEORY_LEDGER, EMPIRICAL_LEDGER, GRAVEYARD, HYPOTHESES_AND_RESEARCH_IDEAS, NEXT_DECISION;
    complete proof notes under `historical/v4` and `theory/extension-2026-10-25`; frozen experiment specifications under `reproduction/`.
  - `docs/lab-reports/` — byte-for-byte copies (183 files, with `INDEX.md` giving repo, commit, bytes, SHA-256) of every result report,
    closeout/audit document, ledger, manifest, source lock, results table and accounting record produced by the H4 lab (run1 → external
    benchmark → moment audit → closeout → centering pilot). This answers the handoff's `reports/REQUEST_MISSING_REPORTS.md`.
  - `docs/archives/` — the original ZIP bytes of the handoff (v5.2) and of the lab-reports bundle, for identity checks.
- `code/` — empty. The previous implementation (the `strongcompact` repositories and their evidence archives) was deleted on 26 Oct 2026;
  any new implementation starts here, built from the specifications in `docs/`.

Procedure for a new handoff version: copy its ZIP into `docs/archives/`, re-extract into `docs/handoff/`, commit; `git diff` then shows what
changed between versions.
