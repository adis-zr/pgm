"""Unified PAC planner over checked quotients (``unified_pac_planner.UPlanner``): the coarse envelope (canonicalization,
LP envelope through the supervised ``lp_worker`` child, Budget / Clock / Refused), identity / exact / approximate
quotients and the certified residual stream, grouped and residual MAX envelopes, the lifted decoder, joint / global /
residual proposals with their proof-boundary checkers (``check_joint`` / ``check_global`` / ``check_residual``), the
reservation transaction and the frozen phase-rate cost models (``PHASE_RATES.json`` / ``PHASE_RATES_R1.json``).
Guarantee: PAC (DETERMINISTIC when the planner closes exactly) with simplex-feasible points."""
