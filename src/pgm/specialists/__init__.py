"""Retained specialists with EXPLICIT entrypoints (never selected automatically for a UAI request):

* ``cqr`` -- the general finite query / normalizer language (bounded rational expectation and ratio query tables,
  singleton / joint / parity / conditional constructors) with its own checked certificates.
* ``cbi`` -- native coupled binary blocks (supplied product-kernel block representation); ``solve`` + ``verify``.
* ``sf``  -- the sparse / Fourier two-block bridge (supplied sparse two-block law); selector + independent checker.
* ``h4a`` -- the H4 arithmetic / signed-mode cohort (fixed arithmetic nodes, native producer / checker kernels built
  on the host); reference-only.

The registry (``pgm.registry``) records each as ``specialist`` / ``reference`` with its admission condition.
All implementations ship under ``pgm.algorithms`` and are also reachable through ``pgm.method(name)``.
"""
