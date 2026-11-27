"""Durable queue, spawn workers and one coordinator writer. Workers never open SQLite."""
import multiprocessing as mp
import threading
import time
from dataclasses import dataclass

from sqlalchemy import select

from glassflow.contracts.platform import Job
from glassflow.core.errors import AppError
from glassflow.core.models import JobRow, now, uid
from glassflow.core.uow import write_transaction


@dataclass(frozen=True)
class Handler:
    function: object
    lane: str = "cpu"
    validate: object = None
    timeout_seconds: float = 660


class Cancelled(Exception):
    pass


def serialize(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


class ProcessContext:
    def __init__(self, sender, cancelled, snapshot, validator):
        self.sender, self.event, self.snapshot, self.validator = sender, cancelled, snapshot, validator

    def cancelled(self):
        return self.event.is_set()

    def progress(self, stage, completed, total=None):
        if self.cancelled():
            raise Cancelled()
        if completed < 0 or (total is not None and (total < completed or total < 0)):
            raise ValueError("Invalid progress")
        self.sender.send(("progress", {"stage": str(stage)[:100], "completed": completed, "total": total}))

    def incumbent(self, result):
        if self.validator is None or not self.validator(self.snapshot, serialize(result)):
            raise ValueError("Incumbent requires independent validation")
        self.sender.send(("incumbent", serialize(result)))


def process_entry(sender, cancel, handler, snapshot):
    try:
        context = ProcessContext(sender, cancel, snapshot, handler.validate)
        result = serialize(handler.function(snapshot, context))
        if handler.validate is not None and not handler.validate(snapshot, result):
            raise ValueError("Invalid final result")
        sender.send(("result", result))
    except Cancelled:
        sender.send(("cancelled", None))
    except BaseException:
        # No exception text, prompts or secrets cross into persistent diagnostics.
        sender.send(("failed", "WORKER_FAILED"))
    finally:
        sender.close()


def job_dto(row):
    return Job(job_id=row.id, dataset_id=row.dataset_id, run_id=row.run_id, state=row.state, stage=row.stage,
               result_ref=row.id if row.result is not None else None,
               last_valid_result_ref=row.id if row.last_valid_result is not None else None,
               result=row.result, last_valid_result=row.last_valid_result, error_code=row.error_code,
               cancel_requested=row.cancel_requested, stopped=row.stopped, completed=row.completed, total=row.total)


def enqueue(session, dataset_id, kind, snapshot, run_id=None):
    job = JobRow(id=uid(), dataset_id=dataset_id, run_id=run_id, kind=kind, input=snapshot,
                 state="queued", stage="queued", completed=0, cancel_requested=False, stopped=False)
    session.add(job)
    return job


def get_job(session, job_id, dataset_id=None):
    row = session.get(JobRow, job_id)
    if row is None or (dataset_id is not None and row.dataset_id != dataset_id):
        raise AppError(404, "JOB_NOT_FOUND", "Задание не найдено в этом наборе.")
    return row


class Coordinator:
    def __init__(self, factory, handlers, *, network_parallel=2, tick=None, result_hooks=None):
        self.factory, self.handlers = factory, handlers
        self.capacity = {"cpu": 1, "network": network_parallel}
        self.active = {}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="glassflow-coordinator", daemon=True)
        self.context = mp.get_context("spawn")
        self.healthy = True
        self.tick = tick
        self.result_hooks = result_hooks or {}

    def start(self):
        with write_transaction(self.factory) as session:
            for row in session.scalars(select(JobRow).where(JobRow.state.in_(["running", "queued"]))):
                row.state, row.stage = "interrupted", "restart"
                row.error_code, row.stopped, row.finished_at = "PROCESS_RESTARTED", True, now()
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=6)
        self.healthy = False

    def loop(self):
        try:
            while not self.stop_event.is_set():
                self.poll()
                if self.tick:
                    self.tick()
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
            queued = session.scalars(select(JobRow).where(JobRow.state == "queued")
                                     .order_by(JobRow.created_at).limit(50)).all()
            for row in queued:
                if row.cancel_requested:
                    row.state, row.stopped, row.finished_at = "cancelled", True, now()
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
                used[handler.lane] += 1
                launches.append((row.id, handler, row.input))
        for job_id, handler, snapshot in launches:
            receiver, sender = self.context.Pipe(duplex=False)
            event = self.context.Event()
            process = self.context.Process(target=process_entry, args=(sender, event, handler, snapshot), daemon=True)
            self.active[job_id] = {"process": process, "receiver": receiver, "event": event,
                "lane": handler.lane, "deadline": time.monotonic() + handler.timeout_seconds,
                "cancel_at": None}
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
                    with write_transaction(self.factory) as session:
                        row = get_job(session, job_id)
                        if kind == "progress":
                            row.stage, row.completed, row.total = value["stage"], value["completed"], value["total"]
                        elif kind == "incumbent":
                            row.last_valid_result = value
                        elif kind == "result":
                            hook = self.result_hooks.get(row.kind)
                            if hook is not None and not row.cancel_requested:
                                try:
                                    with session.begin_nested():
                                        hook(session, row.dataset_id, value)
                                except Exception:
                                    row.state, row.stage, row.error_code = "failed", "persist", "RESULT_PERSIST_FAILED"
                                    row.stopped, row.finished_at, ended = True, now(), True
                            if not ended:
                                row.result = value
                                row.state = "cancelled" if row.cancel_requested else "completed"
                                row.stage, row.stopped, row.finished_at = row.state, True, now()
                                ended = True
                        elif kind in {"failed", "cancelled"}:
                            row.state, row.stage = kind, kind
                            row.error_code = value
                            row.stopped, row.finished_at, ended = True, now(), True
                    if ended:
                        self.cleanup(job_id)
                        break
            except (EOFError, OSError):
                pass
            if ended or job_id not in self.active:
                continue
            with self.factory() as session:
                cancelled = get_job(session, job_id).cancel_requested
            if cancelled and active["cancel_at"] is None:
                active["event"].set()
                active["cancel_at"] = time.monotonic()
            if active["cancel_at"] is not None and time.monotonic() - active["cancel_at"] > 2:
                self.finish(job_id, "cancelled", None)
            elif time.monotonic() > active["deadline"]:
                self.finish(job_id, "failed", "JOB_TIMEOUT")
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
        self.cleanup(job_id)
        with write_transaction(self.factory) as session:
            row = get_job(session, job_id)
            row.state, row.stage, row.error_code = state, state, error
            row.stopped, row.finished_at = True, now()
