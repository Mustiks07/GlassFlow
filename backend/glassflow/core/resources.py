import hashlib
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def resource_root():
    return Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]


@lru_cache
def build_info():
    path = resource_root() / "glassflow/build-info.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf8"))
    root = resource_root()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                         stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        commit = "development_unstamped"
    files = sorted([*root.joinpath("backend").rglob("*.py"), *root.joinpath("apps/web/dist").rglob("*")])
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
    return {"commit": commit, "source_digest": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), "frozen": False}
