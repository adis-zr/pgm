# validation/

`driver_probe.sh REPRODUCE.sh fail19|clean` — the stub-only control of the
reproduction driver: a fake interpreter whose 7/9-witness step exits 19 (and
whose matrix steps write nothing) must make the driver exit non-zero without
the readiness token; a clean stub whose matrix steps write a zero-failure
summary newer than the run marker must make it exit zero. No solver runs and no
external input is opened by this control.
