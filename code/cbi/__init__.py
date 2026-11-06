"""cbi -- coupled-block inference (branch cbi-library-2026-11-06).

A narrowly specified certified inference library for models made of BINARY BLOCK TABLES joined by the full-coordinate product kernel
K_r(x, y) = prod_j (1 + r x_j y_j) (the overseer's packet "INFERENCE: CENTRAL THEORY AND A USABLE IMPLEMENTATION PASS", 6 Nov 2026).
Public API: `cbi.api.solve(model, queries, requested_width, limits)` and `cbi.api.verify(model, result)`; CLI `python -m cbi.cli`.
Bit convention: coordinate j (0-based) <-> bit j of a block state's integer mask; bit set <-> x_j = +1."""
