"""Lexical inspection keeps its exact grammar and admission at the fast paths."""
from fractions import Fraction
import math

import pytest

from pgm.planning.features import PlanningRefused, _Context, _number


@pytest.mark.parametrize("token,bits", [
    (b"0", 8), (b"1", 8), (b"0000", 20), (b"0001", 20),
    (b"+1", 8), (b"-0", 8), (b"-000", 16),
    (b".5", 12), (b"1.", 8), (b"1.000", 32), (b"01.0", 20),
    (b"-.000", 28), (b"+.000", 28),
    (b"1e-3", 20), (b"1E+3", 20), (b"1e+0000", 8),
    (b"0e-100", 408), (b"1/2", 8), (b"-1/-2", 8),
    (b"-0/-0002", 8), (b"000123/00000456", 24),
])
def test_numeric_fast_paths_preserve_exact_zero_and_payload(token, bits):
    zero, observed_bits = _number(token, _Context(math.inf, 1 << 30))
    value = (Fraction(*(int(part) for part in token.split(b"/")))
             if b"/" in token else Fraction(token.decode("ascii")))
    assert zero == (value == 0)
    assert observed_bits == bits


@pytest.mark.parametrize("token", [
    b"", b" ", b"1 2", b"++1", b"--0", b"+-0", b"1..0", b".",
    b"1_000", b"0x1", b"NaN", b"inf", b"1e", b"1e+", b"1e-",
    b"1/0", b"0/000", b"1//2", b"1/2/3", b"1/2.0",
    b"-1", b"-0.01", b"-1E-10", b"1/-2", b"-1/2", b"\xb2",
])
def test_numeric_fast_paths_do_not_widen_the_input_language(token):
    with pytest.raises(PlanningRefused) as exc:
        _number(token, _Context(math.inf, 1 << 30))
    assert exc.value.kind == "INVALID_TASK"


@pytest.mark.parametrize("prefix", [b"", b"+"])
def test_integer_fast_path_enforces_the_same_exact_admission_boundary(prefix):
    # cap / 16 = 128 bits, equal to the floor used by the lexical inspector.
    context = _Context(math.inf, 2048)
    assert _number(prefix + b"1" * 31, context) == (False, 128)
    with pytest.raises(PlanningRefused) as exc:
        _number(prefix + b"1" * 32, context)
    assert exc.value.kind == "BITS"
