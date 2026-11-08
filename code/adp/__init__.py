"""AGGREGATE_DP_V1 -- one lazy sum-product bucket-elimination program with source-certified response
cores, bounded memoization, a shared backward pass for every requested singleton marginal, and an
independent reduced-program checker (design packet AGGREGATE_DP_DESIGN_AND_EVIDENCE_2026-11-07,
algorithm_design/ALGORITHM_DECISION.txt). New code; accepted mdi/ pins are read-only and only
mdi.model (exact parsing / restriction) and mdi.arith (directed MPFR primitives) are reused."""
ARM = "AGGREGATE_DP_V1"
