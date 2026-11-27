import importlib.metadata
import json
import os
import subprocess
from pathlib import Path

rows = []
for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
    metadata = distribution.metadata
    rows.append(
        {
            "name": metadata["Name"],
            "version": distribution.version,
            "declared_license": metadata.get("License-Expression") or metadata.get("License"),
            "license_files": metadata.get_all("License-File") or [],
            "project_urls": metadata.get_all("Project-URL") or [],
            "legal_review": "not_run",
        }
    )
output = Path("docs/release/python-licenses.json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps(
        {
            "scope": "Installed locked all-groups Python environment; metadata only",
            "components": rows,
            "rights_transfer": "Requires separate team agreement; not accepted by this script",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf8",
)
print(f"Recorded {len(rows)} Python components; manual license/rights review remains not_run")
command = (["cmd", "/c"] if os.name == "nt" else []) + ["pnpm", "licenses", "list", "--json"]
frontend = json.loads(subprocess.check_output(command).decode("utf-8-sig"))
for components in frontend.values():
    for component in components:
        component.pop("paths", None)  # Package metadata must not publish developer machine paths.
Path("docs/release/frontend-licenses.json").write_text(
    json.dumps(frontend, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
)
