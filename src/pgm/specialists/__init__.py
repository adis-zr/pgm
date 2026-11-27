"""Retained specialists with EXPLICIT entrypoints (never selected automatically for a UAI request):

* ``cqr`` -- the general finite query / normalizer language (bounded rational expectation and ratio query tables,
  singleton / joint / parity / conditional constructors) with its own checked certificates.  Checkout-only: the
  ``code/cex/cqr`` package uses bare sibling imports and is reached through the isolated specialist bridge.
* ``cbi`` -- native coupled binary blocks (supplied product-kernel block representation); ``solve`` + ``verify``.
* ``sf``  -- the sparse / Fourier two-block bridge (supplied sparse two-block law); selector + independent checker.
* ``h4a`` -- the H4 arithmetic / signed-mode cohort (fixed arithmetic nodes, native producer / checker kernels built
  on the host); reference-only.

The registry (``pgm.registry``) records each as ``specialist`` / ``reference`` with its admission condition.
"""
