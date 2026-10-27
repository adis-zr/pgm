// dqcommon.hpp — progress/timing helpers shared by the two binaries (not numerical code).
#pragma once
#include <sys/resource.h>
#include <time.h>
#include <cstdio>
#include <string>
static double mono_now() { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec + ts.tv_nsec * 1e-9; }
static double cpu_now() { struct rusage ru; getrusage(RUSAGE_SELF, &ru); return ru.ru_utime.tv_sec + ru.ru_utime.tv_usec * 1e-6 + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec * 1e-6; }
struct Progress {
  FILE* f = nullptr; double t0 = 0;
  void open(const char* p) { f = fopen(p, "a"); t0 = mono_now(); }
  void line(const char* phase, long site, long pass, long passes_total, long iter, long freq, const char* last) {
    if (!f) return; fprintf(f, "PROG t=%.3f cpu=%.3f phase=%s site=%ld pass=%ld/%ld iter=%ld freq=%ld last=%s\n", mono_now() - t0, cpu_now(), phase, site, pass, passes_total, iter, freq, last ? last : "-"); fflush(f);
  }
  void close() { if (f) fclose(f); f = nullptr; }
};
struct PhaseTimer { double w0, c0; std::string name; PhaseTimer(const std::string& n) : w0(mono_now()), c0(cpu_now()), name(n) {} double wall() const { return mono_now() - w0; } double cpu() const { return cpu_now() - c0; } };
