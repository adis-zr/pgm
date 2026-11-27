"""The supported request and result contract, independent of solver modules."""
from __future__ import annotations
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class InferenceRequest:
    model: str | Path
    budget: float = 20.0
    memory_mib: int = 3072
    epsilon: Fraction | str = "1/200"
    delta: Fraction | str = "1/1000000"
    seed: int = 1
    mode: str = "auto"
    queries: Sequence[tuple[int, int]] | None = None
    policy: str = "accepted"

    def __post_init__(self):
        object.__setattr__(self, "model", Path(self.model).expanduser().resolve())
        object.__setattr__(self, "epsilon", Fraction(self.epsilon))
        object.__setattr__(self, "delta", Fraction(self.delta))
        if not math.isfinite(self.budget) or self.budget <= 0:
            raise ValueError("budget must be positive and finite")
        if type(self.memory_mib) is not int or self.memory_mib <= 0:
            raise ValueError("memory_mib must be a positive integer")
        if not 0 < self.epsilon <= 1 or not 0 <= self.delta < 1:
            raise ValueError("epsilon must be in (0,1] and delta in [0,1)")
        if self.mode not in {"auto", "exact", "deterministic"}:
            raise ValueError("mode must be auto, exact, or deterministic")
        if self.policy not in {"accepted", "experimental"}:
            raise ValueError("policy must be accepted or experimental")
        if self.mode == "auto" and self.delta == 0:
            object.__setattr__(self, "mode", "deterministic")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        if self.queries is not None:
            queries = tuple(tuple(q) for q in self.queries)
            if any(len(q) != 2 or any(type(x) is not int for x in q) for q in queries):
                raise ValueError("queries must be (variable, state) integer pairs")
            if len(set(queries)) != len(queries):
                raise ValueError("duplicate queries")
            object.__setattr__(self, "queries", queries)


@dataclass(frozen=True)
class InferenceResult:
    """A result whose published coordinates satisfy the requested contract.

    Fractions are serialized as strings; exact labels never mean merely that an
    exact algorithm was used.  `complete` concerns the requested coordinates.
    The API currently accepts UAI files and singleton-coordinate queries.
    ``policy`` / ``policy_version`` record the public scheduling policy that
    produced the result (separately from the guarantee ``mode``).
    """
    data: Mapping[str, Any] = field(repr=False)

    @property
    def complete(self) -> bool:
        return self.data["outcome"] == "COMPLETE"

    @property
    def outcome(self) -> str:
        return self.data["outcome"]

    @property
    def guarantee(self) -> str:
        return self.data["guarantee"]

    @property
    def policy(self) -> str:
        return self.data["policy"]

    @property
    def answers(self) -> tuple[dict, ...]:
        return tuple(dict(r) for r in self.data["answers"])

    def to_dict(self) -> dict:
        import copy
        return copy.deepcopy(dict(self.data))

    def probability(self, variable: int, state: int) -> Fraction:
        for row in self.data["answers"]:
            if row["variable"] == variable and row["state"] == state:
                if row["guarantee"] == "NOT_PUBLISHED":
                    raise ValueError("requested coordinate has not been certified")
                return Fraction(row["point"])
        raise KeyError((variable, state))
