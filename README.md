# inference-research-theory — the prose counterpart to the lab

This directory holds the prose-only research handoff (theory ledger, empirical ledger, graveyard, hypotheses, reproduction
specifications, complete proof notes, first-party reports). It is the research record; the executable lab and its raw evidence live in
the sibling directories below. Nothing here is code to run.

## Layout

- `current/` — the latest handoff, extracted (browse/grep here; start with `current/README.md` and `current/START_NEW_CHAT.md`).
- `archives/` — the original ZIP bytes of every handoff version received, named by version. Never edited.
- Future handoff versions: copy the ZIP into `archives/`, re-extract into `current/`, commit. `git diff` then shows what changed between versions.

## Current version

| | |
|---|---|
| Version | 5.2 (26 October 2026, Pacific) — "refreshed after reconciling two AI reviews of the next research step" |
| Source file | `~/Downloads/inference-research-handoff-2026-10-26.zip` (received 16:37 PDT) |
| Archived copy | `archives/inference-research-handoff-2026-10-26-v5.2.zip`, 1,044,412 bytes |
| SHA-256 | `237babe7042184d5d49f42ce58340d06dc8ddc7c912989bbe1da27c70aac708b` |
| Contents | 188 files (Markdown/plain text only); `current/CHECKSUMS.txt` verified 187/187 on storage |

## The lab this record describes (same machine, `~/Workspace`)

| Item | Identity |
|---|---|
| `strongcompact` (main repo, branch main) | commit b41e278 — code (`sc/`), ledgers (REPORT_NOTES, THEORY_GAPS, GRAVEYARD_DELTA, DEVLOG), runs/ (run1, probes, fourier1–3, audit1–2) |
| `strongcompact-bench` (worktree, branch benchmark/h4-external-v1) | commit c03ee35 — external benchmark + closeout evidence (`runs/h4_external_v1`) |
| `strongcompact-pilot` (worktree, branch pilot/h4-centering-v1) | commit 1eec516 — centering pilot code + evidence (`runs/h4_centering_v1`) |
| `strongcompact-h4-closeout-2026-10-26.zip` | 251,682,120 bytes, 3,062 files, SHA-256 `7b4aea9e1db4cf77e63ccb8021da5a7f75cf70d4ec7a2604f93ca85b5ffe9266` |
| `strongcompact-h4-centering-pilot-2026-10-26-r3.zip` | 93,794,916 bytes, 472 files, SHA-256 `26a836978b35365f5b16ddd940ef192aa10655b6b3e4cdb47e3ccdc3c213b40a` |

Earlier archives (run1 handoff, external-v1 handoff, pilot r1/r2, pgm backup tarballs) and the frozen prior-phase repos (pgm, qgrid) were
deleted on 26 October 2026 after confirming their evidence is contained in the two archives above or preserved as prose in
`current/historical/v4`. Later the same evening, at the user's direction, the three strongcompact repositories and both evidence archives
were deleted as well: the prose record (this directory) is the research record going forward. The identities above are kept so that any
copy that resurfaces can be recognised; none exists on this machine.

## Lab reports bundle (added 26 Oct 2026, evening)

`lab-reports-2026-10-26/` (and `archives/lab-reports-2026-10-26.zip`) holds byte-for-byte copies of every result report, ledger, manifest, source
lock, results table and accounting record from the lab, exported before the lab was deleted; `lab-reports-2026-10-26/INDEX.md` lists each
file with repo, commit, bytes and SHA-256, and records the identities of the two deleted evidence archives. It answers the handoff's
`current/reports/REQUEST_MISSING_REPORTS.md`.

## Open item recorded by the handoff

`current/reports/REQUEST_MISSING_REPORTS.md` asks for a reports-only bundle of the final closeout, audit and main-repo ledger prose. Those
files are all present in the lab (bench `runs/h4_external_v1/closeout/`, main `runs/audit2/`, main-repo ledgers at b41e278) and can be
exported without running anything.
