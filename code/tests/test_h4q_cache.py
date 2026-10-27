"""Cache encoding controls (addendum §5): exact round trips and rejection of wrong dimensions, truncation,
identity mismatch, malformed endpoint order and wrong kind."""
import sys, os, pathlib, struct, tempfile
HERE = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(HERE))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import pytest
from h4q.cache import (write_point_cache, write_interval_cache, open_cache, verify_round_trip, identity,
                       CacheError, KIND_POINT, KIND_INTERVAL, HEADER, MAGIC, EP_BYTES)

IDENT = identity("deadbeef", 128, 265, 256, "frozen-v1", KIND_INTERVAL)
IDENT_P = identity("deadbeef", 128, 265, 256, "frozen-v1", KIND_POINT)


def test_point_cache_exact_bit_pattern_round_trip():
    vals = [1.0, -0.0, 0.5, 2.0 ** -1074, 1.0 - 2.0 ** -53, 3.141592653589793]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.bin"); write_point_cache(p, vals, 128, 265, IDENT_P)
        r = verify_round_trip(p, KIND_POINT, 128, 265, IDENT_P, vals)
        assert r["exact_round_trip"] and r["entries"] == len(vals)


def test_interval_cache_exact_dyadic_round_trip():
    eps = [Fr(0), Fr(1), Fr(-3, 4), Fr(3, 4), Fr(1, 2 ** 300), Fr(5, 2 ** 300),
           Fr(-(2 ** 200), 2 ** 310), Fr(2 ** 200, 2 ** 310)]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.bin"); write_interval_cache(p, eps, 128, 265, IDENT)
        r = verify_round_trip(p, KIND_INTERVAL, 128, 265, IDENT, eps)
        assert r["exact_round_trip"] and r["entries"] == len(eps)


def test_rejects_malformed_endpoint_order():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(CacheError, match="malformed endpoint order"):
            write_interval_cache(os.path.join(d, "c.bin"), [Fr(1), Fr(0)], 128, 265, IDENT)


def test_rejects_non_dyadic_endpoint():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(CacheError, match="not dyadic"):
            write_interval_cache(os.path.join(d, "c.bin"), [Fr(0), Fr(1, 3)], 128, 265, IDENT)


def test_rejects_wrong_dimensions_identity_kind_and_truncation():
    eps = [Fr(0), Fr(1)]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.bin"); write_interval_cache(p, eps, 128, 265, IDENT)
        with pytest.raises(CacheError, match="wrong dimensions"):
            open_cache(p, KIND_INTERVAL, 64, 265, IDENT)
        with pytest.raises(CacheError, match="identity mismatch"):
            open_cache(p, KIND_INTERVAL, 128, 265, b"\x00" * 32)
        with pytest.raises(CacheError, match="wrong kind"):
            open_cache(p, KIND_POINT, 128, 265, IDENT)
        # truncate mid-entry
        with open(p, "r+b") as f: f.truncate(HEADER.size + EP_BYTES + 3)
        with pytest.raises(CacheError, match="truncation"):
            open_cache(p, KIND_INTERVAL, 128, 265, IDENT)


def test_rejects_bad_magic_and_version():
    eps = [Fr(0), Fr(1)]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.bin"); write_interval_cache(p, eps, 128, 265, IDENT)
        raw = bytearray(open(p, "rb").read())
        raw[:8] = b"XXXXXXXX"; open(p, "wb").write(bytes(raw))
        with pytest.raises(CacheError, match="bad magic"):
            open_cache(p, KIND_INTERVAL, 128, 265, IDENT)
        raw[:8] = MAGIC; raw[8:10] = (99).to_bytes(2, "big"); open(p, "wb").write(bytes(raw))
        with pytest.raises(CacheError, match="unsupported version"):
            open_cache(p, KIND_INTERVAL, 128, 265, IDENT)


def test_identity_binds_precision_and_model():
    a = identity("aa", 128, 265, 256, "frozen-v1", KIND_INTERVAL)
    assert a != identity("aa", 128, 265, 320, "frozen-v1", KIND_INTERVAL)   # precision
    assert a != identity("bb", 128, 265, 256, "frozen-v1", KIND_INTERVAL)   # model
    assert a != identity("aa", 128, 265, 256, "frozen-v1", KIND_POINT)      # kind/role


def test_round_trip_detects_a_corrupted_payload():
    """the identity header still matches; only the payload is altered"""
    eps = [Fr(1, 4), Fr(1, 2)]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.bin"); write_interval_cache(p, eps, 128, 265, IDENT)
        raw = bytearray(open(p, "rb").read())
        raw[HEADER.size + EP_BYTES - 5] ^= 0xFF          # flip a mantissa byte of the second endpoint
        open(p, "wb").write(bytes(raw))
        with pytest.raises(CacheError, match="exact endpoint differs"):
            verify_round_trip(p, KIND_INTERVAL, 128, 265, IDENT, eps)
