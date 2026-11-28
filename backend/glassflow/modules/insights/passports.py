"""Run provenance; accepted passports use pinned artifacts, never latest jobs."""

import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from glassflow.contracts.insights import ResultPassport
from glassflow.core.errors import AppError
from glassflow.core.models import AuditRow, JobRow
from glassflow.modules.platform.runs import find_run, latest_jobs, run_view


def passport(session, data_dir, run_id, dataset_id, view):
    run = find_run(session, run_id)
    manifest = dict(run.data)
    if dataset_id not in {run.dataset_id, manifest.get("source_dataset_id")}:
        raise AppError(404, "RUN_NOT_FOUND", "Прогон не относится к выбранному набору.")
    export_id = None
    if view == "accepted":
        export_id = manifest.get("accepted_export_id")
        if not export_id:
            raise AppError(409, "ACCEPTED_EXPORT_UNAVAILABLE", "Полный принятый комплект ещё не сохранён.")
        root = (Path(data_dir) / "exports" / run_id).resolve()
        directory = (root / export_id).resolve()
        if directory.parent != root:
            raise AppError(409, "EXPORT_INTEGRITY", "Неверная ссылка на экспорт.")
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("files") != run.data.get("accepted_files"):
                raise ValueError("accepted file reference")
            if (
                manifest.get("run_id") != run_id
                or manifest.get("export_id") != export_id
                or manifest.get("dataset_id") != run.dataset_id
                or manifest.get("status") != "ready"
            ):
                raise ValueError("manifest scope")
            for name, expected in manifest["files"].items():
                file = (directory / name).resolve()
                if file.parent != directory or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                    raise ValueError("artifact hash")
            refs = manifest["result_refs"]
            jobs = []
            for module, ref in refs.items():
                job = session.get(JobRow, ref["job_id"])
                if job is None or job.run_id != run_id or job.kind != module:
                    raise ValueError("job scope")
                jobs.append(job)
        except (OSError, ValueError, KeyError, TypeError):
            raise AppError(
                409,
                "EXPORT_INTEGRITY",
                "Файлы или паспорт принятого комплекта не прошли проверку целостности.",
            ) from None
        status = manifest["status"]
    else:
        jobs = list(latest_jobs(session, run_id).values())
        status = run_view(session, run_id)["status"]
    modules = []
    for job in jobs:
        result = job.result or job.last_valid_result or {}
        events = list(
            session.scalars(
                select(AuditRow)
                .where(
                    AuditRow.dataset_id == job.dataset_id,
                    AuditRow.object_id == job.id,
                    AuditRow.action.in_(["job.valid_incumbent", "job.stopped"]),
                )
                .order_by(AuditRow.id)
            )
        )
        history = [{"action": e.action, "created_at": e.created_at, **e.versions} for e in events]
        modules.append(
            {
                "module": job.kind,
                "job_id": job.id,
                "state": job.state,
                "stage": job.stage,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "error_code": job.error_code,
                "stop_reason": result.get("stop_reason"),
                "metrics": result.get("metrics"),
                "history": history,
                "history_available": any(e.action == "job.valid_incumbent" for e in events),
                "provenance": manifest.get("module_provenance", {}).get(job.kind),
            }
        )
    return ResultPassport(
        dataset_id=run.dataset_id,
        run_id=run_id,
        view=view,
        export_id=export_id,
        status=status,
        manifest=manifest,
        files=manifest.get("files", {}),
        validators=manifest.get("validators", []),
        modules=modules,
        history_available=any(m["history_available"] for m in modules),
    )
