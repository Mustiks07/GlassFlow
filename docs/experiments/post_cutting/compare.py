"""Pre-registered, process-isolated bounded comparisons; never imported by production."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import pathlib
import queue
import random
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from decimal import Decimal

from glassflow.modules.cutting.domain import Assignment, MaterialSpec, PartSpec, RemnantSpec, Snapshot
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.solver import CuttingSolver, SolverSettings

HERE = pathlib.Path(__file__).resolve().parent
VARIANTS = ["baseline", "N11_directed", "N12_locations", "N14_components"]
SEEDS = [7, 19, 41]
BUDGET = 20.0
MEMORY = 1024**3


def single_cpu():
    """Hard per-process CPU allocation, including native-library workers."""
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GetProcessAffinityMask.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        handle = kernel.GetCurrentProcess()
        allowed, system = ctypes.c_size_t(), ctypes.c_size_t()
        if not kernel.GetProcessAffinityMask(handle, ctypes.byref(allowed), ctypes.byref(system)):
            raise OSError(ctypes.get_last_error(), "GetProcessAffinityMask")
        core = allowed.value.bit_length() - 1
        if not kernel.SetProcessAffinityMask(handle, 1 << core):
            raise OSError(ctypes.get_last_error(), "SetProcessAffinityMask")
        return [core]
    cores = os.sched_getaffinity(0)
    core = max(cores)
    os.sched_setaffinity(0, {core})
    return sorted(os.sched_getaffinity(0))


class Directed(CuttingSolver):
    def lns(self, seconds):
        count = self.stats.get("directed_moves", 0)
        self.stats["directed_moves"] = count + 1
        if count % 4 == 3 or self.best is None:
            return super().lns(seconds)
        current = self.best.assignments
        uncovered = [p for p in self.p.ordinary_parts if p not in current and self.p.elig.eligible[p]]
        if not uncovered:
            return super().lns(seconds)
        target = max(uncovered, key=lambda p: self.s.parts[p].area / max(1, len(self.p.elig.eligible[p])))
        possible = self.p.elig.eligible[target]
        chosen = sorted(
            possible, key=lambda r: sum(self.s.parts[p].area for p, a in current.items() if a.remnant_id == r)
        )[:3]
        own = [p for p, a in current.items() if a.remnant_id in chosen]
        candidates = (
            own
            + sorted(
                [p for p in uncovered if p not in own and any(r in chosen for r in self.p.elig.eligible[p])],
                key=lambda p: -self.s.parts[p].area / max(1, len(self.p.elig.eligible[p])),
            )[: max(8, 40 - len(own))]
        )
        added = 0
        for pattern in self.cpsat_pack(
            chosen, candidates, {p: self.s.parts[p].area for p in candidates}, seconds
        ):
            if self.p.pattern_ok_for_locks(pattern) and self.pool.add(pattern):
                added += 1
        self.stats["lns_moves"] += 1
        return added


class Locations(CuttingSolver):
    def key(self, outcome):
        used = {a.remnant_id for a in outcome.assignments.values()}
        places = {self.s.remnants[r].location_raw for r in used}
        return (
            outcome.locks_satisfied,
            outcome.meets_min_free,
            outcome.covered_area,
            outcome.full_orders,
            -len(places),
            *self._secondary(outcome),
        )


class Components(CuttingSolver):
    def random_fills(self):
        parent = {r: r for r in self.p.available}

        def find(r):
            while parent[r] != r:
                r = parent[r]
            return r

        for choices in self.p.elig.eligible.values():
            for r in choices[1:]:
                parent[find(r)] = find(choices[0])
        groups = defaultdict(list)
        for r in self.p.available:
            groups[find(r)].append(r)
        ordered = sorted(groups.values(), key=lambda g: (len(g), sorted(g)))
        interleaved = [g[i] for i in range(max(map(len, ordered), default=0)) for g in ordered if i < len(g)]
        saved = self.p.available
        self.p.available = interleaved
        try:
            super().random_fills()
        finally:
            self.p.available = saved
        self.stats["eligibility_components"] = len(groups)


def build(family, seed):
    rng = random.Random(20261128 + (family == "mixed"))
    materials = {
        "clear": MaterialSpec("clear", False, Decimal("4500")),
        "mirror": MaterialSpec("mirror", False, Decimal("9500")),
    }
    rs = {}
    for i in range(18):
        rid = f"{family}-{seed}-piece-{i * 17 + 11}"
        mid = "mirror" if family == "mixed" and i % 2 else "clear"
        rs[rid] = RemnantSpec(
            rid,
            mid,
            rng.randrange(550, 951, 20),
            rng.randrange(350, 651, 20),
            False,
            i + 3,
            "available",
            0,
            f"Rack {i % 3} / cell {i % 2}",
            True,
        )
    ps = {}
    for i in range(64 if family == "dense" else 48):
        pid = f"{family}-{seed}-part-{i * 13 + 5}"
        mid = "mirror" if family == "mixed" and i % 2 else "clear"
        ps[pid] = PartSpec(
            pid,
            f"{family}-{seed}-order-{i // 3}",
            mid,
            rng.randrange(180, 551, 10),
            rng.randrange(130, 391, 10),
            False,
        )
    prng = random.Random(seed)
    rids = list(rs)
    pids = list(ps)
    prng.shuffle(rids)
    prng.shuffle(pids)
    return Snapshot(f"{family}-{seed}", materials, rs, ps, pids, rids)


def source_hash(snapshot):
    from glassflow.modules.cutting.conversion import input_from_snapshot

    body = input_from_snapshot(snapshot).model_dump(mode="json", exclude={"config"})
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def peak_rss(pid):
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t)
                for n in [
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                ]
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return 0
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        try:
            ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            return counters.PeakWorkingSetSize if ok else 0
        finally:
            kernel.CloseHandle(handle)
    try:
        return max(
            int(line.split()[1]) * 1024
            for line in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines()
            if line.startswith(("VmRSS:", "VmHWM:"))
        )
    except (OSError, ValueError):
        return 0


def worker(variant, family, seed):
    affinity = single_cpu()
    snapshot = build(family, seed)
    frozen = json.loads((HERE / "inputs" / f"{family}-{seed}.json").read_text(encoding="utf8"))
    if source_hash(snapshot) != frozen["input_sha256"]:
        raise RuntimeError("Frozen paired input changed")
    start = time.perf_counter()

    def emit(event, **body):
        print(json.dumps({"event": event, "elapsed": time.perf_counter() - start, **body}), flush=True)

    class Callback:
        def cancelled(self):
            return False

        def progress(self, *args):
            pass

        def incumbent(self, outcome):
            rows = outcome.rows(snapshot)
            report = validate_plan(snapshot, rows)
            if not report.valid:
                raise RuntimeError("Invalid incumbent")
            emit(
                "incumbent",
                area=outcome.covered_area,
                full_orders=outcome.full_orders,
                free_original=outcome.free_original,
                locations=len(
                    {snapshot.remnants[a.remnant_id].location_raw for a in outcome.assignments.values()}
                ),
                rows=[
                    dict(
                        part_id=a.part_id,
                        remnant_id=a.remnant_id,
                        x_mm=a.x_mm,
                        y_mm=a.y_mm,
                        rot=a.rot,
                        lock_kind=a.lock_kind,
                    )
                    for a in rows
                ],
            )

    cls = {
        "baseline": CuttingSolver,
        "N11_directed": Directed,
        "N12_locations": Locations,
        "N14_components": Components,
    }[variant]
    solver = cls(
        snapshot,
        SolverSettings(
            profile="standard",
            seed=seed,
            time_limit_seconds=BUDGET,
            workers=1,
            minimum_free_remnants=5,
            max_pool_patterns=10000,
        ),
        callbacks=Callback(),
    )
    emit("started", input_sha256=source_hash(snapshot), cpu_affinity=affinity)
    result = solver.run()
    emit(
        "finished",
        stop_reason=result.stop_reason,
        search_status=result.search_status,
        stats=result.stats,
        peak_rss_bytes=peak_rss(os.getpid()),
    )


def trial(variant, family, seed):
    process = subprocess.Popen(
        [sys.executable, str(__file__), "--worker", variant, "--family", family, "--seed", str(seed)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf8",
        creationflags=0x08000000 if os.name == "nt" else 0,
        env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
    )
    events = queue.Queue()

    def reader():
        for line in process.stdout:
            try:
                events.put(json.loads(line))
            except ValueError:
                events.put({"event": "parse_error"})

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    started = time.monotonic()
    deadline = started + 30
    first = None
    best = None
    peak = 0
    stop = "process_finished"
    detail = None
    affinity = None
    while process.poll() is None or thread.is_alive() or not events.empty():
        peak = max(peak, peak_rss(process.pid))
        try:
            event = events.get(timeout=0.02)
        except queue.Empty:
            event = None
        if event:
            if event["event"] == "started":
                deadline = time.monotonic() + BUDGET + 0.15
                affinity = event["cpu_affinity"]
            elif event["event"] == "incumbent" and event["elapsed"] <= BUDGET:
                if first is None:
                    first = event["elapsed"]
                best = event
            elif event["event"] == "finished":
                detail = event
                peak = max(peak, event["peak_rss_bytes"])
        if process.poll() is None and (peak > MEMORY or time.monotonic() > deadline):
            stop = "memory_limit" if peak > MEMORY else "common_deadline"
            process.kill()
            break
    process.wait(timeout=5)
    thread.join(timeout=2)
    error = process.stderr.read()[-500:]
    snapshot = build(family, seed)
    valid = False
    if best:
        validation = validate_plan(snapshot, [Assignment(**r) for r in best.pop("rows")])
        valid = validation.valid and best["free_original"] >= 5
    return {
        "variant": variant,
        "family": family,
        "seed": seed,
        "input_sha256": source_hash(snapshot),
        "budget_seconds": BUDGET,
        "workers": 1,
        "cpu_affinity": affinity,
        "memory_limit_bytes": MEMORY,
        "peak_rss_bytes": peak,
        "valid_complete": valid,
        "first_valid_seconds": first,
        "selected": best,
        "process_stop": stop,
        "finished": detail,
        "exit_code": process.returncode,
        "stderr_tail": error,
    }


def compare():
    report = {
        "baseline_commit": "a079a28",
        "previous_pilot": "pilot-9s-partial.json: interrupted; existing baseline corrected before v2",
        "candidate_source_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(),
        "clock": "same20s process budget; latest independently valid incumbent at <=20s, late final ignored",
        "memory": "native OS peak RSS in fresh isolated process; hard1GiB parent monitor",
        "machine": {"os": sys.platform, "python": sys.version, "logical_cpus": os.cpu_count()},
        "trials": [],
    }
    for family_index, family in enumerate(["dense", "mixed"]):
        for seed_index, seed in enumerate(SEEDS):
            offset = (family_index + seed_index) % len(VARIANTS)
            for variant in VARIANTS[offset:] + VARIANTS[:offset]:
                row = trial(variant, family, seed)
                report["trials"].append(row)
                (HERE / "comparison.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
                )
                print(
                    f"{family}/{seed}/{variant}: valid={row['valid_complete']}, area={(row['selected'] or {}).get('area')}",
                    flush=True,
                )
    decisions = {}
    for variant in VARIANTS[1:]:
        rows = [r for r in report["trials"] if r["variant"] == variant]
        pairs = [
            (
                next(
                    b
                    for b in report["trials"]
                    if b["variant"] == "baseline" and b["family"] == r["family"] and b["seed"] == r["seed"]
                ),
                r,
            )
            for r in rows
        ]
        guard = all(
            a["valid_complete"]
            and b["valid_complete"]
            and a["peak_rss_bytes"] > 0
            and b["peak_rss_bytes"] > 0
            and b["peak_rss_bytes"] <= a["peak_rss_bytes"] * 1.15
            and b["peak_rss_bytes"] <= MEMORY
            and a["cpu_affinity"] == b["cpu_affinity"]
            and len(a["cpu_affinity"] or []) == 1
            for a, b in pairs
        )

        def p95(values):
            return sorted(values)[max(0, int(len(values) * 0.95 + 0.999) - 1)]

        timing = all(
            a["first_valid_seconds"] is not None and b["first_valid_seconds"] is not None for a, b in pairs
        )
        timing = (
            timing
            and p95([b["first_valid_seconds"] for a, b in pairs])
            <= p95([a["first_valid_seconds"] for a, b in pairs]) + 0.1
        )
        guard = guard and timing
        changes = [
            (b["selected"] or {}).get("area", 0) - (a["selected"] or {}).get("area", 0) for a, b in pairs
        ]
        if variant == "N12_locations":
            better = sum(
                (b["selected"] or {}).get("locations", 999) < (a["selected"] or {}).get("locations", 0)
                for a, b in pairs
            )
            promote = (
                guard
                and all(d >= 0 for d in changes)
                and all(
                    b["selected"]["full_orders"] >= a["selected"]["full_orders"]
                    and b["selected"]["locations"] <= a["selected"]["locations"]
                    for a, b in pairs
                )
                and better >= len(pairs) / 2
            )
        else:
            gains = [
                100 * d / build(a["family"], a["seed"]).total_part_area for (a, b), d in zip(pairs, changes)
            ]
            promote = (
                guard
                and all(d >= 0 for d in changes)
                and statistics.median(gains) >= 0.1
                and all(
                    sum(d > 0 for (a, b), d in zip(pairs, changes) if a["family"] == family) >= 2
                    for family in ["dense", "mixed"]
                )
            )
        decisions[variant] = {
            "promote": promote,
            "guards_passed": guard,
            "area_deltas_mm2": changes,
            "decision": "candidate meets pre-registered guards"
            if promote
            else "keep strong baseline; pre-registered guards not met",
        }
    report["decisions"] = decisions
    (HERE / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(json.dumps(decisions, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=VARIANTS)
    parser.add_argument("--family")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.family, args.seed)
    else:
        compare()
