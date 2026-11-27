#!/usr/bin/env python3
"""Frozen external suite for the public pgm API, with independent artifact checks."""

from __future__ import annotations
import argparse, hashlib, json, math, os, platform, subprocess, sys, time
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
ROOT = (
    Path(
        os.environ.get(
            "PGM_BENCH_RUN_DIR", REPO / "benchmark_runs" / "consolidation-v1"
        )
    )
    .expanduser()
    .resolve()
)
PY = Path(os.environ.get("PGM_BENCH_PY", sys.executable)).expanduser().absolute()
LIBDAI = (
    Path(os.environ.get("PGM_LIBDAI", REPO / "code/bench/libdai/libdai_mar"))
    .expanduser()
    .resolve()
)
REFERENCE = HERE / "reference/previous_accepted_cells.json"
EPS = F(1, 200)
GENERATED = {
    "code/cex/newarm/cex_build.json",
    "code/cex/newarm/stream_build.json",
    "code/cex/newarm/libcex_kernel.dylib",
    "code/cex/newarm/libstream_kernel.so",
}
HARNESS = [
    "run_suite.py",
    "strict_supervisor.py",
    "analyze_suite.py",
    "PROTOCOL.md",
    "README.md",
]


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def dump(p, v):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(v, indent=2, default=str) + "\n")


def host_files(warm=False):
    # Freeze the active ignored host build too; stale unused caches are irrelevant.
    active = ["code/cex/hp/heatbath_build.json"]
    record = REPO / active[0]
    if not record.is_file():
        raise RuntimeError("Build the heat-bath kernel during setup before freezing")
    heat = json.loads(record.read_text())
    if Path(heat["library"]).name != heat["library"]:
        raise ValueError("Invalid heat-bath library path")
    if heat["source_sha256"] != sha(REPO / "code/cex/hp/heatbath_native.c"):
        raise RuntimeError("Heat-bath build is stale")
    active.append("code/cex/hp/native_cache/" + heat["library"])
    if sha(REPO / active[-1]) != heat["binary_sha256"]:
        raise RuntimeError("Heat-bath binary identity mismatch")
    for record_name, source_name, binary_name, prefix, suffix in [
        ("cex_build.json", "cex_kernel.cpp", "libcex_kernel.dylib", "cex_", ".dylib"),
        (
            "stream_build.json",
            "stream_kernel.cpp",
            "libstream_kernel.so",
            "stream_",
            ".so",
        ),
    ]:
        base = REPO / "code/cex/newarm"
        d = json.loads((base / record_name).read_text())
        if d["source_sha256"] != sha(base / source_name) or d["binary_sha256"] != sha(
            base / binary_name
        ):
            raise RuntimeError("Native source/build identity mismatch: " + record_name)
        rel = "code/cex/newarm/native_cache/" + prefix + d["binary_sha256"] + suffix
        if warm and not (REPO / rel).exists():
            (REPO / rel).parent.mkdir(exist_ok=True)
            (REPO / rel).write_bytes((base / binary_name).read_bytes())
        if not (REPO / rel).is_file() or sha(REPO / rel) != d["binary_sha256"]:
            raise RuntimeError("Warm native cache before freezing: " + rel)
        active.append(rel)
    return active


def identity():
    files = subprocess.check_output(
        ["git", "ls-files"], cwd=REPO, text=True
    ).splitlines()
    paths = sorted(set(files + host_files()))
    return {p: sha(REPO / p) for p in paths if (REPO / p).is_file()}


def metadata(task):
    with open(task["model"]) as f:
        t = (s for line in f for s in line.split())
        next(t)
        n = int(next(t))
        cards = [int(next(t)) for _ in range(n)]
    ev = list(map(int, Path(task["evidence"]).read_text().split()))
    assert len(ev) == 1 + 2 * ev[0]
    evidence = dict(zip(ev[1::2], ev[2::2]))
    assert len(evidence) == ev[0]
    return cards, evidence


def check_pgm(path, task):
    d = json.loads(Path(path).read_text())
    cards, ev = metadata(task)
    expected = {(v, a) for v, k in enumerate(cards) if v not in ev for a in range(k)}
    seen = set()
    pubs = {}
    faults = []
    maxradius = F(0)
    maxwidth = F(0)
    for row in d.get("answers", []):
        key = (row.get("variable", row.get("var")), row.get("state"))
        if any(type(x) is not int for x in key):
            faults.append("noninteger coordinate identifier")
        if key in seen:
            faults.append("duplicate coordinate")
        seen.add(key)
        if key not in expected:
            faults.append("unexpected coordinate")
        if row.get("guarantee") in ("NOT_PUBLISHED", "NONE"):
            continue
        if row.get("guarantee") is None and all(
            row.get(k) is None for k in ("point", "lo", "hi")
        ):
            continue
        if row.get("guarantee") not in (
            "EXACT",
            "DETERMINISTIC",
            "DETERMINISTIC_RESIDUAL",
            "PAC",
            "PAC_EB",
            "PAC_MARKOV",
        ):
            faults.append("unknown row guarantee")
        try:
            lo, hi, point = (F(str(row[k])) for k in ("lo", "hi", "point"))
            radius = max(point - lo, hi - point)
            if not 0 <= lo <= point <= hi <= 1 or radius > EPS:
                faults.append("invalid probability geometry")
            if row.get("guarantee") == "EXACT" and not lo == point == hi:
                faults.append("nonpoint exact row")
            pubs[key] = (lo, hi, point)
            maxradius = max(maxradius, radius)
            maxwidth = max(maxwidth, hi - lo)
        except Exception as e:
            faults.append("invalid rational: " + repr(e))
    if seen != expected:
        faults.append("query inventory mismatch")
    if d.get("K") != len(expected) or d.get("published") != len(pubs):
        faults.append("reported counts mismatch")
    if pubs and d.get("positive_mass_witness") is not True:
        faults.append("missing positive mass witness")
    if len(pubs) == len(expected) and d.get("guarantee") not in (
        "EXACT",
        "DETERMINISTIC",
        "PAC",
    ):
        faults.append("unknown aggregate guarantee")
    binding = d.get("binding") or {}
    if (
        binding.get("model_sha256") != task["model_sha256"]
        or binding.get("evidence_sha256") != task["evidence_sha256"]
    ):
        faults.append("input binding mismatch")
    for v, k in enumerate(cards):
        if v in ev or not all((v, a) in pubs for a in range(k)):
            continue
        if (
            not sum(pubs[v, a][0] for a in range(k))
            <= 1
            <= sum(pubs[v, a][1] for a in range(k))
        ):
            faults.append("simplex enclosure mismatch")
    return dict(
        output_valid=not faults,
        validation_faults=sorted(set(faults)),
        solver_outcome=d.get("outcome"),
        guarantee=d.get("guarantee"),
        published=len(pubs),
        K=len(expected),
        all_queries_returned=not faults
        and len(pubs) == len(expected)
        and d.get("outcome") in ("COMPLETE", "EXACT"),
        max_published_radius=float(maxradius),
        max_published_width=float(maxwidth),
        backend=d.get("backend"),
        attempts=d.get("attempts"),
        solver_wall_s=d.get("wall_s"),
    )


def read_mar(path, task):
    cards, ev = metadata(task)
    t = iter(Path(path).read_text().split())
    if next(t) != "MAR" or int(next(t)) != len(cards):
        raise ValueError("MAR header")
    points = {}
    for v, k in enumerate(cards):
        if int(next(t)) != k:
            raise ValueError("MAR cardinality")
        row = [float(next(t)) for _ in range(k)]
        if (
            not all(math.isfinite(x) and 0 <= x <= 1 for x in row)
            or abs(sum(row) - 1) > 1e-7
        ):
            raise ValueError("MAR probability row")
        if v in ev and any(abs(x - int(a == ev[v])) > 1e-10 for a, x in enumerate(row)):
            raise ValueError("evidence mismatch")
        points.update({(v, a): x for a, x in enumerate(row)})
    if next(t, None) is not None:
        raise ValueError("MAR trailing data")
    return points


def check_libdai(folder, task):
    side = (
        json.loads((folder / "side.json").read_text())
        if (folder / "side.json").exists()
        else {}
    )
    points = read_mar(folder / "output.MAR", task)
    return dict(
        output_valid=True,
        validation_faults=[],
        solver_outcome="COMPLETE" if side.get("converged") else "COMPLETE_UNCONVERGED",
        guarantee="POINT_ONLY",
        all_queries_returned=True,
        converged=side.get("converged"),
        iterations=side.get("iterations"),
        maxdiff=side.get("maxdiff"),
        output_coordinates=len(points),
        solver_wall_s=(side.get("phases_s") or {}).get("total"),
    )


def tasks_from_manifest(path, key="tasks"):
    d = json.loads(Path(path).read_text())
    out = []
    for r in d[key]:
        t = dict(r)
        for k in ("model", "evidence"):
            t[k] = str((HERE / t[k]).resolve())
            t[k + "_relative"] = str(Path(t[k]).relative_to(REPO))
            assert sha(t[k]) == t[k + "_sha256"]
        out.append(t)
    return out


def relocate_frozen_tasks(frozen):
    """Resolve committed input paths for reading a run on another checkout."""
    for task in frozen["tasks"]:
        for key in ("model", "evidence"):
            relative = task.get(key + "_relative")
            if relative is not None:
                path = (REPO / relative).resolve()
                if not path.is_relative_to(REPO):
                    raise ValueError("Frozen input path escapes repository")
                task[key] = str(path)
    return frozen


def freeze():
    ROOT.mkdir(parents=True, exist_ok=True)
    assert not (
        ROOT / "FREEZE.json"
    ).exists(), "Freeze already exists; do not overwrite"
    assert LIBDAI.is_file() and os.access(
        LIBDAI, os.X_OK
    ), "Set PGM_LIBDAI to the qualified comparator executable"
    assert os.environ.get(
        "CC"
    ), "Set CC explicitly to the qualified native C compiler used at setup"
    host_files(warm=True)
    heat = json.loads((REPO / "code/cex/hp/heatbath_build.json").read_text())
    assert (
        heat["compiler"] == os.environ["CC"]
    ), "CC differs from the qualified heat-bath build"
    cex = json.loads((REPO / "code/cex/newarm/cex_build.json").read_text())
    changes = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO, text=True
    ).splitlines()
    assert all(
        row[3:] in GENERATED for row in changes
    ), "Commit source changes before freezing: " + repr(changes)
    assert (REPO / "src/pgm/__main__.py").is_file(), "Public pgm CLI not present"
    exposed = tasks_from_manifest(HERE / "INPUT_MANIFEST.json")
    heldout = tasks_from_manifest(HERE / "HOLDOUT_FREEZE.json")
    assert len(exposed) == 55 and all(
        t["split"] == "exposed_regression" for t in exposed
    )
    assert not {t["model_sha256"] for t in exposed} & {
        t["model_sha256"] for t in heldout
    }
    # Existing executable is qualified separately; this records its exact identity.
    frozen = {
        "schema": "CONSOLIDATION_EXTERNAL_V1",
        "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "engine_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "engine_files": identity(),
        "harness_files": {n: sha(HERE / n) for n in HARNESS},
        "input_manifests": {
            n: sha(HERE / n) for n in ("INPUT_MANIFEST.json", "HOLDOUT_FREEZE.json")
        },
        "libdai_sha256": sha(LIBDAI),
        "libdai_binary": str(LIBDAI),
        "runtime_python": str(PY),
        "compilers": {"CC": os.environ["CC"], "CXX": cex["compiler"]},
        "active_host_files": host_files(),
        "tasks": exposed + heldout,
        "replicates": [1, 2],
        "arms": ["PGM", "LIBDAI_JT", "LIBDAI_BP"],
        "budget_s": 20,
        "memory_mib": 3072,
        "epsilon": "1/200",
        "delta": "1/1000000",
        "scored_ceiling_s": 8000,
        "python": subprocess.check_output(
            [str(PY), "-c", "import sys; print(sys.version)"], text=True
        ).strip(),
        "platform": platform.platform(),
        "dependencies": subprocess.check_output(
            [str(PY), "-m", "pip", "freeze"], text=True
        ).splitlines(),
        "old_reference_engine": "7f28259a4869a2c684d506b51072b04bb0ce4783",
        "old_reference_packet_sha256": "78ba37719b48a97a1a463baa00b9e33f556b5f91e3b2acd35bae11f1757ceb3d",
        "prior_reference_sha256": sha(REFERENCE),
        "notes": [
            "55 exposed regression tasks; prospective evaluation independently selected and reported separately.",
            "One frozen public entrypoint, no per-task tuning or hindsight backend selection.",
            "Same20s outer contract; pgm allowance19.5s; process-tree RSS sampled10ms, grace0.",
            "Compilation is setup. Nativebuild outputs may differ from committedmacOS binary but are frozen here.",
            "Prior results are historical comparison, not silently paired same-round measurements.",
            "Failure and timeout remain in coverage; memory refusals never speedup denominators.",
        ],
    }
    dump(ROOT / "FREEZE.json", frozen)
    print(
        json.dumps(
            {
                "frozen": True,
                "engine_commit": frozen["engine_commit"],
                "exposed": len(exposed),
                "eval": len(heldout),
                "cells": len(frozen["tasks"]) * 6,
            }
        )
    )


def receipts(path):
    return (
        [
            d
            for line in Path(path).read_text().splitlines()
            if line.strip() and (d := json.loads(line)).get("kind") == "RECEIPT"
        ]
        if Path(path).exists()
        else []
    )


def run_cell(task, arm, rep, frozen):
    budget = frozen["budget_s"]
    job = f'{task["split"]}__{task["name"]}__{arm}__r{rep}'
    folder = ROOT / "runs" / job
    ledger = ROOT / "RECEIPTS.jsonl"
    assert identity() == frozen["engine_files"], "Source/build changed before cell"
    for k in ("model", "evidence"):
        assert sha(task[k]) == task[k + "_sha256"]
    assert sha(LIBDAI) == frozen["libdai_sha256"]
    prior = [r for r in receipts(ledger) if r["job"] == job]
    assert len(prior) <= 1, "Duplicate terminal receipt"
    if not prior:
        folder.mkdir(parents=True, exist_ok=False)
        if arm == "PGM":
            cmd = [
                str(PY),
                "-m",
                "pgm",
                "--input",
                task["model"],
                "--output",
                str(folder / "result.json"),
                "--budget",
                str(budget - 0.5),
                "--memory-mib",
                "3072",
                "--seed",
                str(rep),
                "--epsilon",
                "1/200",
                "--delta",
                "1/1000000",
            ]
        else:
            alg = (
                "JTREE[inference=SUMPROD,updates=HUGIN,maxmem=3221225472]"
                if arm == "LIBDAI_JT"
                else f"BP[inference=SUMPROD,updates=SEQMAX,logdomain=0,tol=1e-9,maxiter=10000,damping=0.0,maxtime={budget-1.0}]"
            )
            cmd = [
                str(LIBDAI),
                task["model"],
                task["evidence"],
                str(folder / "output.MAR"),
                str(folder / "side.json"),
                alg,
            ]
        build = json.loads((REPO / "code/cex/newarm/cex_build.json").read_text())
        env = dict(
            os.environ,
            PYTHONPATH=str(REPO / "src") + os.pathsep + str(REPO / "code"),
            CXX=frozen["compilers"]["CXX"],
            CC=frozen["compilers"]["CC"],
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            VECLIB_MAXIMUM_THREADS="1",
            NUMEXPR_NUM_THREADS="1",
            PYTHONHASHSEED="0",
        )
        sup = [
            str(PY),
            str(HERE / "strict_supervisor.py"),
            "--ledger",
            str(ledger),
            "--scope",
            task["split"],
            "--job",
            job,
            "--timeout",
            str(budget),
            "--mem-gib",
            "3",
            "--interval",
            "0.01",
            "--cwd",
            str(REPO),
            "--stdout",
            str(folder / "stdout.log"),
            "--stderr",
            str(folder / "stderr.log"),
            "--",
        ] + cmd
        dump(
            folder / "launch.json",
            {
                "command": cmd,
                "supervisor": sup,
                "task": task,
                "environment_overrides": {
                    k: env[k]
                    for k in (
                        "PYTHONPATH",
                        "CXX",
                        "CC",
                        "OMP_NUM_THREADS",
                        "OPENBLAS_NUM_THREADS",
                        "MKL_NUM_THREADS",
                        "PYTHONHASHSEED",
                    )
                },
            },
        )
        with (folder / "supervisor.log").open("w") as log:
            subprocess.run(sup, cwd=REPO, env=env, stdout=log, stderr=log)
    receipt = [r for r in receipts(ledger) if r["job"] == job][-1]
    row = {
        "job": job,
        "task": task["name"],
        "arm": arm,
        "replicate": rep,
        "split": task["split"],
        "historical_cohort": task["historical_cohort"],
        "model_sha256": task["model_sha256"],
        "evidence_sha256": task["evidence_sha256"],
        "wall_s": receipt["wall_s"],
        "budget_s": budget,
        "receipt_outcome": receipt["outcome"],
        "returncode": receipt["returncode"],
        "peak_rss_bytes": receipt["peak_tree_rss_bytes"],
        "identity_ok": identity() == frozen["engine_files"]
        and sha(LIBDAI) == frozen["libdai_sha256"],
    }
    try:
        row.update(
            check_pgm(folder / "result.json", task)
            if arm == "PGM"
            else check_libdai(folder, task)
        )
    except Exception as e:
        row.update(
            output_valid=False, all_queries_returned=False, validation_error=repr(e)
        )
    row["complete_within_contract"] = bool(
        row["identity_ok"]
        and row.get("all_queries_returned")
        and receipt["outcome"] == "COMPLETED"
        and receipt["wall_s"] <= budget
    )
    row["converged_within_contract"] = row["complete_within_contract"] and (
        arm != "LIBDAI_BP" or row.get("converged", False)
    )
    dump(folder / "cell.json", row)
    with (ROOT / "CELLS.jsonl").open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    print(
        json.dumps(
            {
                k: row.get(k)
                for k in (
                    "job",
                    "complete_within_contract",
                    "solver_outcome",
                    "wall_s",
                    "backend",
                    "guarantee",
                    "validation_error",
                )
            }
        ),
        flush=True,
    )
    assert row["identity_ok"], "Source/build changed after cell"
    return row


def run(phase):
    frozen = json.loads((ROOT / "FREEZE.json").read_text())
    assert (
        str(PY) == frozen["runtime_python"]
    ), "Use the frozen runtime interpreter or declare a new experiment"
    assert (
        str(LIBDAI) == frozen["libdai_binary"]
    ), "Use the frozen comparator path or declare a new experiment"
    assert (
        sha(REFERENCE) == frozen["prior_reference_sha256"]
    ), "Historical reference changed"
    split = "exposed_regression" if phase == "primary" else "prospective_external_eval"
    tasks = [t for t in frozen["tasks"] if t["split"] == split]
    done = (
        {
            json.loads(line)["job"]
            for line in (ROOT / "CELLS.jsonl").read_text().splitlines()
        }
        if (ROOT / "CELLS.jsonl").exists()
        else set()
    )
    jobs = [
        (t, a, r)
        for r in frozen["replicates"]
        for i, t in enumerate(tasks)
        for a in (frozen["arms"] if (i + r) % 2 else list(reversed(frozen["arms"])))
    ]
    for task, arm, rep in jobs:
        for n, h in frozen["harness_files"].items():
            assert sha(HERE / n) == h, "Harness changed after freeze: " + n
        for n, h in frozen["input_manifests"].items():
            assert sha(HERE / n) == h, "Input manifest changed after freeze: " + n
        job = f'{split}__{task["name"]}__{arm}__r{rep}'
        if job in done:
            continue
        charge = sum(r["wall_s"] for r in receipts(ROOT / "RECEIPTS.jsonl"))
        if charge + frozen["budget_s"] + 1 > frozen["scored_ceiling_s"]:
            dump(ROOT / "BUDGET_STOP.json", {"charged_s": charge, "next": job})
            return
        run_cell(task, arm, rep, frozen)
    dump(
        ROOT / (phase.upper() + "_RETURN.json"),
        {
            "phase": phase,
            "planned_cells": len(jobs),
            "completed_cells": sum(
                1
                for p in (ROOT / "runs").glob("*/cell.json")
                if json.loads(p.read_text())["split"] == split
            ),
            "charged_s": sum(r["wall_s"] for r in receipts(ROOT / "RECEIPTS.jsonl")),
        },
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["freeze", "primary", "eval"])
    a = ap.parse_args()
    freeze() if a.action == "freeze" else run(a.action)
