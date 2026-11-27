"""Shared adapter context (explicit inputs, no module globals) and the cooperative memory ceiling policy."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F
import time

from ..validation.publication import AdapterRefused


@dataclass(frozen=True)
class AdapterContext:
    deadline: float          # absolute monotonic attempt deadline (set by the controller; never reset here)
    epsilon: F
    delta: F                 # this attempt's prospective PAC allowance (the policy's share; zero when not PAC)
    seed: int
    memory_bytes: int
    mode: str                # auto | deterministic | exact (the permitted guarantee)
    structural_route: str = "auto"
    configuration: dict | None = None
    policy: str | None = None

    def remaining(self) -> float:
        return remaining(self.deadline)


def remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AdapterRefused("DEADLINE", "absolute attempt deadline reached")
    return remaining


def memory_policy(module, memory_bytes: int) -> None:
    """Only lower declared backend ceilings; never increase an inherited cap."""
    headroom = getattr(module, "PROCESS_HEADROOM_BYTES", 160 << 20)
    usable = max(0, memory_bytes - headroom)
    for name in ("USABLE_BYTES",):
        if hasattr(module, name):
            setattr(module, name, min(getattr(module, name), usable))
    if hasattr(module, "CEX_CAP_BYTES"):
        module.CEX_CAP_BYTES = min(module.CEX_CAP_BYTES, memory_bytes)
    if hasattr(module, "CONSTRUCTOR_BYTES"):
        module.CONSTRUCTOR_BYTES = min(module.CONSTRUCTOR_BYTES, usable)
