"""The retained inference implementations, one canonical owner per live algorithm:

* ``structural`` -- the structural dispatcher: pairwise forest (exact), source DAG, support contraction, binary
  bipartite stream; deterministic enclosures with coordinatewise epsilon-safe points (formerly ``code/cex/newarm``).
* ``block`` -- the accepted engine v2.13.2 (BlockRes): exact support closure, signed evidence expansion, layered
  contraction, ancestral responses, exact block route and the certified PAC residual stream (``code/cex/blockres``).
* ``quotient`` -- the unified PAC planner over checked quotients: identity / exact / approximate quotients, the coarse
  envelope family (grouped, residual MAX, lifted decoder), joint / global / residual proposals with proof-boundary
  checkers, the reservation transaction (``code/cex/hp`` quotient closure).
* ``response`` -- the spectrally admitted exact heat-bath chain with the Markov confidence certificate and the DGP10
  conditional-response observer / checked moment-mean certificate (``code/cex/hp`` response closure).

Arithmetic kernels, message ordering, update formulas, certificate formulas and frozen cost coefficients are unchanged
from the scored sources; only import statements were qualified and the native cache / build-record locations made explicit.
"""
