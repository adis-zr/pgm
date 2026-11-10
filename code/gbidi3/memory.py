"""Python-side MEMORY LEDGER of GENERAL_BIDI_COMPLETE_V3 (brief §16): five internal categories (6 GiB total), every retained host-side object
reserved BEFORE it is built, documented byte proxies where exact allocator measurement is unavailable, and the remaining capacity of each category
handed to the native kernel as its caps. A category cap is a typed MEMORY_CATEGORY stop (MemoryStop), never a silent borrow.

  source_ir_maps_output   2 GiB   raw input bytes, parsed exact rationals, trusted copies, IR nodes, scopes / maps / decoders, flat handoff arrays,
                                   value strings handed to the kernel, planner metadata, output rows
  value_cache_blocks      2 GiB   kernel value blocks / sparse rows / LRU (kernel side)
  reverse_pinned          1 GiB   kernel numerators, root scratch, local tapes
  pending_adjoints      512 MiB   kernel pending AND active adjoint payloads
  frames_scratch_pub    512 MiB   kernel frames, conversion temporaries, export buffers; Python publication buffers and exact conversion temporaries

Proxies (documented; conservative for CPython 3.12 arm64): Fraction 128 B + 32 B per 64-bit limb of numerator and denominator beyond one; Python int
28 B + 4 B per 30-bit digit; tuple 40 B + 8 B per item; list 56 B + 8 B per slot; dict entry 104 B; str 49 B + 1 B per char; IR node 1,024 B + per-axis
/ per-child items; numpy int64 array 112 B + 8 B per element. These are RESERVATIONS against a ceiling, not measurements of RSS."""
from __future__ import annotations

GIB = 1 << 30; MIB = 1 << 20
RATIONAL_BYTES_FALLBACK = 160      # documented proxy per source entry during fallback preparation (sliced Fraction copy + integer + decimal string + list slots)
CATEGORIES = ("source_ir_maps_output", "value_cache_blocks", "reverse_pinned", "pending_adjoints", "frames_scratch_pub")
CAPS = {"source_ir_maps_output": 2 * GIB, "value_cache_blocks": 2 * GIB, "reverse_pinned": 1 * GIB, "pending_adjoints": 512 * MIB, "frames_scratch_pub": 512 * MIB}
KERNEL_ORDER = ("value_cache_blocks", "source_ir_maps_output", "reverse_pinned", "pending_adjoints", "frames_scratch_pub")   # caps5 order of kernel3: values, index, reverse, pending, scratch


class MemoryStop(Exception):
    def __init__(self, category, requested, used, cap, what):
        super().__init__("MEMORY_CATEGORY %s: %s needs %d bytes, %d used of %d" % (category, what, requested, used, cap)); self.category = category; self.requested = requested; self.used = used; self.cap = cap; self.what = what


def fraction_bytes(q):
    return 128 + 32 * ((q.numerator.bit_length() + 63) // 64 + (q.denominator.bit_length() + 63) // 64)


def int_bytes(n):
    return 28 + 4 * max(1, (int(n).bit_length() + 29) // 30)


class Ledger:
    __slots__ = ("caps", "used", "peak", "log")

    def __init__(self, caps=None):
        self.caps = dict(caps or CAPS); self.used = {c: 0 for c in self.caps}; self.peak = {c: 0 for c in self.caps}; self.log = []

    def reserve(self, category, nbytes, what):
        nbytes = int(nbytes); cap = self.caps[category]; u = self.used[category]
        if nbytes > cap or u > cap - nbytes:
            raise MemoryStop(category, nbytes, u, cap, what)
        self.used[category] = u + nbytes; self.peak[category] = max(self.peak[category], self.used[category]); self.log.append((category, nbytes, what)); return nbytes

    def release(self, category, nbytes):
        self.used[category] = max(0, self.used[category] - int(nbytes))

    def remaining(self, category):
        return max(0, self.caps[category] - self.used[category])

    def kernel_caps(self):
        """remaining capacity per category in kernel order (the kernel never sees what Python already holds)"""
        return [self.remaining(c) for c in KERNEL_ORDER]

    def report(self):
        return {"caps": dict(self.caps), "used": dict(self.used), "peak": dict(self.peak), "entries": len(self.log), "note": "host-side RESERVATIONS by documented proxies (not RSS); kernel categories are reported by the kernel"}


def model_bytes_estimate(m, data_len):
    """raw bytes + parsed Fractions + per-factor containers"""
    b = data_len + 64
    for f in m.factors:
        b += 56 + 8 * len(f.table) + 40 + 8 * len(f.scope) * 2 + 200
        for q in f.table:
            b += fraction_bytes(q)
    b += 56 + 8 * m.nvars + 28 * m.nvars
    return b
