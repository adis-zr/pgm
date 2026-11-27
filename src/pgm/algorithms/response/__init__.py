"""Spectral heat-bath with the Markov confidence certificate (``spectral_heatbath_run.solve_response``): checked spectral
witness (``spectral_witness``), exact rational chain (``heatbath_exact``) or the native exact-decision kernel
(``heatbath_native.c``, strict FP) admitted by an all-assignment range witness, predetermined checkpoints with summable
risks (``markov_certificate``), the DGP10 conditional-response observer with the checked population-moment / two-state
mean certificate (``response_certificate`` / ``checked_tilt``) and the accepted epsilon-safe J-box publication.
Guarantee: PAC on the full requested delta (beta delta/2, raw delta/4, moment delta/8, mean delta/8)."""
