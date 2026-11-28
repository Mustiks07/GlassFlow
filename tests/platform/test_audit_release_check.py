import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from test_reports import synthetic_evidence

from glassflow.core.errors import AppError
from glassflow.modules.platform.release_check import check_bundle
from glassflow.modules.platform.reports import build_reports


def archive(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, value in files.items():
            z.writestr(name, value)
    return out.getvalue()


def test_real_bytes_and_source_hashes_are_checked():
    csv = b'part_id,remnant_id,x_mm,y_mm,rot\r\nP,NEW,,,\r\n'
    source = b'actual source bytes'
    manifest = {'run_id': 'run', 'input_hash': 'inputs', 'source_hashes': {'orders': 'input-source'},
                'result_refs': {}, 'files': {'solution.csv': hashlib.sha256(csv).hexdigest()},
                'build_info': {'files': {'backend/main.py': hashlib.sha256(source).hexdigest()}}}
    files = {'README.md': b'Vtiposhniki', 'code/backend/main.py': source,
             'closed_run/manifest.json': json.dumps(manifest), 'closed_run/solution.csv': csv}
    check = check_bundle(archive(files), manifest)
    assert next(i for i in check.items if i.name == 'CSV и версии прогона').status == 'ready'
    assert next(i for i in check.items if i.name == 'Исходный код').status == 'ready'
    assert not check.files_coherent and not check.contest_accepted
    files['closed_run/solution.csv'] = csv + b'changed'
    files['code/backend/main.py'] = b'wrong version'
    check = check_bundle(archive(files), manifest)
    assert next(i for i in check.items if i.name == 'CSV и версии прогона').status == 'mismatch'
    assert next(i for i in check.items if i.name == 'Исходный код').status == 'mismatch'


def test_missing_and_corrupt_pdfs_are_not_success_or_server_error():
    result = check_bundle(archive({'README.md': 'Vtiposhniki', 'economics.pdf': b'not a PDF'}), {'run_id': 'actual'})
    assert not result.files_coherent
    assert next(i for i in result.items if i.name == 'Экономика PDF').status == 'needs_review'
    with pytest.raises(AppError):
        check_bundle(archive({'../README.md': b'bad'}), {'run_id': 'actual'})


def test_examples_generation_does_not_require_economic_inputs(tmp_path):
    evidence = synthetic_evidence()
    del evidence['economics']
    source = tmp_path / 'synthetic-examples-only.json'
    source.write_text(json.dumps(evidence, ensure_ascii=False), 'utf-8')
    font = next(p for p in (Path('C:/Windows/Fonts/arial.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.exists())
    result = build_reports(source, tmp_path / 'separate', font, preview=True, only='examples')
    assert (tmp_path / 'separate/examples.pdf').is_file()
    assert not (tmp_path / 'separate/economics.pdf').exists()
    assert 'economics' not in result and result['status'] == 'synthetic_layout_preview'
    with pytest.raises(ValueError, match='Synthetic'):
        build_reports(source, tmp_path / 'protected', font, only='examples')
