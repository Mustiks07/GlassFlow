import json
from pathlib import Path

from glassflow.main import create_app

root = Path(__file__).resolve().parents[1]
target = root / "packages/contracts/openapi.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target.relative_to(root))
