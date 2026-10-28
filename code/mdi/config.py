"""Frozen finite caps and error budget (spec sections 8 and 9).

ONE configuration file. Every cap is checked inside its loop and by the outer
supervisor. Any amendment must be recorded BEFORE external numerical runs.
"""
from __future__ import annotations
from fractions import Fraction as Fr

SPEC_SHA256 = "403c4db2bcba8545178d7cbb87a455618326724958a74c2e99d495e4987487cc"

# ---------------- section 9: frozen finite caps ----------------
CAPS = {
    "coarsening_levels": 2,
    "partition_proposals_per_level": 4,
    "region_tuple_assignments": 4096,          # assignments in one region/parent tuple space
    "profile_entry_comparisons": 2_000_000,    # per model, across proposals
    "rational_bit_length": 65_536,             # numerator and denominator each
    "local_mass_entries": 1_000_000,           # retained across a plan
    "feature_contrast_dim": 1024,
    "residual_masks": 3,
    "fits_per_mask": 2,
    "mode_rank_total": 4,
    "mode_rank_positive": 2,
    "mode_rank_negative": 2,
    "mode_fit_iterations": 50,                 # per fit
    "discovery_wall_s": 30.0,                  # per external arm, inside arm budget
    "local_check_wall_s": 30.0,                # per external arm, inside arm budget
    "deletion_prefix_tests": 8,                # geometrically spaced prefix sizes
    "dyadic_Q_tries": 3,                       # statistic rounding denominators

    # Contract F.7, as amended by review 4: the 4,096 region-assignment cap is
    # 4,096. Renaming 262,144 is not restoration, so every derived space is now
    # tied to that figure and any genuinely larger need must be an explicit
    # overseer amendment recorded in AMENDMENTS below.
    "region_local_enumeration": 4_096,         # boundary x interior, one region
    "aggregated_kernel_entries": 4_096,        # one product kernel
    "level2_contraction_space": 4_096,         # parent boundary product
    "checker_contraction_space": 4_096,        # independent reduced contraction
}

# Any cap change must be listed here with its reason, so a silent enlargement is
# impossible. An empty list means every cap is at its specified value.
AMENDMENTS = []

# ---------------- section 13: resource contract ----------------
RESOURCES = {
    "arm_wall_s": 600.0,            # complete wall time per arm
    "arm_rss_bytes": 8 * (1 << 30), # process-tree RSS per arm
    "threads": 6,                   # same limit across arms
    "total_numerical_s": 7200.0,    # all validation + capability + repair + replay
    "controls_s": 1200.0,           # at most, inside the total
    "repair_attempts": 1,
}

# ---------------- section 8: error allocation ----------------
MAX_WIDTH = Fr(1, 100)              # 0.01 final width per requested state

RADII = {
    "regional_coarsening_total": Fr(2, 1000),      # 0.002, both levels together
    "state_deletion_total": Fr(5, 10000),          # 0.0005, all levels together
    "collective_fit_and_rounding": Fr(5, 10000),   # 0.0005, if used
    "gaussian_quadrature": Fr(5, 10000),           # 0.0005, if used
}
PUBLICATION_RESERVE = Fr(2, 1_000_000)             # >= 2e-6 reserved for publication/checking

# Worst allowed analytic allocation, for the forecast in section 8.
ANALYTIC_WORST = sum(RADII.values())               # 0.0035
# Width consumed by outward expansion is 2*d.
NUMERICAL_BUDGET_WORST = MAX_WIDTH - 2 * ANALYTIC_WORST - PUBLICATION_RESERVE


def level_radius(levels_used: int) -> Fr:
    """Split the two-level regional allowance EQUALLY before construction."""
    if levels_used <= 0:
        return Fr(0)
    return RADII["regional_coarsening_total"] / levels_used


def region_deletion_radius(n_regions: int, levels_used: int) -> Fr:
    """Split each level's deletion allowance equally across its regions."""
    if n_regions <= 0 or levels_used <= 0:
        return Fr(0)
    return RADII["state_deletion_total"] / (levels_used * n_regions)


def region_distortion_budget(t_level: Fr, k_regions: int) -> Fr:
    """Spec 5.4: B_R = 1 + 4t/k, whose product over k regions is at most
    exp(4t) <= ((1+t)/(1-t))^2. Returns the PER-REGION rho cap."""
    if k_regions <= 0:
        return Fr(1)
    return Fr(1) + (Fr(4) * Fr(t_level)) / k_regions


def tv_radius_from_R(R: Fr) -> Fr:
    """t(R) = (sqrt(R)-1)/(sqrt(R)+1). Returned as an exact UPPER bound without
    computing a square root: we instead invert the certificate below."""
    raise NotImplementedError("use certify_R_against_t; no square root is needed")


def certify_R_against_t(R: Fr, t: Fr) -> bool:
    """Spec 5.4: certify an allocated rational radius t by the EXACT comparison
    R <= ((1+t)/(1-t))^2. No numerical logarithm or square root."""
    R = Fr(R); t = Fr(t)
    if t < 0 or t >= 1:
        return False
    if R < 1:
        R = Fr(1)
    lhs = R * (Fr(1) - t) ** 2
    rhs = (Fr(1) + t) ** 2
    return lhs <= rhs


def tanh_upper(nu: Fr) -> Fr:
    """An exact rational UPPER bound on tanh(nu/2), used for TV(P,P') <= tanh(nu/2).

    tanh(x) <= x for x >= 0, so tanh(nu/2) <= nu/2. That is the bound used; it
    is conservative and needs no transcendental evaluation.
    """
    nu = Fr(nu)
    if nu < 0:
        raise ValueError("nu must be nonnegative")
    return min(Fr(1), nu / 2)


BUDGET_SELF_CHECK = {
    "analytic_worst": ANALYTIC_WORST,
    "numerical_budget_worst": NUMERICAL_BUDGET_WORST,
}
