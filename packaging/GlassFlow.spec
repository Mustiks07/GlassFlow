# Build on Windows x64 after pnpm build. No secrets, KEY, user models or runtime DB.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parent
web = root / "apps/web/dist"
if not (web / "index.html").is_file():
    raise RuntimeError("Missing production frontend; run pnpm build")
sources = ["1_ostatki/materials.csv", "1_ostatki/stock_open.csv", "1_ostatki/orders_open.csv",
           "1_ostatki/validate.py", "2_assistant_crm/ksm_knowledge_base.json",
           "2_assistant_crm/applications_open.csv", "2_assistant_crm/questions_open.csv", "2_assistant_crm/dialogs_open.csv"]
datas = [(str(web), "apps/web/dist"),
         (str(root / "backend/glassflow/core/migrations"), "glassflow/core/migrations")]
for relative in sources:
    datas.append((str(root / "inputs/PACK_for_teams" / relative), "inputs/PACK_for_teams/" + str(Path(relative).parent)))
for package in ("sqlalchemy", "pydantic", "scikit-learn", "scipy", "ortools"):
    datas.extend(copy_metadata(package))
hidden = collect_submodules("glassflow") + ["scipy.optimize", "ortools.sat.python.cp_model",
    "sklearn.linear_model", "sklearn.compose", "sklearn.preprocessing", "sklearn.pipeline", "sklearn.model_selection",
    "alembic.ddl.sqlite", "sqlalchemy.dialects.sqlite"]
a = Analysis([str(root / "packaging/entrypoint.py")], pathex=[str(root / "backend")],
             binaries=[], datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GlassFlow", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GlassFlow")
