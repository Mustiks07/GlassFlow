# Build on Windows x64 after pnpm build. No secrets, KEY, user models or runtime DB.
from pathlib import Path
import hashlib
import json
import subprocess
from PyInstaller.utils.hooks import collect_submodules, copy_metadata, collect_dynamic_libs

root = Path(SPECPATH).parent
web = root / "apps/web/dist"
if not (web / "index.html").is_file():
    raise RuntimeError("Missing production frontend; run pnpm build")
sources = ["1_ostatki/materials.csv", "1_ostatki/stock_open.csv", "1_ostatki/orders_open.csv",
           "1_ostatki/validate.py", "2_assistant_crm/ksm_knowledge_base.json",
           "2_assistant_crm/applications_open.csv", "2_assistant_crm/questions_open.csv", "2_assistant_crm/dialogs_open.csv"]
datas = [(str(web), "apps/web/dist"),
         (str(root / "backend/glassflow/core/migrations"), "glassflow/core/migrations")]
runtime_files = sorted([*root.joinpath("backend").rglob("*.py"), *web.rglob("*")])
source_hashes = {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in runtime_files if p.is_file()}
for name in ("uv.lock", "pnpm-lock.yaml", "pyproject.toml"):
    source_hashes[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
stamp = root / "build/build-info.json"
stamp.parent.mkdir(parents=True, exist_ok=True)
stamp.write_text(json.dumps({"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
    "source_digest": hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest(),
    "files": source_hashes, "frozen": True}, indent=2), encoding="utf8")
datas.append((str(stamp), "glassflow"))
for domain in ("cutting", "intelligence"):
    migrations = root / f"backend/glassflow/modules/{domain}/migrations"
    if migrations.is_dir():
        datas.append((str(migrations), f"glassflow/modules/{domain}/migrations"))
for relative in sources:
    datas.append((str(root / "inputs/PACK_for_teams" / relative), "inputs/PACK_for_teams/" + str(Path(relative).parent)))
for package in ("sqlalchemy", "pydantic", "scikit-learn", "scipy", "ortools"):
    datas.extend(copy_metadata(package))
hidden = collect_submodules("glassflow", filter=lambda name: not name.startswith("glassflow.modules.intelligence.evaluation")) + ["scipy.optimize", "ortools.sat.python.cp_model",
    "sklearn.linear_model", "sklearn.compose", "sklearn.preprocessing", "sklearn.pipeline", "sklearn.model_selection",
    "alembic.ddl.sqlite", "sqlalchemy.dialects.sqlite"]
hidden += collect_submodules("reportlab.graphics.barcode")
a = Analysis([str(root / "packaging/entrypoint.py")], pathex=[str(root / "backend")],
             binaries=collect_dynamic_libs("ortools"), datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook", "glassflow.modules.intelligence.evaluation"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GlassFlow", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
diagnostics = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GlassFlowDiagnostics", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, diagnostics, a.binaries, a.datas, strip=False, upx=False, name="GlassFlow")
