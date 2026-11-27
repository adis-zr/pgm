"""Common result geometry and final publication (``pgm.validation.publication``): backend result normalization
without strengthening any claim, late-commit suppression with staged payloads, the controller's per-row
acceptance and per-variable simplex feasibility of the assembled box."""
from .publication import (AdapterRefused, DETERMINISTIC_LABELS, PAC_LABELS, WALL_TOKEN, accepted_row, assemble,
                          empty_rows, normalize_result, suppressed, write_result)

__all__ = ["AdapterRefused", "DETERMINISTIC_LABELS", "PAC_LABELS", "WALL_TOKEN", "accepted_row", "assemble", "empty_rows",
           "normalize_result", "suppressed", "write_result"]
