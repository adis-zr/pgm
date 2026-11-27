"""Every native constructor allocation may fail without a crash or orphan."""
import ctypes as C
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "code/cex/hp/heatbath_native.c"


def build_failure_library(source, folder):
    """Interpose only this translation unit's allocator; sampling is not timed."""
    wrapper = Path(folder) / "allocation_failure.c"
    library = Path(folder) / "allocation_failure.so"
    wrapper.write_text(r'''
#include <stdlib.h>
static long calls = 0, failure = 0, live = 0;
static void *test_malloc(size_t n) {
    calls++;
    if (calls == failure) return NULL;
    void *p = malloc(n); if (p) live++; return p;
}
static void *test_calloc(size_t n, size_t s) {
    calls++;
    if (calls == failure) return NULL;
    void *p = calloc(n, s); if (p) live++; return p;
}
static void test_free(void *p) { if (p) live--; free(p); }
void allocation_fail_at(long n) { calls = 0; failure = n; }
long allocation_calls(void) { return calls; }
long allocation_live(void) { return live; }
#define malloc test_malloc
#define calloc test_calloc
#define free test_free
#include ''' + json.dumps(str(Path(source).resolve())) + "\n")
    # This tests allocation control flow, not the floating-point inference
    # certificate. Production native qualification retains its strict flags.
    subprocess.run([shutil.which("cc"), "-std=c11", "-O0", "-fPIC", "-shared",
                    str(wrapper), "-o", str(library), "-lm"], check=True,
                   capture_output=True, text=True, timeout=30)
    lib = C.CDLL(str(library))
    I = C.POINTER(C.c_int); D = C.POINTER(C.c_double); L = C.POINTER(C.c_longlong)
    lib.hb_create.argtypes = [C.c_int, I, D, C.c_int, I, I, D, L, C.c_uint64]
    lib.hb_create.restype = C.c_void_p
    lib.hb_free.argtypes = [C.c_void_p]
    lib.hb_observer_setup.argtypes = [C.c_void_p, C.c_int, I, C.POINTER(C.c_uint32), C.c_int, L]
    lib.hb_observer_setup.restype = C.c_int
    for name in ("allocation_calls", "allocation_live"):
        getattr(lib, name).restype = C.c_long
    lib.allocation_fail_at.argtypes = [C.c_long]
    return lib


def create(lib):
    return lib.hb_create(2, (C.c_int * 2)(2, 2), (C.c_double * 4)(1, 1, 1, 1),
                         1, (C.c_int * 1)(0), (C.c_int * 1)(1),
                         (C.c_double * 4)(1, 1, 1, 1), (C.c_longlong * 2)(0, 4), 1)


def observe(lib, context):
    return lib.hb_observer_setup(context, 2, (C.c_int * 2)(0, 1),
                                (C.c_uint32 * 2)(1 << 31, 1 << 31),
                                2, (C.c_longlong * 2)(1, 2))


@unittest.skipUnless(shutil.which("cc"), "C compiler required for allocator failure controls")
class NativeAllocationFailureTests(unittest.TestCase):
    def test_every_context_and_observer_allocation_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            lib = build_failure_library(SOURCE, td)
            lib.allocation_fail_at(0)
            context = create(lib)
            self.assertTrue(context)
            create_count = lib.allocation_calls()
            lib.hb_free(context)
            self.assertEqual(lib.allocation_live(), 0)
            self.assertGreater(create_count, 10)
            for ordinal in range(1, create_count + 1):
                with self.subTest(constructor="context", ordinal=ordinal):
                    lib.allocation_fail_at(ordinal)
                    context = create(lib)
                    if context:
                        lib.hb_free(context)
                    self.assertFalse(context)
                    self.assertEqual(lib.allocation_live(), 0)

            lib.allocation_fail_at(0)
            context = create(lib)
            lib.allocation_fail_at(0)
            self.assertEqual(observe(lib, context), 4)
            observer_count = lib.allocation_calls()
            lib.hb_free(context)
            self.assertEqual(lib.allocation_live(), 0)
            self.assertGreater(observer_count, 10)
            for ordinal in range(1, observer_count + 1):
                with self.subTest(constructor="observer", ordinal=ordinal):
                    lib.allocation_fail_at(0)
                    context = create(lib)
                    baseline = lib.allocation_live()
                    lib.allocation_fail_at(ordinal)
                    self.assertEqual(observe(lib, context), -4)
                    self.assertEqual(lib.allocation_live(), baseline)
                    # An allocation failure must leave the context reusable.
                    lib.allocation_fail_at(0)
                    self.assertEqual(observe(lib, context), 4)
                    lib.hb_free(context)
                    self.assertEqual(lib.allocation_live(), 0)


if __name__ == "__main__":
    unittest.main()
