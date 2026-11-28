"""Check a real open-pack review ZIP in the EXE browser; never call it a closed submission."""

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import httpx
from audit_final_series import Frozen
from post_acceptance import ROOT, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('exe', 'data', 'series', 'reports', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--port', type=int, default=19860)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output directory; preserve prior materials')
    args.output.mkdir(parents=True)
    series = json.loads((args.series / 'series.json').read_text('utf-8'))
    assert series['status'] == 'passed'
    manifest = series['selected']['manifest']
    source_id, run_id = series['source']['dataset_id'], manifest['run_id']
    files = {'README.md': (
        '# GlassFlow — Vtiposhniki\n\n'
        'Аудиторский комплект на неизменённом открытом наборе. Это не официальная закрытая сдача.\n'
        'CSV и examples.pdf получены из настоящего EXE. Человеческие трудозамеры и экономика\n'
        'не подменены синтетикой; economics.pdf отсутствует. Каталог closed_run используется\n'
        'только для проверки структуры конкурсного ZIP. Live AI и внешняя приёмка не завершены.\n'
    ).encode('utf-8')}
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    prefixes = ('backend/', 'apps/web/', 'packages/', 'packaging/', 'scripts/', 'infra/', 'inputs/', 'data/')
    for name in tracked:
        if not name or '_KEY.' in name or name.endswith('.env'):
            continue
        if name.startswith(prefixes) or name in {'README.md', 'LICENSE', 'pyproject.toml', 'uv.lock', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', 'package.json'}:
            files['code/' + name] = subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=ROOT)
    for name, expected in manifest['build_info']['files'].items():
        raw = (ROOT / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Actual source/assets differ from the accepted build: ' + name)
        files['code/' + name] = raw
    for name, expected in manifest['files'].items():
        raw = (args.series / 'selected/downloaded' / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        files['buyers_top50.csv' if name == 'buyers_top50.csv' else 'closed_run/' + name] = raw
    files['closed_run/manifest.json'] = (args.series / 'selected/downloaded/manifest.json').read_bytes()
    for name in ('examples.pdf', 'report-build.json', 'report-evidence.json'):
        files[name] = (args.reports / name).read_bytes()
    archives = {}
    for variant in ('actual-open-review', 'intentionally-changed-csv'):
        target = args.output / (variant + '.zip')
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in files.items():
                archive.writestr(name, raw + b'\r\n' if variant.startswith('intentionally') and name == 'closed_run/solution.csv' else raw)
        archives[variant] = target
    service = Frozen(args.data.resolve(), args.port, args.exe.resolve())
    service.start()
    try:
        env = dict(os.environ, GLASSFLOW_E2E_URL=f'http://127.0.0.1:{args.port}',
                   GLASSFLOW_AUDIT_DATASET=source_id, GLASSFLOW_AUDIT_RUN=run_id,
                   GLASSFLOW_AUDIT_ZIP=str(archives['actual-open-review'].resolve()),
                   GLASSFLOW_AUDIT_CHANGED_ZIP=str(archives['intentionally-changed-csv'].resolve()))
        with (args.output / 'browser.log').open('wb') as log:
            result = subprocess.run(['pnpm.cmd' if os.name == 'nt' else 'pnpm', '--filter', '@glassflow/web',
                'exec', 'playwright', 'test', '--config', 'playwright.release.config.ts'], cwd=ROOT, env=env, stdout=log, stderr=log)
        browser = json.loads((ROOT / 'tests/e2e/.results/release-readiness-report.json').read_text('utf-8'))
        write_json(args.output / 'browser-report.json', browser)
        with httpx.Client(base_url=f'http://127.0.0.1:{args.port}', trust_env=False, timeout=30) as client:
            client.get('/api/v1/session').raise_for_status()
            for name, archive in archives.items():
                response = client.post(f'/api/v1/runs/{run_id}/release-check', files={'file': (archive.name, archive.read_bytes())})
                response.raise_for_status()
                write_json(args.output / (name + '.json'), response.json())
                assert not response.json()['contest_accepted'] and not response.json()['files_coherent']
        if result.returncode or browser['stats']['unexpected'] or browser['stats']['expected'] != 1:
            raise RuntimeError('Actual bundle browser check failed; inspect preserved evidence')
        print('Actual ZIP source/CSV/examples match; missing economics and tampered CSV remain blocked')
    finally:
        with httpx.Client(base_url=f'http://127.0.0.1:{args.port}', trust_env=False, timeout=5) as client:
            service.stop(client)


if __name__ == '__main__':
    main()
