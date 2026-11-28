"""Durable queue, spawn workers and one coordinator writer. Workers never open SQLite."""

import multiprocessing as mp
import threading
import time
from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy import select

from glassflow.contracts.platform import Job
from glassflow.core.errors import AppError
from glassflow.core.models import JobRow, ObjectRow, now, uid
from glassflow.core.uow import audit, canonical_hash, write_transaction
from glassflow.modules.platform.budgets import remaining


@dataclass(frozen=True)
class Handler:
    function: object
    lane: str = "cpu"
    validate: object = None
    timeout_seconds: float = 3660
    memory_limit_mb: int = 2048
    checkpoint_validate: object = None


class Cancelled(Exception):
    pass


class BudgetExpired(Exception):
    pass


def serialize(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


class ProcessContext:
    def __init__(self, sender, cancelled, snapshot, validator, private_config=None):
        self.sender, self.event, self.snapshot, self.validator = sender, cancelled, snapshot, validator
        self.private_config = private_config or {}  # Memory-only provider credentials; never part of JobRow.
        available = remaining(snapshot.get("run_budget"), work=True)
        self.deadline = time.monotonic() + available if available is not None else None

    def cancelled(self):
        return self.event.is_set() or (self.deadline is not None and time.monotonic() >= self.deadline)

    def remaining_seconds(self):
        return max(0.0, self.deadline - time.monotonic()) if self.deadline is not None else None

    def progress(self, stage, completed, total=None):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise BudgetExpired()
        if self.cancelled():
            raise Cancelled()
        if completed < 0 or (total is not None and (total < completed or total < 0)):
            raise ValueError("Invalid progress")
        self.sender.send(("progress", {"stage": str(stage)[:100], "completed": completed, "total": total}))

    def incumbent(self, result):
        if self.validator is None or not self.validator(self.snapshot, serialize(result)):
            raise ValueError("Incumbent requires independent validation")
        self.sender.send(("incumbent", serialize(result)))

    def checkpoint(self, row_id, fingerprint, payload):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise BudgetExpired()
        if self.cancelled():
            raise Cancelled()
        self.sender.send(("checkpoint", {"row_id": row_id, "fingerprint": fingerprint,
            "payload": serialize(payload), "attempt_id": self.snapshot["attempt_id"]}))


def process_entry(sender, cancel, handler, snapshot, private_config=None):
    try:
        context = ProcessContext(sender, cancel, snapshot, handler.validate, private_config)
        result = serialize(handler.function(snapshot, context))
        if not isinstance(result, dict):
            raise ValueError("Job handler must return a typed object/envelope")
        if handler.validate is not None and not handler.validate(snapshot, result):
            raise ValueError("Invalid final result")
        sender.send(("result", result))
    except Cancelled:
        sender.send(("cancelled", None))
    except BudgetExpired:
        sender.send(("failed", "RUN_WORK_BUDGET_EXCEEDED"))
    except BaseException:
        # No exception text, prompts or secrets cross into persistent diagnostics.
        sender.send(("failed", "WORKER_FAILED"))
    finally:
        sender.close()


def job_dto(row):
    return Job(
        job_id=row.id,
        dataset_id=row.dataset_id,
        run_id=row.run_id,
        state=row.state,
        stage=row.stage,
        result_ref=row.id if row.result is not None else None,
        last_valid_result_ref=row.id if row.last_valid_result is not None else None,
        result=row.result,
        last_valid_result=row.last_valid_result,
        error_code=row.error_code,
        cancel_requested=row.cancel_requested,
        stopped=row.stopped,
        completed=row.completed,
        total=row.total,
        retry_of=row.input.get("retry_of"),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        accepted_row_count=row.input.get("accepted_row_count", 0),
    )


def enqueue(session, dataset_id, kind, snapshot, run_id=None):
    job_id = uid()
    snapshot = {**snapshot, "checkpoint_lineage": snapshot.get("checkpoint_lineage", job_id)}
    job = JobRow(
        id=job_id,
        dataset_id=dataset_id,
        run_id=run_id,
        kind=kind,
        input=snapshot,
        state="queued",
        stage="queued",
        completed=0,
        cancel_requested=False,
        stopped=False,
    )
    session.add(job)
    return job


def get_job(session, job_id, dataset_id=None):
    row = session.get(JobRow, job_id)
    if row is None or (dataset_id is not None and row.dataset_id != dataset_id):
        raise AppError(404, "JOB_NOT_FOUND", "Задание не найдено в этом наборе.")
    return row


class Coordinator:
    def __init__(
        self, factory, handlers, *, network_parallel=2, tick=None, result_hooks=None, private_context=None,
        export_context=None,
    ):
        self.factory, self.handlers = factory, handlers
        self.capacity = {"cpu": 1, "network": network_parallel}
        self.active = {}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="glassflow-coordinator", daemon=True)
        self.context = mp.get_context("spawn")
        self.healthy = True
        self.tick = tick
        self.result_hooks = result_hooks or {}
        self.private_context = private_context or {}
        self.export_context = export_context
        self.exports = {}
        self.next_export_scan = 0.0

    def configure_export_context(self, data_dir, services):
        self.export_context = {"data_dir": data_dir, "services": services}

    def start(self):
        with write_transaction(self.factory) as session:
            for row in session.scalars(select(JobRow).where(JobRow.state.in_(["running", "queued"]))):
                row.state, row.stage = "interrupted", "restart"
                row.error_code, row.stopped, row.finished_at = "PROCESS_RESTARTED", True, now()
                audit(session, row.dataset_id, "job.stopped", row.id, "coordinator-restart",
                      state="interrupted", error_code=row.error_code, elapsed_seconds=None,
                      elapsed_basis="not_available_after_restart")
            for row in session.scalars(select(ObjectRow).where(ObjectRow.kind == "run")):
                budget = row.data.get("budget")
                if budget and budget.get("export_status") == "running":
                    row.data = {**row.data, "budget": {**budget, "export_status": "interrupted"}}
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=6)
        for value in list(self.exports.values()):
            value["thread"].join(timeout=10)
        self.healthy = False

    def loop(self):
        try:
            while not self.stop_event.is_set():
                self.poll()
                if self.tick:
                    self.tick()
                self.poll_exports()
                self.dispatch()
                self.stop_event.wait(0.05)
        except BaseException:
            self.healthy = False
        finally:
            for active in list(self.active.values()):
                active["event"].set()
            deadline = time.monotonic() + 2
            while self.active and time.monotonic() < deadline:
                self.poll()
                time.sleep(0.02)
            for job_id in list(self.active):
                self.finish(job_id, "interrupted", "SHUTDOWN")

    def dispatch(self):
        used = {lane: sum(a["lane"] == lane for a in self.active.values()) for lane in self.capacity}
        launches = []
        with write_transaction(self.factory) as session:
            queued = session.scalars(
                select(JobRow).where(JobRow.state == "queued").order_by(JobRow.created_at).limit(50)
            ).all()
            for row in queued:
                if row.cancel_requested:
                    row.state, row.stage, row.stopped, row.finished_at = "cancelled", "cancelled", True, now()
                    audit(session, row.dataset_id, "job.stopped", row.id, "coordinator-queued-cancel",
                          state="cancelled", error_code=None, elapsed_seconds=None,
                          elapsed_basis="never_dispatched")
                    continue
                if row.input.get("run_budget") and remaining(row.input["run_budget"], work=True) <= 0:
                    row.state, row.stage, row.error_code = "failed", "budget", "RUN_WORK_BUDGET_EXCEEDED"
                    row.stopped, row.finished_at = True, now()
                    audit(session, row.dataset_id, "job.stopped", row.id, "coordinator-budget",
                          state=row.state, error_code=row.error_code, elapsed_seconds=None)
                    continue
                handler = self.handlers.get(row.kind)
                if handler is None:
                    row.state, row.stage, row.error_code = "failed", "dependency", "SERVICE_NOT_REGISTERED"
                    row.stopped, row.finished_at = True, now()
                    continue
                if handler.lane not in used:
                    row.state, row.error_code, row.stopped = "failed", "INVALID_HANDLER_LANE", True
                    row.finished_at = now()
                    continue
                if used[handler.lane] >= self.capacity[handler.lane]:
                    continue
                row.state, row.stage, row.started_at = "running", "starting", now()
                row.input = {**row.input, "attempt_id": uid()}
                used[handler.lane] += 1
                snapshot = deepcopy(row.input)
                validator = handler.checkpoint_validate or getattr(handler.function, "checkpoint_validator", None)
                candidates = [deepcopy(c.data) for c in session.scalars(select(ObjectRow).where(
                    ObjectRow.dataset_id == row.dataset_id, ObjectRow.kind == "job_checkpoint"))
                    if c.data.get("lineage") == snapshot["checkpoint_lineage"]] if validator else []
                launches.append((row.id, handler, snapshot, validator, candidates))
        for job_id, handler, snapshot, validator, candidates in launches:
            accepted = []
            for candidate in candidates:
                try:
                    valid = validator(snapshot, candidate["row_id"], candidate["fingerprint"], candidate["payload"])
                except Exception:
                    valid = False
                if valid:
                    valid = canonical_hash(candidate["payload"]) == candidate["payload_hash"]
                if valid:
                    accepted.append(candidate)
            row_order = {q["id"]: i for i, q in enumerate(snapshot.get("questions", []))}
            accepted.sort(key=lambda item: (row_order.get(item["row_id"], len(row_order)), item["row_id"]))
            snapshot["accepted_rows"] = accepted
            snapshot["accepted_row_count"] = len(accepted)
            with write_transaction(self.factory) as session:
                row = get_job(session, job_id)
                if row.state != "running" or row.input.get("attempt_id") != snapshot["attempt_id"]:
                    continue
                row.input = {**row.input, "accepted_row_count": len(accepted)}
            receiver, sender = self.context.Pipe(duplex=False)
            event = self.context.Event()
            private = {}
            resolver = self.private_context.get(handler.lane)
            if resolver:
                private = resolver(snapshot)
            process = self.context.Process(
                target=process_entry, args=(sender, event, handler, snapshot, private), daemon=True
            )
            self.active[job_id] = {
                "process": process,
                "receiver": receiver,
                "event": event,
                "lane": handler.lane,
                "deadline": time.monotonic()
                + min(
                    handler.timeout_seconds,
                    snapshot.get("solver_config", {}).get("time_limit_seconds", 3600) + 60
                    if handler.lane == "cpu"
                    else handler.timeout_seconds,
                ),
                "memory_limit_mb": handler.memory_limit_mb,
                "cancel_at": None,
                "snapshot": snapshot,
                "handler": handler,
                "attempt_id": snapshot["attempt_id"],
                "checkpoint_validator": validator,
                "started_monotonic": time.monotonic(),
            }
            if snapshot.get("run_budget"):
                self.active[job_id]["deadline"] = min(self.active[job_id]["deadline"],
                    time.monotonic() + remaining(snapshot["run_budget"], work=True))
            try:
                process.start()
                sender.close()
            except BaseException:
                sender.close()
                self.finish(job_id, "failed", "WORKER_START_FAILED")

    def poll(self):
        for job_id in list(self.active):
            active = self.active[job_id]
            receiver = active["receiver"]
            ended = False
            try:
                # Bound per tick so a noisy process cannot starve cancellation or HTTP writers.
                for _ in range(100):
                    if not receiver.poll():
                        break
                    kind, value = receiver.recv()
                    if kind == "checkpoint":
                        self.accept_checkpoint(job_id, active, value)
                        continue
                    if kind == "incumbent" or (kind == "result" and active["handler"].validate):
                        try:
                            valid = bool(active["handler"].validate and active["handler"].validate(active["snapshot"], value))
                        except Exception:
                            valid = False
                        if not valid:
                            self.finish(job_id, "failed", "INVALID_WORKER_RESULT")
                            ended = True
                            break
                    with write_transaction(self.factory) as session:
                        row = get_job(session, job_id)
                        if row.state != "running" or row.input.get("attempt_id") != active["attempt_id"]:
                            ended = True
                        elif row.input.get("run_budget") and remaining(row.input["run_budget"], work=True) <= 0:
                            row.state, row.stage, row.error_code = "failed", "budget", "RUN_WORK_BUDGET_EXCEEDED"
                            row.stopped, row.finished_at, ended = True, now(), True
                        if ended:
                            pass
                        elif kind == "progress":
                            row.stage, row.completed, row.total = (
                                value["stage"],
                                value["completed"],
                                value["total"],
                            )
                        elif kind == "incumbent":
                            row.last_valid_result = value
                            digest = canonical_hash(value)
                            if row.input.get("last_incumbent_digest") != digest:
                                row.input = {**row.input, "last_incumbent_digest": digest}
                                metrics = {k: v for k, v in value.get("metrics", {}).items()
                                           if v is None or isinstance(v, (str, int, float, bool))}
                                audit(session, row.dataset_id, "job.valid_incumbent", row.id, "coordinator",
                                    result_digest=digest, metrics=metrics,
                                    elapsed_seconds=time.monotonic() - active["started_monotonic"],
                                    elapsed_basis="coordinator_monotonic_since_dispatch")
                        elif kind == "result":
                            if getattr(active["handler"].function, "requires_complete_checkpoints", False):
                                if not self.complete_rows_match(session, row, active["snapshot"], value):
                                    row.state, row.stage, row.error_code = "failed", "checkpoint", "INCOMPLETE_VERIFIED_ROWS"
                                    row.stopped, row.finished_at, ended = True, now(), True
                            hook = self.result_hooks.get(row.kind)
                            if hook is not None and not row.cancel_requested and not ended:
                                try:
                                    with session.begin_nested():
                                        hook(session, row.dataset_id, value)
                                except Exception:
                                    row.state, row.stage, row.error_code = (
                                        "failed",
                                        "persist",
                                        "RESULT_PERSIST_FAILED",
                                    )
                                    row.stopped, row.finished_at, ended = True, now(), True
                            if not ended:
                                if row.input.get("phase") == "improvement":
                                    base = row.input.get("baseline_metrics", {})
                                    current = value.get("metrics", {})
                                    promoted = (current.get("covered_area_mm2", -1), current.get("fully_covered_orders", 0)) > (
                                        base.get("covered_area_mm2", -1), base.get("fully_covered_orders", 0))
                                    value["promotion"] = {"promoted": promoted, "baseline_metrics": base,
                                                          "reason": "strict_primary_secondary_improvement" if promoted else "baseline_preserved"}
                                row.result = value
                                row.state = "cancelled" if row.cancel_requested else "completed"
                                row.stage, row.stopped, row.finished_at = row.state, True, now()
                                ended = True
                        elif kind in {"failed", "cancelled"}:
                            row.state, row.stage = kind, kind
                            row.error_code = value
                            row.stopped, row.finished_at, ended = True, now(), True
                        if ended:
                            audit(session, row.dataset_id, "job.stopped", row.id, "coordinator",
                                state=row.state, error_code=row.error_code,
                                elapsed_seconds=time.monotonic() - active["started_monotonic"],
                                elapsed_basis="coordinator_monotonic_since_dispatch")
                    if ended:
                        self.cleanup(job_id)
                        break
            except (EOFError, OSError):
                pass
            if ended or job_id not in self.active:
                continue
            from glassflow.core.memory import resident_bytes

            used_memory = resident_bytes(active["process"].pid)
            if used_memory is not None and used_memory > active["memory_limit_mb"] * 1024**2:
                self.finish(job_id, "failed", "MEMORY_BUDGET_EXCEEDED")
                continue
            with self.factory() as session:
                cancelled = get_job(session, job_id).cancel_requested
            if cancelled and active["cancel_at"] is None:
                active["event"].set()
                active["cancel_at"] = time.monotonic()
            if active["cancel_at"] is not None and time.monotonic() - active["cancel_at"] > 2:
                self.finish(job_id, "cancelled", None)
            elif time.monotonic() > active["deadline"]:
                self.finish(job_id, "failed", "RUN_WORK_BUDGET_EXCEEDED" if active["snapshot"].get("run_budget") else "JOB_TIMEOUT")
            elif not active["process"].is_alive():
                self.finish(job_id, "failed", "WORKER_EXITED")

    def cleanup(self, job_id):
        active = self.active.pop(job_id)
        process = active["process"]
        if process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            process.close()
        active["receiver"].close()

    def finish(self, job_id, state, error):
        elapsed = time.monotonic() - self.active[job_id]["started_monotonic"]
        self.cleanup(job_id)
        with write_transaction(self.factory) as session:
            row = get_job(session, job_id)
            row.state, row.stage, row.error_code = state, state, error
            row.stopped, row.finished_at = True, now()
            audit(session, row.dataset_id, "job.stopped", row.id, "coordinator",
                  state=state, error_code=error, elapsed_seconds=elapsed,
                  elapsed_basis="coordinator_monotonic_since_dispatch")

    def accept_checkpoint(self, job_id, active, value):
        if value.get("attempt_id") != active["attempt_id"]:
            return  # A late previous attempt cannot fail or modify the current attempt.
        validator = active["checkpoint_validator"]
        valid = False
        try:
            valid = (value["attempt_id"] == active["attempt_id"] and validator is not None and
                     validator(active["snapshot"], value["row_id"], value["fingerprint"], value["payload"]))
        except Exception:
            pass
        if not valid:
            self.finish(job_id, "failed", "INVALID_ACCEPTED_ROW")
            return
        with write_transaction(self.factory) as session:
            row = get_job(session, job_id)
            if (row.state != "running" or row.cancel_requested or row.input.get("attempt_id") != value["attempt_id"]
                    or (row.input.get("run_budget") and remaining(row.input["run_budget"], work=True) <= 0)):
                return
            lineage = row.input["checkpoint_lineage"]
            identity = canonical_hash([lineage, value["row_id"], value["fingerprint"]])
            previous = session.get(ObjectRow, (row.dataset_id, "job_checkpoint", identity))
            digest = canonical_hash(value["payload"])
            if previous:
                if previous.data["payload_hash"] != digest:
                    row.cancel_requested = True
                return
            session.add(ObjectRow(dataset_id=row.dataset_id, kind="job_checkpoint", id=identity,
                version=0, data={"lineage": lineage, "row_id": value["row_id"], "fingerprint": value["fingerprint"],
                    "payload": value["payload"], "payload_hash": digest, "source_job_id": job_id, "accepted_at": now()}))
            row.input = {**row.input, "accepted_row_count": row.input.get("accepted_row_count", 0) + 1}
            audit(session, row.dataset_id, "job.accepted_row", row.id, "coordinator",
                  row_id=value["row_id"], fingerprint=value["fingerprint"], payload_hash=digest,
                  provenance=value["payload"].get("provenance", {}))

    def complete_rows_match(self, session, row, snapshot, result):
        from glassflow.modules.platform.checkpoints import row_fingerprint
        rows = result.get("rows", [])
        expected = {q["id"] for q in snapshot.get("questions", [])}
        if len(rows) != len(expected) or {r.get("id") for r in rows} != expected:
            return False
        for answer in rows:
            fingerprint = row_fingerprint(snapshot, answer["id"])
            identity = canonical_hash([row.input["checkpoint_lineage"], answer["id"], fingerprint])
            record = session.get(ObjectRow, (row.dataset_id, "job_checkpoint", identity))
            if (not record or canonical_hash(record.data["payload"]) != record.data["payload_hash"]
                    or answer != {"id": answer["id"], **record.data["payload"]["row"]}):
                return False
        return True

    def poll_exports(self):
        from glassflow.modules.platform.runs import auto_export_candidates
        if not self.export_context or self.stop_event.is_set():
            return
        if time.monotonic() < self.next_export_scan:
            return
        self.next_export_scan = time.monotonic() + .25
        for run_id, active in list(self.exports.items()):
            if not active["thread"].is_alive():
                del self.exports[run_id]
        if self.exports:
            return
        candidate = auto_export_candidates(self.factory)
        if candidate is None:
            return
        run_id, version, attempt = candidate
        context = self.export_context

        def export():
            from glassflow.modules.platform.exports import export_run
            try:
                export_run(self.factory, run_id, context["data_dir"], context["services"], "budget-auto-export",
                    expected_budget_version=version, budget_attempt_id=attempt,
                    cancel_check=self.stop_event.is_set)
            except Exception:
                with write_transaction(self.factory) as session:
                    row = session.query(ObjectRow).filter_by(kind="run", id=run_id).one()
                    budget = row.data.get("budget", {})
                    if budget.get("export_attempt_id") == attempt:
                        row.data = {**row.data, "budget": {**budget, "export_status": "failed",
                                                         "export_error": "AUTO_EXPORT_FAILED"}}

        thread = threading.Thread(target=export, name="glassflow-budget-export", daemon=True)
        self.exports[run_id] = {"thread": thread}
        thread.start()
