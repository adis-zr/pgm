"""Memory-mapped phase/weight cache with a frozen portable exact encoding (addendum §5).

Encoding, frozen:
  * point values  -> binary64 BIT PATTERNS (8 bytes, big-endian), never a decimal or text round trip;
  * interval endpoints -> explicit signed integer MANTISSA + int32 EXPONENT, value = mantissa * 2^exponent exactly.
    C's bounds are never serialized through binary64 and never as raw pointer-bearing MPFR structs.

Layout:  MAGIC | version | kind | n | F | identity(32B sha256) | payload
Every load validates magic, version, kind, dimensions, identity and payload length, and rejects malformed endpoint
order. An identity header alone does not establish faithful numerical encoding, so `verify_round_trip` re-reads every
stored value and compares it exactly against the source."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import hashlib, struct, mmap, os
from fractions import Fraction as Fr

MAGIC = b"H4QCACHE"
VERSION = 1
KIND_POINT = 1          # binary64 bit patterns
KIND_INTERVAL = 2       # mantissa/exponent pairs
MANT_BYTES = 48         # signed big-endian mantissa field, ample for 320-bit significands
HEADER = struct.Struct(">8sHHii32s")


class CacheError(Exception):
    """malformed cache: magic, version, kind, dimensions, identity, length or endpoint order"""


def _enc_f64(x: float) -> bytes:
    return struct.pack(">d", x)

def _dec_f64(b: bytes) -> float:
    return struct.unpack(">d", b)[0]

def _enc_dyadic(v: Fr) -> bytes:
    """exact: v = mantissa * 2^exponent with an integer mantissa"""
    if v == 0: return (0).to_bytes(MANT_BYTES, "big", signed=True) + struct.pack(">i", 0)
    num, den = v.numerator, v.denominator
    if den & (den - 1) != 0: raise CacheError(f"endpoint {v} is not dyadic; the frozen encoding requires mantissa*2^e")
    e = -(den.bit_length() - 1)
    while num % 2 == 0 and num != 0: num //= 2; e += 1
    try: mb = int(num).to_bytes(MANT_BYTES, "big", signed=True)
    except OverflowError: raise CacheError(f"mantissa for {v} exceeds the frozen {MANT_BYTES}-byte field")
    return mb + struct.pack(">i", e)

def _dec_dyadic(b: bytes) -> Fr:
    m = int.from_bytes(b[:MANT_BYTES], "big", signed=True); e = struct.unpack(">i", b[MANT_BYTES:])[0]
    return Fr(m) * (Fr(2) ** e)

EP_BYTES = MANT_BYTES + 4


def identity(model_hash: str, n: int, F: int, prec: int, policy: str, kind: int) -> bytes:
    return hashlib.sha256("|".join([model_hash, str(n), str(F), str(prec), policy, str(kind)]).encode()).digest()


def write_point_cache(path, values, n, F, ident: bytes):
    """values: flat sequence of floats (re,im interleaved)"""
    body = b"".join(_enc_f64(v) for v in values)
    with open(path, "wb") as f:
        f.write(HEADER.pack(MAGIC, VERSION, KIND_POINT, n, F, ident)); f.write(body)
        f.flush(); os.fsync(f.fileno())
    return len(body) + HEADER.size


def write_interval_cache(path, endpoints, n, F, ident: bytes):
    """endpoints: flat sequence of exact Fractions (re_lo,re_hi,im_lo,im_hi per entry)"""
    for i in range(0, len(endpoints), 2):
        if endpoints[i] > endpoints[i + 1]:
            raise CacheError(f"malformed endpoint order at pair {i//2}: [{endpoints[i]},{endpoints[i+1]}]")
    body = b"".join(_enc_dyadic(v) for v in endpoints)
    with open(path, "wb") as f:
        f.write(HEADER.pack(MAGIC, VERSION, KIND_INTERVAL, n, F, ident)); f.write(body)
        f.flush(); os.fsync(f.fileno())
    return len(body) + HEADER.size


def open_cache(path, expect_kind, expect_n, expect_F, expect_ident: bytes):
    """memory-map and validate; returns (mmap, count). Raises CacheError on any mismatch."""
    size = os.path.getsize(path)
    if size < HEADER.size: raise CacheError("truncated: smaller than the header")
    f = open(path, "rb"); mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    magic, ver, kind, n, F, ident = HEADER.unpack(mm[:HEADER.size])
    if magic != MAGIC: raise CacheError(f"bad magic {magic!r}")
    if ver != VERSION: raise CacheError(f"unsupported version {ver}")
    if kind != expect_kind: raise CacheError(f"wrong kind {kind}, expected {expect_kind}")
    if (n, F) != (expect_n, expect_F): raise CacheError(f"wrong dimensions ({n},{F}), expected ({expect_n},{expect_F})")
    if ident != expect_ident: raise CacheError("cache identity mismatch")
    stride = 8 if kind == KIND_POINT else EP_BYTES
    payload = size - HEADER.size
    if payload % stride: raise CacheError(f"payload {payload} is not a whole number of {stride}-byte entries (truncation)")
    return mm, payload // stride


def read_point(mm, i) -> float:
    off = HEADER.size + 8 * i; return _dec_f64(mm[off:off + 8])

def read_endpoint(mm, i) -> Fr:
    off = HEADER.size + EP_BYTES * i; return _dec_dyadic(mm[off:off + EP_BYTES])


def verify_round_trip(path, kind, n, F, ident, source):
    """re-read every stored value and compare exactly against the source. An identity header alone proves nothing
    about faithfulness, so this is mandatory before a cache is used."""
    mm, count = open_cache(path, kind, n, F, ident)
    try:
        if count != len(source): raise CacheError(f"entry count {count} != source {len(source)}")
        rd = read_point if kind == KIND_POINT else read_endpoint
        for i, want in enumerate(source):
            got = rd(mm, i)
            if kind == KIND_POINT:
                if struct.pack(">d", got) != struct.pack(">d", want):
                    raise CacheError(f"point bit pattern differs at {i}")
            else:
                if got != want: raise CacheError(f"exact endpoint differs at {i}: {got} != {want}")
        return {"entries": count, "bytes": os.path.getsize(path), "exact_round_trip": True}
    finally:
        mm.close()
