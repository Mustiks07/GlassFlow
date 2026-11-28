"""Read-only checking of the actual uploaded contest ZIP; no extraction or execution."""

import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from glassflow.contracts.economics import EconomicInputs
from glassflow.contracts.release import ReleaseCheck, ReleaseCheckItem
from glassflow.core.errors import AppError
from glassflow.modules.platform.economics import serialized_result


def check_bundle(raw, expected_manifest):
    items = []

    def item(name, status, message):
        items.append(ReleaseCheckItem(name=name, status=status, message=message))

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > 200_000_000:
            raise ValueError("limits")
        names = [i.filename for i in infos if not i.is_dir()]
        if len({n.casefold() for n in names}) != len(names) or any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts or "\\" in n for n in names):
            raise ValueError("paths")
        # A single outer folder from ordinary Windows ZIP creation is allowed.
        prefix = names[0].split('/')[0] + '/' if names and all('/' in n and n.split('/')[0] == names[0].split('/')[0] for n in names) else ''
        files = {n.removeprefix(prefix): archive.read(n) for n in names}
    except (ValueError, OSError, RuntimeError, zipfile.BadZipFile):
        raise AppError(422, "RELEASE_ZIP_INVALID", "Нужен ZIP без повторных/опасных путей, до 10000 файлов и 200 МБ после распаковки.") from None
    if 'README.md' not in files:
        item('README', 'missing', 'Добавьте итоговую инструкцию с названием команды.')
    else:
        text = files['README.md'].decode('utf-8-sig', errors='replace')
        valid = 'Vtiposhniki' in text and 'TEAM_NAME_REQUIRED' not in text
        item('README', 'ready' if valid else 'mismatch', 'Инструкция и имя команды найдены.' if valid else 'Проверьте имя команды и незаполненные поля.')
    code = [n for n in files if n.startswith('code/')]
    secret = any(n.endswith('.env') or '_KEY.' in n or n.endswith(('.db', '.key')) for n in files)
    secret = secret or any(re.search(rb"sk-pl-[a-zA-Z0-9]{24,}|ghp_[a-zA-Z0-9]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", raw) for raw in files.values())
    pinned = expected_manifest.get('build_info', {}).get('files', {})
    source_matches = bool(pinned) and all('code/' + n in files and hashlib.sha256(files['code/' + n]).hexdigest() == h for n, h in pinned.items())
    item('Исходный код', 'mismatch' if secret or (code and pinned and not source_matches) else 'ready' if code and source_matches else 'needs_review' if code else 'missing',
         'В архиве обнаружены запрещённые локальные файлы.' if secret else 'Исходники и production assets совпадают с хешами принятого прогона.' if source_matches else 'Добавьте исходники и production assets именно выбранной версии; хеши должны совпасть с паспортом.')
    try:
        manifest = json.loads(files['closed_run/manifest.json'])
        if not isinstance(manifest, dict):
            raise ValueError("manifest object")
        same = all(manifest.get(k) == expected_manifest.get(k) for k in ('run_id', 'input_hash', 'source_hashes', 'result_refs'))
        hashes = all(hashlib.sha256(files['buyers_top50.csv' if n == 'buyers_top50.csv' else 'closed_run/' + n]).hexdigest() == h
                     for n, h in expected_manifest['files'].items())
        item('CSV и версии прогона', 'ready' if same and hashes else 'mismatch',
             'Пять CSV и реестр побайтно соответствуют выбранному принятому результату.' if same and hashes else 'Файлы, входы или версии не совпадают с выбранным прогоном.')
    except (KeyError, ValueError, TypeError):
        item('CSV и версии прогона', 'missing', 'Нужны manifest и пять CSV в closed_run, buyers_top50.csv в корне.')
    try:
        report = json.loads(files['report-build.json'])
        evidence = json.loads(files['report-evidence.json'])
        if not isinstance(report, dict) or not isinstance(evidence, dict):
            raise ValueError("report objects")
        bound = evidence['manifest']['run_id'] == expected_manifest['run_id'] and evidence['manifest']['source_hashes'] == expected_manifest['source_hashes']
        for name, title in (('examples.pdf', 'Примеры PDF'), ('economics.pdf', 'Экономика PDF')):
            if name not in files:
                item(title, 'missing', 'Файл отсутствует.')
                continue
            ok = bound and hashlib.sha256(files[name]).hexdigest() == report.get('files', {}).get(name)
            reader = PdfReader(io.BytesIO(files[name]))
            if name == 'economics.pdf':
                inputs = EconomicInputs.model_validate(evidence['economics'])
                ok = ok and len(reader.pages) == 1 and inputs.measurement_status == 'supplied_measurements'
                ok = ok and report.get('economics') == serialized_result(inputs.model_dump(mode='json'))
            ok = ok and report.get('visual_review') == 'passed' and not evidence.get('synthetic')
            item(title, 'ready' if ok else 'mismatch', 'Хеши, версии и проверка документа согласованы.' if ok else 'Сверьте источники, расчёт, хеш PDF и отметку визуального просмотра.')
    except (KeyError, ValueError, TypeError, PyPdfError):
        for name, title in (('examples.pdf', 'Примеры PDF'), ('economics.pdf', 'Экономика PDF')):
            if not any(i.name == title for i in items):
                item(title, 'needs_review' if name in files else 'missing', 'Нужны сам PDF, report-build.json и report-evidence.json с проверяемым происхождением.')
    coherent = all(i.status == 'ready' for i in items)
    item('Закрытый набор и внешняя приёмка', 'needs_review',
         'Совпадение файлов не доказывает официальный закрытый набор, live ИИ, человеческие измерения и самостоятельный запуск. Эти проверки подтверждаются отдельно.')
    return ReleaseCheck(run_id=expected_manifest['run_id'], items=items, files_coherent=coherent)
