"""Create a new portable working build without replacing any prior release."""

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from scan_release import scan

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "dist/GlassFlow")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    source, target = args.source.resolve(), args.destination.resolve()
    archive = target.with_suffix(".zip")
    if target.exists() or archive.exists():
        raise ValueError("Choose a new version; existing materials are preserved")
    stamp = json.loads((source / "_internal/glassflow/build-info.json").read_text(encoding="utf-8"))
    shutil.copytree(source, target)
    starter = target / "Учебные данные KSM.zip"
    files = [
        "1_ostatki/materials.csv",
        "1_ostatki/stock_open.csv",
        "1_ostatki/orders_open.csv",
        "2_assistant_crm/ksm_knowledge_base.json",
        "2_assistant_crm/questions_open.csv",
        "2_assistant_crm/dialogs_open.csv",
        "2_assistant_crm/applications_open.csv",
    ]
    with zipfile.ZipFile(starter, "w", zipfile.ZIP_DEFLATED) as output:
        for name in files:
            output.write(ROOT / "inputs/PACK_for_teams" / name, Path(name).name)
    with zipfile.ZipFile(starter) as check:
        assert check.testzip() is None and len(check.namelist()) == 7
        for name in files:
            assert check.read(Path(name).name) == (ROOT / "inputs/PACK_for_teams" / name).read_bytes()
    (target / "НАЧАТЬ ЗДЕСЬ.txt").write_text(
        "GlassFlow · команда Vtiposhniki\n\n"
        "1. Распакуйте всю папку и откройте GlassFlow.exe. Дождитесь открытия браузера.\n"
        "2. Для учебного комплекта: Настройки → Данные → выберите «Учебные данные KSM.zip» из этой папки.\n"
        "3. Нажмите «Проверить файлы», задайте название и создайте исходный снимок.\n"
        "4. Создайте рабочую копию кнопкой «Копия» и выберите её. Исходные данные сохраняются.\n"
        "5. Откройте «Рабочее место»: выберите товар, размеры и количество, затем рассчитайте.\n\n"
        "Подтверждение цены, резерв, проверка склада, передача и фактический расход — отдельные действия.\n"
        "Неполный расчёт не считается готовым. Свободный диалог ограничен; доступна форма расчёта по каталогу.\n"
        "Ключей ИИ в поставке нет, денежная оплата автоматически не включается.\n"
        "Для своих данных используйте импорт. Учебный комплект — исходные данные организаторов.\n"
        "Не переносите один EXE отдельно: рядом нужна вся папка _internal.\n"
        "Резервные копии и завершение работы: Настройки → Система.\n"
        "Данные пользователя хранятся отдельно от программы. GlassFlowDiagnostics.exe предназначен для поддержки.\n\n"
        "Это проверенная рабочая версия. Полная конкурсная приёмка, чистая Windows11 и человеческие замеры\n"
        "не объявлены завершёнными. Документация и точные ограничения: https://github.com/Mustiks07/GlassFlow\n",
        encoding="utf-8-sig",
    )
    errors = scan(target)
    if errors:
        raise ValueError("\n".join(errors))
    contents = {p.relative_to(target).as_posix(): sha(p) for p in sorted(target.rglob("*")) if p.is_file()}
    manifest = {
        "runtime_commit": stamp["commit"],
        "source_digest": stamp["source_digest"],
        "file_hashes_except_manifest": contents,
        "status": "working_build_not_full_contest_acceptance",
    }
    (target / "package.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                output.write(path, (Path(target.name) / path.relative_to(target)).as_posix())
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None:
            raise ValueError("Archive CRC failed")
    result = {
        "directory": str(target),
        "archive": str(archive),
        "archive_sha256": sha(archive),
        "archive_bytes": archive.stat().st_size,
        "exe_sha256": sha(target / "GlassFlow.exe"),
        "runtime_commit": stamp["commit"],
        "source_digest": stamp["source_digest"],
        "files": len(contents) + 1,
        "scan": "passed",
        "zip_crc": "passed",
    }
    (archive.with_suffix(".package.json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
