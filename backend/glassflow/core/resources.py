import json
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
    return {"commit": "development_unstamped", "source_digest": None, "frozen": False}
