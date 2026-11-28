"""Run the identical changed-input HTTP protocol against actual Windows executables.

Only process startup differs from post_acceptance. All domain requests, exports,
official validation, deadlines, cancellation and restart checks remain real.
"""

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import post_acceptance as protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18684)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.exe, args.data, args.output = args.exe.resolve(), args.data.resolve(), args.output.resolve()
    if args.exe.read_bytes()[:2] != b"MZ":
        raise ValueError("An actual Windows executable is required")
    stamp = json.loads((args.exe.parent / "_internal/glassflow/build-info.json").read_text(encoding="utf-8"))

    class FrozenService(protocol.Service):
        def start(self):
            env = {
                k: v
                for k, v in os.environ.items()
                if not re.search(
                    r"API_KEY|TOKEN|SECRET|GEMINI|BASISWEB|OPENROUTER|OPENAI|AI_PROFILE|PYTHONPATH|PYTHONHOME",
                    k,
                    re.I,
                )
            }
            env.update(GLASSFLOW_DATA_DIR=str(self.data), PYTHONUTF8="1")
            self.data.mkdir(parents=True, exist_ok=True)
            self.log = (self.data / "frozen-host.log").open("ab")
            self.process = subprocess.Popen(
                [str(args.exe), "--no-browser", "--port", str(self.port)],
                cwd=args.exe.parent,
                env=env,
                stdout=self.log,
                stderr=self.log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            with httpx.Client(trust_env=False, timeout=2) as client:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise RuntimeError("Frozen host exited before readiness; inspect frozen-host.log")
                    try:
                        response = client.get(f"http://127.0.0.1:{self.port}/api/v1/ready")
                        if response.status_code == 200 and response.json()["business_modules_ready"]:
                            return
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(0.2)
            raise RuntimeError("Frozen host failed readiness")

    protocol.Service = FrozenService
    report = {
        "source_sha": stamp["commit"],
        "runtime_source_digest": stamp["source_digest"],
        "exe_sha256": protocol.digest(args.exe.read_bytes()),
        "transport": "actual_windows_exe_tcp",
        "clean_windows": "not_run",
        "human_measurements": "not_run",
        "online_ai": "not_run",
        "official_hidden_accuracy": "not_run_no_changed_input_KEY",
        "status": "running",
    }
    begin = time.monotonic()
    try:
        protocol.exercise(args, report)
    except Exception as exc:
        report.update(status="failed", failure=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report["total_observer_seconds"] = round(time.monotonic() - begin, 3)
        protocol.write_json(args.output / "report.json", report)
        print(json.dumps({k: report[k] for k in ("status", "source_sha", "total_observer_seconds")}))
    if report["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
