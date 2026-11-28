# H4 arithmetic campaign

These are the retained fixed-cohort experiment, reporting and qualification tools.
They do not participate in automatic UAI dispatch or ship in the production wheel.
The arithmetic implementation lives in `pgm.algorithms.h4`; its public specialist
facade remains `pgm.specialists.h4a`. The cold-bundle callable is retained there
for compatibility and requires an explicit packet and output directory.

Host setup is explicit:

```sh
python -m pgm.algorithms.h4.kernels
python -m research.campaigns.h4.run --packet /path/to/packet --run-dir /path/to/results
```

The three kernels require a C++17 compiler. `h4rect` also requires the GMP and
MPFR development headers and libraries. `CXX` selects the compiler; `CPATH` and
`LIBRARY_PATH` can point to externally installed dependencies. Strict floating
point flags remain fixed. Builds and checked records go to `PGM_NATIVE_CACHE/h4`
or the user's cache, never to the source tree. Historical pinned executables are
preserved under `research/archive/native/h4_binaries` and are never selected for
execution by the library.

The original arithmetic packet is still needed for the historical campaign.
The portable tiny migration check exercises all four kernel roles and all three
containment verifiers without that private packet:

```sh
PGM_TEST_H4_NATIVE=1 python -m pytest -q tests/test_h4_migration.py
```
