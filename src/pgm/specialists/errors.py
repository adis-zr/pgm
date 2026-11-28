"""Public specialist availability errors, independent of any repository layout."""


class SpecialistUnavailable(Exception):
    """A required optional resource is unavailable in this installation."""

    kind = "UNAVAILABLE"
