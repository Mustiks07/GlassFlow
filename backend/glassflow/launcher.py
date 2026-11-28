"""Protected desktop entrypoint; also used by the actual frozen worker smoke."""

import argparse
import json
import multiprocessing as mp
import os
import runpy
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from glassflow.core.db import default_data_dir
from glassflow.core.resources import resource_root


class AlreadyRunningError(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, directory, filename="instance.lock"):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / filename
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise AlreadyRunningError("GlassFlow уже запущен для этой базы.") from None
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()


def native_worker(sender):
    try:
        from ortools.sat.python import cp_model
        from scipy.optimize import Bounds, milp

        scipy_result = milp(c=[-1.0], integrality=[1], bounds=Bounds([0], [2]))
        model = cp_model.CpModel()
        x = model.new_int_var(0, 2, "x")
        model.maximize(x)
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        status = solver.solve(model)
        sender.send(
            {
                "scipy_x": int(round(scipy_result.x[0])),
                "ortools_x": solver.value(x),
                "ortools_optimal": status == cp_model.OPTIMAL,
                "frozen_worker": bool(getattr(sys, "frozen", False)),
                "worker_executable": Path(sys.executable).name,
                "pid": os.getpid(),
            }
        )
    except BaseException:
        sender.send({"error": "NATIVE_WORKER_FAILED"})
    finally:
        sender.close()


def smoke_native():
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=native_worker, args=(sender,))
    process.start()
    sender.close()
    try:
        if not receiver.poll(60):
            raise RuntimeError("Native worker timed out")
        result = receiver.recv()
        process.join(timeout=10)
        if result.get("scipy_x") != 2 or result.get("ortools_x") != 2 or not result.get("ortools_optimal"):
            raise RuntimeError("Native worker failed")
        return result
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
        process.close()
        receiver.close()


def official_validator(directory):
    path = Path(directory).resolve()
    if not all(
        (path / n).is_file()
        for n in ("input-stock.csv", "input-orders.csv", "solution.csv", "input-materials.csv")
    ):
        raise RuntimeError("Validator input files missing")
    script = resource_root() / "inputs/PACK_for_teams/1_ostatki/validate.py"
    sys.argv = [
        str(script),
        str(path / "input-stock.csv"),
        str(path / "input-orders.csv"),
        str(path / "solution.csv"),
        str(path / "input-materials.csv"),
    ]
    runpy.run_path(str(script), run_name="__main__")


def serve(data_dir, no_browser=False, port=0):
    import uvicorn

    from glassflow.main import create_app

    with InstanceLock(data_dir):
        app = create_app(data_dir)
        # The bound socket stays open: another process cannot claim it between probing and startup.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        actual_port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=actual_port, log_level="warning", access_log=False)
        )
        app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
        origin = f"http://127.0.0.1:{actual_port}"
        (data_dir / "launch.json").write_text(
            json.dumps({"port": actual_port, "pid": os.getpid()}), encoding="utf8"
        )

        def open_when_ready():
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not server.should_exit:
                try:
                    with urllib.request.urlopen(origin + "/api/v1/ready", timeout=1) as response:
                        ready = json.load(response)
                    if ready["database"] and ready["schema"] and ready["worker"]:
                        if not no_browser:
                            webbrowser.open(origin)
                        return
                except (OSError, ValueError):
                    time.sleep(0.1)
            server.should_exit = True
            print("Не удалось запустить локальное ядро GlassFlow за 30 секунд.", file=sys.stderr)

        opener = threading.Thread(target=open_when_ready, daemon=True)
        opener.start()
        try:
            server.run(sockets=[listener])
        finally:
            listener.close()
            (data_dir / "launch.json").unlink(missing_ok=True)


def main():
    mp.freeze_support()
    if os.name == "nt" and getattr(sys, "frozen", False):
        gui_executable = Path(sys.executable).with_name("GlassFlow.exe")
        if gui_executable.is_file():
            mp.set_executable(str(gui_executable))
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf8", errors="replace")
        sys.stderr.reconfigure(encoding="utf8", errors="replace")
    parser = argparse.ArgumentParser(prog="GlassFlow")
    parser.add_argument("--smoke-native-worker", action="store_true")
    parser.add_argument("--official-validator", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.smoke_native_worker:
        print(json.dumps(smoke_native()))
    elif args.official_validator:
        official_validator(args.official_validator)
    else:
        if not (resource_root() / "apps/web/dist/index.html").is_file():
            raise RuntimeError("Не найден интерфейс. Выполните pnpm build перед упаковкой.")
        try:
            serve(default_data_dir(), args.no_browser, args.port)
        except AlreadyRunningError:
            info = default_data_dir() / "launch.json"
            if info.is_file() and not args.no_browser:
                port = json.loads(info.read_text(encoding="utf8"))["port"]
                webbrowser.open(f"http://127.0.0.1:{int(port)}")
            print("GlassFlow уже работает. Второй экземпляр над базой не запущен.")


if __name__ == "__main__":
    main()
