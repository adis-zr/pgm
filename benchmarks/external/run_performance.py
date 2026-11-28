#!/usr/bin/env python3
"""Frozen, serial comparison of the consolidated baseline, current package and libDAI.

The existing external readers and zero-grace supervisor are reused. This runner
never changes the historical step-2 protocol, records, or benchmark inputs.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import run_suite as checks
from benchmark_validity import censored_comparator, censored_fields, check_public_output

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASELINE_COMMIT = "f664ee7aa06851c77e9876cea409d4a04a9e4b21"
ARMS = ("BASE_ACCEPTED", "PGM_ACCEPTED", "BASE_EXPERIMENTAL", "PGM_AUTOMATIC", "LIBDAI_JT", "LIBDAI_BP")
POLICIES = {"BASE_ACCEPTED": "accepted", "PGM_ACCEPTED": "accepted", "BASE_EXPERIMENTAL": "experimental", "PGM_AUTOMATIC": "automatic"}
ROOT_KEYS = {a: "baseline" if a.startswith("BASE_") else "candidate" for a in POLICIES}
HOST_OVERLAYS = frozenset("src/pgm/algorithms/structural/" + n for n in (
    "libcex_kernel.dylib", "cex_build.json", "libstream_kernel.so", "stream_build.json"))
PROTOCOL_PATH = HERE / "PERFORMANCE_ROUND2_PLAN.json"
MANIFEST_NAMES = ("INPUT_MANIFEST.json", "HOLDOUT_FREEZE.json", "EXPOSURE_HISTORY.json")
HARNESS_NAMES = ("run_performance.py", "analyze_performance.py", "benchmark_validity.py", "PERFORMANCE_ROUND2_PLAN.json", "PERFORMANCE_ROUND2_PLAN.md", "run_suite.py", "strict_supervisor.py")
sha = checks.sha


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=str)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def exclusive_run(path):
    """Prevent two resume processes from launching the same frozen cell."""
    path.mkdir(parents=True, exist_ok=True)
    with (path / ".runner.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def clean_tree(root):
    changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True).splitlines()
    unexpected = [line for line in changes if line[3:] not in HOST_OVERLAYS]
    if unexpected:
        raise RuntimeError("Commit all source and harness changes before freezing/running: " + repr(unexpected))


def source_manifest(root):
    # All executable package/research sources, tests and package metadata, plus
    # this campaign and its reused readers. Large historical result archives do
    # not execute; model bytes have their separate complete manifest below.
    files = git(root, "ls-files", "src", "code", "tests", "pyproject.toml", "setup.cfg", "setup.py").splitlines()
    files += ["benchmarks/external/" + name for name in HARNESS_NAMES if (root / "benchmarks/external" / name).is_file()]
    out = {}
    for relative in sorted(set(files)):
        path = root / relative
        if path.is_file():
            out[relative] = sha(path)
    return out


def environment(config, key="candidate"):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PGM_NATIVE_CACHE", "GBIDI_OWNER_DIR", "GBIDI_JID", "GBIDI_PARENT_JID")}
    root = Path(config["roots"][key]["path"])
    env.update(PYTHONPATH=os.pathsep.join((str(root / "src"), str(root / "code"))),
               PGM_NATIVE_CACHE=config["roots"][key]["native_cache"],
               CC=config["compilers"]["CC"], CXX=config["compilers"]["CXX"],
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               VECLIB_MAXIMUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONHASHSEED="0")
    return env


def native_manifest(config, key):
    """Resolve and verify the exact native artifacts loaded by this root."""
    root = Path(config["roots"][key]["path"])
    process = subprocess.run([config["runtime_python"], "-c", checks.NEW_LAYOUT_PROBE], cwd=root,
                             env=environment(config, key), text=True, capture_output=True, timeout=60)
    if process.returncode:
        raise RuntimeError("Native probe failed: " + process.stderr[-1000:])
    locations = json.loads(process.stdout.strip().splitlines()[-1])
    active = {}
    for kind in ("cex", "stream"):
        item = locations[kind]
        record = json.loads(Path(item["record"]).read_text())
        if sha(item["src"]) != record["source_sha256"] or sha(item["lib"]) != record["binary_sha256"]:
            raise RuntimeError("Stale native build: " + kind)
        cached = Path(item["cache"]) / (item["prefix"] + record["binary_sha256"] + item["suffix"])
        if sha(cached) != record["binary_sha256"]:
            raise RuntimeError("Unverified native cache: " + str(cached))
        for path in (item["src"], item["record"], item["lib"], str(cached)):
            active[path] = sha(path)
    item = locations["heat"]
    record = json.loads(Path(item["record"]).read_text())
    if Path(record["library"]).name != record["library"]:
        raise RuntimeError("Heat-bath cache path escapes its directory")
    library = Path(item["cache"]) / record["library"]
    if sha(item["src"]) != record["source_sha256"] or sha(library) != record["binary_sha256"]:
        raise RuntimeError("Stale heat-bath build")
    for path in (item["src"], item["record"], str(library)):
        active[path] = sha(path)
    return active


def task_inventory():
    tasks = []
    for name, cohort in (("INPUT_MANIFEST.json", "old55"), ("HOLDOUT_FREEZE.json", "former_eval6")):
        for task in checks.tasks_from_manifest(HERE / name):
            task.update(historical_group=cohort, exposure_status="exposed_regression")
            tasks.append(task)
    if len(tasks) != 61 or len({(t["model_sha256"], t["evidence_sha256"]) for t in tasks}) != 61 or len({t["name"] for t in tasks}) != 61:
        raise RuntimeError("The complete 61-task external panel is required")
    return tasks


def job_name(task, arm, replicate):
    name = task["name"]
    if Path(name).name != name or "__" in name:
        raise ValueError("Unsafe task name")
    return f"{name}__{arm}__r{replicate}"


def schedule(frozen):
    """Both policies get a paired before/after order reversal, without outcomes."""
    for replicate in frozen["replicates"]:
        for index, task in enumerate(frozen["tasks"]):
            order = frozen["arms"] if (index + replicate) % 2 else list(reversed(frozen["arms"]))
            for arm in order:
                yield task, arm, replicate


def contract(arm):
    if arm == "PGM_AUTOMATIC":
        return dict(checks.CONTRACTS["PGM_EXPERIMENTAL"], policy="automatic", policy_version="structural-portfolio-3")
    return checks.CONTRACTS["PGM_" + POLICIES[arm].upper()] if arm in POLICIES else None


def command(config, task, arm, replicate, folder):
    if arm in POLICIES:
        return [config["runtime_python"], "-m", "pgm", "--input", task["model"], "--output", str(folder / "result.json"),
                "--budget", "19.5", "--memory-mib", "3072", "--seed", str(replicate), "--epsilon", "1/200", "--delta", "1/1000000", "--policy", POLICIES[arm]]
    algorithm = ("JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]" if arm == "LIBDAI_JT" else
                 "BP[inference=SUMPROD,updates=SEQMAX,logdomain=0,tol=1e-9,maxiter=10000,damping=0.0,maxtime=19]")
    return [config["libdai_binary"], task["model"], task["evidence"], str(folder / "output.MAR"), str(folder / "side.json"), algorithm]


def supervised(config, task, arm, replicate, folder, ledger, scope):
    env = environment(config, ROOT_KEYS.get(arm, "candidate"))
    candidate = Path(config["roots"]["candidate"]["path"])
    supervisor_env = environment(config, "candidate")
    cmd = command(config, task, arm, replicate, folder)
    sup = [config["runtime_python"], str(candidate / "benchmarks/external/strict_supervisor.py"),
           "--ledger", str(ledger), "--scope", scope, "--job", job_name(task, arm, replicate),
           "--timeout", "20", "--mem-gib", "3", "--interval", "0.01", "--cwd", str(candidate),
           "--stdout", str(folder / "stdout.log"), "--stderr", str(folder / "stderr.log"),
           "--env", "PYTHONPATH=" + env["PYTHONPATH"], "--env", "PGM_NATIVE_CACHE=" + env["PGM_NATIVE_CACHE"], "--", *cmd]
    atomic_json(folder / "launch.json", dict(command=cmd, supervisor=sup, task=task, arm=arm, replicate=replicate,
                                              launched_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                              environment={k: env[k] for k in ("PYTHONPATH", "PGM_NATIVE_CACHE", "CC", "CXX", "PYTHONHASHSEED", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")}))
    with (folder / "supervisor.log").open("ab") as log:
        subprocess.run(sup, cwd=candidate, env=supervisor_env, stdout=log, stderr=log)


def terminal_receipt(ledger, job):
    records = checks.receipts(ledger)
    matches = [record for record in records if record.get("job") == job]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one terminal receipt for {job}; found {len(matches)}. Reconcile before resuming; never rerun silently.")
    return matches[0]


def read_cell(config, task, arm, replicate, folder, receipt, identity_ok):
    row = dict(job=job_name(task, arm, replicate), task=task["name"], arm=arm, replicate=replicate,
               split="exposed_regression", historical_group=task.get("historical_group"), family=task.get("family"),
               model_sha256=task["model_sha256"], evidence_sha256=task["evidence_sha256"], wall_s=receipt["wall_s"],
               budget_s=20, receipt_outcome=receipt["outcome"], returncode=receipt["returncode"],
               peak_rss_bytes=receipt["peak_tree_rss_bytes"], cleanup_unresolved=receipt.get("cleanup_unresolved"),
               identity_ok=identity_ok, receipt_jid=receipt["jid"])
    try:
        if censored_comparator(config, arm, receipt):
            row.update(censored_fields(receipt))
        else:
            row.update(check_public_output(config, folder / "result.json", task, config["contracts"][arm], receipt) if arm in POLICIES else checks.check_libdai(folder, task))
        if arm in POLICIES:
            result = json.loads((folder / "result.json").read_text())
            row["attempts"] = result.get("attempts", [])
            row["planning"] = result.get("planning", {})
            row["phase_timings"] = result.get("phase_timings", {})
    except (OSError, ValueError, KeyError, StopIteration) as error:
        row.update(output_valid=False, contract_valid=False, all_queries_returned=False, validation_error=repr(error))
    row["complete_within_contract"] = bool(identity_ok and row.get("all_queries_returned") and row.get("contract_valid")
        and row.get("output_valid") and receipt["outcome"] == "COMPLETED" and receipt["returncode"] == 0
        and receipt["wall_s"] <= 20 and receipt.get("cleanup_unresolved") is False
        and receipt.get("group_empty_at_receipt") is True and receipt.get("nested_groups_live_at_receipt") == 0)
    row["converged_within_contract"] = row["complete_within_contract"] and (arm != "LIBDAI_BP" or bool(row.get("converged")))
    row["artifact_sha256"] = {name: sha(folder / name) for name in ("launch.json", "result.json", "output.MAR", "side.json", "stdout.log", "stderr.log", "supervisor.log") if (folder / name).is_file()}
    return row


def config_from_args(args):
    baseline = Path(args.baseline_root).expanduser().resolve()
    if git(baseline, "rev-parse", "HEAD") != BASELINE_COMMIT:
        raise RuntimeError("Baseline must be the consolidated f664ee7 commit")
    binary = Path(args.libdai).expanduser().resolve()
    qualification_path = Path(args.qualification).expanduser().resolve()
    qualification = json.loads(qualification_path.read_text())
    if qualification.get("all_ok") is not True or qualification.get("binary_sha256") != sha(binary):
        raise RuntimeError("libDAI qualification does not bind to the executable")
    return dict(runtime_python=str(Path(sys.executable).absolute()), python_sha256=sha(Path(sys.executable).resolve()),
                roots={key: dict(path=str(path), native_cache=str(args.run_dir / "setup/native" / key)) for key, path in (("baseline", baseline), ("candidate", REPO))},
                compilers=checks.resolve_compilers(), libdai_binary=str(binary), libdai_sha256=sha(binary),
                libdai_qualification_path=str(qualification_path), libdai_qualification_sha256=sha(qualification_path),
                protocol=json.loads(PROTOCOL_PATH.read_text()), protocol_sha256=sha(PROTOCOL_PATH),
                contracts={arm: contract(arm) for arm in POLICIES})


def setup(args):
    config = config_from_args(args)
    setup_dir = args.run_dir / "setup"
    if (setup_dir / "SETUP.json").exists():
        raise RuntimeError("Setup already exists; use a fresh run directory")
    setup_dir.mkdir(parents=True, exist_ok=True)
    builds = {}
    for key in config["roots"]:
        command_ = ("import pgm.algorithms.structural.cex_executor as CX, pgm.algorithms.structural.stream_float as SF, "
                    "pgm.algorithms.response.heatbath_native as HN; "
                    "p=CX.build(); CX.load(p); s=SF.build(); SF._load_verified(s); HN.build(); print('native kernels built and loaded')")
        process = subprocess.run([config["runtime_python"], "-c", command_], cwd=config["roots"][key]["path"],
                                 env=environment(config, key), text=True, capture_output=True, timeout=1800)
        builds[key] = dict(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
        atomic_json(setup_dir / (key + "_build.json"), builds[key])
        if process.returncode:
            raise RuntimeError("Native build failed: " + process.stderr[-1000:])
        config["roots"][key]["natives"] = native_manifest(config, key)
    fixture = setup_dir / "fixture"
    fixture.mkdir()
    model = fixture / "model.uai"
    shutil.copyfile(REPO / "tests/parity/fixtures/asym2.uai", model)
    evidence = model.with_suffix(".uai.evid")
    evidence.write_text("0\n")
    task = dict(name="setup_asym2", model=str(model), evidence=str(evidence), model_sha256=sha(model), evidence_sha256=sha(evidence))
    smoke = {}
    for arm in ARMS:
        folder = setup_dir / arm
        folder.mkdir()
        ledger = setup_dir / "RECEIPTS.jsonl"
        supervised(config, task, arm, 1, folder, ledger, "performance_setup")
        receipt = terminal_receipt(ledger, job_name(task, arm, 1))
        row = read_cell(config, task, arm, 1, folder, receipt, True)
        smoke[arm] = row
        atomic_json(folder / "cell.json", row)
        print(json.dumps(dict(setup_arm=arm, complete=row["complete_within_contract"], faults=row.get("contract_faults"), error=row.get("validation_error"))), flush=True)
    config.update(smoke_all_valid=all(row["complete_within_contract"] for row in smoke.values()), smoke=smoke, builds=builds)
    atomic_json(setup_dir / "SETUP.json", config)
    if not config["smoke_all_valid"]:
        raise RuntimeError("Setup smoke failed")


def freeze(args):
    path = args.run_dir / "FREEZE.json"
    if path.exists():
        raise RuntimeError("Freeze exists; it is immutable")
    config = json.loads((args.run_dir / "setup/SETUP.json").read_text())
    if config.get("smoke_all_valid") is not True:
        raise RuntimeError("All setup arms must pass")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if config.get("protocol") != protocol or config.get("protocol_sha256") != sha(PROTOCOL_PATH):
        raise RuntimeError("Protocol changed after setup qualification")
    if (protocol.get("arms") != list(ARMS) or protocol.get("replicates") != [1, 2]
            or protocol.get("tasks") != 61 or protocol.get("expected_cells") != 732
            or protocol.get("contract") != dict(outer_seconds=20, pgm_seconds=19.5,
                memory_mib=3072, epsilon="1/200", delta="1/1000000", sample_interval_seconds=0.01,
                grace_seconds=0, scored_ceiling_seconds=14640)):
        raise RuntimeError("Committed plan and executable matrix/contract disagree")
    for key, root in config["roots"].items():
        clean_tree(root["path"])
        root["commit"] = git(root["path"], "rev-parse", "HEAD")
        if key == "baseline" and root["commit"] != BASELINE_COMMIT:
            raise RuntimeError("Baseline moved")
        root["sources"] = source_manifest(Path(root["path"]))
        if native_manifest(config, key) != root["natives"]:
            raise RuntimeError("Native bytes changed after setup")
    historical_path = REPO / "documentation/consolidation/step2/supplement/ANALYSIS.json"
    historical = json.loads(historical_path.read_text())["complete_both"]
    tasks = task_inventory()
    previous_dir = REPO / "documentation/performance/round1/results"
    previous_analysis = previous_dir / "ANALYSIS.json"
    previous_freeze = previous_dir / "FREEZE.json"
    previous = json.loads(previous_analysis.read_text())
    if previous["freeze_sha256"] != sha(previous_freeze) or len(previous["complete_both"]["PGM_AUTOMATIC"]) != 50:
        raise RuntimeError("Round-1 candidate coverage reference is not the recorded 50-task set")
    config.update(schema="PGM_UNTUNED_PERFORMANCE_2", frozen_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  tasks=tasks, arms=list(ARMS), replicates=[1, 2], expected_cells=732,
                  budget_s=20, pgm_allowance_s=19.5, memory_mib=3072, epsilon="1/200", delta="1/1000000", scored_ceiling_s=14640,
                  protocol=protocol, protocol_sha256=sha(PROTOCOL_PATH),
                  previous_candidate_reference=dict(analysis_path=str(previous_analysis), analysis_sha256=sha(previous_analysis),
                      freeze_path=str(previous_freeze), freeze_sha256=sha(previous_freeze), arm="PGM_AUTOMATIC",
                      engine_commit="d33d40aec7a05ec43cd52ff2793e544f9edc4cf0"),
                  harness_files={name: sha(HERE / name) for name in HARNESS_NAMES},
                  input_manifests={name: sha(HERE / name) for name in MANIFEST_NAMES},
                  setup_sha256=sha(args.run_dir / "setup/SETUP.json"),
                  historical_reference=dict(path=str(historical_path), sha256=sha(historical_path),
                      sets={"accepted": historical["PGM_ACCEPTED"], "experimental": historical["PGM_EXPERIMENTAL"]}),
                  host=dict(platform=platform.platform(), machine=platform.machine(), python=sys.version),
                  dependencies=subprocess.check_output([config["runtime_python"], "-m", "pip", "freeze"], text=True).splitlines())
    # Preserve executed native bytes, build records, source and comparator in
    # the run packet. Paths in the identity record still bind the active files.
    artifact_dir = args.run_dir / "artifacts"
    artifact_dir.mkdir()
    artifact_paths = {config["libdai_binary"], config["libdai_qualification_path"]}
    for root in config["roots"].values():
        artifact_paths.update(root["natives"])
    config["archived_artifacts"] = {}
    for source in sorted(artifact_paths):
        target = artifact_dir / (sha(source) + "_" + Path(source).name)
        if not target.exists():
            shutil.copyfile(source, target)
        config["archived_artifacts"][source] = dict(path=str(target.relative_to(args.run_dir)), sha256=sha(target))
    verify_identity(config)
    atomic_json(path, config)
    print(json.dumps(dict(frozen=True, commits={k: v["commit"] for k, v in config["roots"].items()}, cells=732, ceiling_s=14640)), flush=True)


def verify_identity(config):
    """No source, input, compiler, comparator or loaded native change is allowed."""
    for key, root in config["roots"].items():
        clean_tree(root["path"])
        if git(root["path"], "rev-parse", "HEAD") != root["commit"] or source_manifest(Path(root["path"])) != root["sources"]:
            raise RuntimeError("Source closure changed: " + key)
        for path, digest in root["natives"].items():
            if sha(path) != digest:
                raise RuntimeError("Active native identity changed: " + path)
    for name, digest in config["harness_files"].items():
        if sha(HERE / name) != digest:
            raise RuntimeError("Harness changed: " + name)
    for name, digest in config["input_manifests"].items():
        if sha(HERE / name) != digest:
            raise RuntimeError("Input manifest changed: " + name)
    for path_key, digest_key in (("libdai_binary", "libdai_sha256"), ("libdai_qualification_path", "libdai_qualification_sha256"), ("runtime_python", "python_sha256")):
        if sha(config[path_key]) != config[digest_key]:
            raise RuntimeError("Runtime identity changed: " + path_key)
    for key in ("CC", "CXX"):
        if sha(config["compilers"][key]) != config["compilers"][key + "_sha256"]:
            raise RuntimeError("Compiler identity changed")
    reference = config["historical_reference"]
    if sha(reference["path"]) != reference["sha256"]:
        raise RuntimeError("Historical preservation reference changed")
    previous = config["previous_candidate_reference"]
    for field in ("analysis", "freeze"):
        if sha(previous[field + "_path"]) != previous[field + "_sha256"]:
            raise RuntimeError("Previous candidate reference changed: " + field)


def run(args):
    config = json.loads((args.run_dir / "FREEZE.json").read_text())
    if str(Path(sys.executable).absolute()) != config["runtime_python"]:
        raise RuntimeError("Use the frozen interpreter")
    verify_identity(config)
    ledger = args.run_dir / "RECEIPTS.jsonl"
    executed = 0
    for task, arm, replicate in schedule(config):
        job = job_name(task, arm, replicate)
        folder = args.run_dir / "runs" / job
        if (folder / "cell.json").exists():
            row = json.loads((folder / "cell.json").read_text())
            receipt = terminal_receipt(ledger, job)
            if (row.get("receipt_jid") != receipt["jid"] or row.get("identity_ok") is not True
                    or (row.get("task"), row.get("arm"), row.get("replicate"), row.get("job")) != (task["name"], arm, replicate, job)):
                raise RuntimeError("Invalid prior cell; resume refused: " + job)
            for name, digest in row.get("artifact_sha256", {}).items():
                if Path(name).name != name or sha(folder / name) != digest:
                    raise RuntimeError("Prior artifact changed; resume refused: " + job)
            continue
        verify_identity(config)
        for key in ("model", "evidence"):
            if sha(task[key]) != task[key + "_sha256"]:
                raise RuntimeError("Input bytes changed: " + task[key])
        if folder.exists():
            # A launch may have completed before cell assembly. Only a terminal
            # receipt permits reconstruction; this is never an inference rerun.
            receipt = terminal_receipt(ledger, job)
            launch = json.loads((folder / "launch.json").read_text())
            if launch["arm"] != arm or launch["replicate"] != replicate or launch["task"] != task:
                raise RuntimeError("Existing launch does not match its frozen task")
        else:
            charge = sum(record["wall_s"] for record in checks.receipts(ledger))
            if charge + config["budget_s"] > config["scored_ceiling_s"]:
                atomic_json(args.run_dir / "BUDGET_STOP.json", dict(charged_s=charge, next_job=job, status="INCOMPLETE"))
                return
            folder.mkdir(parents=True)
            supervised(config, task, arm, replicate, folder, ledger, "untuned_performance")
            receipt = terminal_receipt(ledger, job)
        identity_error = None
        try:
            verify_identity(config)
            for key in ("model", "evidence"):
                if sha(task[key]) != task[key + "_sha256"]:
                    raise RuntimeError("Input changed during cell")
        except (OSError, ValueError, RuntimeError) as error:
            identity_error = repr(error)
        row = read_cell(config, task, arm, replicate, folder, receipt, identity_error is None)
        if identity_error:
            row["identity_error"] = identity_error
        atomic_json(folder / "cell.json", row)
        print(json.dumps({key: row.get(key) for key in ("job", "complete_within_contract", "solver_outcome", "wall_s", "guarantee", "validation_error", "contract_faults")}), flush=True)
        if identity_error:
            raise RuntimeError("Identity changed during cell; evidence retained and campaign stopped")
        executed += 1
        if args.max_cells is not None and executed >= args.max_cells:
            return
    rows = [json.loads(path.read_text()) for path in sorted((args.run_dir / "runs").glob("*/cell.json"))]
    atomic_json(args.run_dir / "CELLS.json", rows)
    atomic_json(args.run_dir / "RUN_RETURN.json", dict(cells=len(rows), expected=config["expected_cells"], charged_s=sum(r["wall_s"] for r in checks.receipts(ledger))))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "freeze", "run", "analyze"))
    parser.add_argument("--run-dir", type=Path, default=Path(os.environ.get("PGM_PERFORMANCE_RUN_DIR", REPO / "benchmark_runs/untuned-runtime-2")))
    parser.add_argument("--baseline-root", default=os.environ.get("PGM_PERFORMANCE_BASELINE_ROOT", str(REPO.parent / "pgm-performance-baseline")))
    parser.add_argument("--libdai", default=os.environ.get("PGM_LIBDAI", str(REPO / "code/bench/libdai/libdai_mar")))
    parser.add_argument("--qualification", default=os.environ.get("PGM_LIBDAI_QUALIFICATION", str(HERE / "provenance/LIBDAI_QUALIFICATION.json")))
    parser.add_argument("--max-cells", type=int, help="Pause after this many new cells; resume under the same freeze")
    args = parser.parse_args(argv)
    args.run_dir = args.run_dir.expanduser().resolve()
    if args.max_cells is not None and args.max_cells <= 0:
        parser.error("--max-cells must be positive")
    with exclusive_run(args.run_dir):
        if args.action == "analyze":
            from analyze_performance import main as analyze_main
            raise SystemExit(analyze_main([str(args.run_dir)]))
        else:
            globals()[args.action](args)


if __name__ == "__main__":
    main()
