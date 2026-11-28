"""Repeat all real browser suites against the actual EXE, with isolated databases."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
from audit_final_series import Frozen
from post_acceptance import ROOT, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=19821)
    args = parser.parse_args()
    if args.output.exists() or args.data.exists():
        raise ValueError('Use new directories; preserve previous evidence')
    args.output.mkdir(parents=True)
    report = dict(transport='actual_windows_exe_browser', status='running',
                  human_labor='not_run', clean_windows='not_run', suites={})
    configs = [('audit', 4), ('real', 10), ('integrated', 2), ('post', 4)]
    try:
        for index, (name, count) in enumerate(configs):
            port = args.port + index
            service = Frozen(args.data.resolve() / name, port, args.exe.resolve())
            service.start()
            try:
                env = dict(os.environ, GLASSFLOW_E2E_URL=f'http://127.0.0.1:{port}')
                with (args.output / f'{name}.log').open('wb') as log:
                    result = subprocess.run(['pnpm.cmd' if os.name == 'nt' else 'pnpm', '--filter',
                        '@glassflow/web', 'exec', 'playwright', 'test', '--config', f'playwright.{name}.config.ts'],
                        cwd=ROOT, env=env, stdout=log, stderr=log)
                raw = ROOT / f'tests/e2e/.results/{name}-report.json'
                shutil.copy2(raw, args.output / f'{name}-report.json')
                stats = json.loads(raw.read_text('utf-8'))['stats']
                report['suites'][name] = stats
                if result.returncode or stats['expected'] != count or stats['unexpected'] or stats['skipped']:
                    raise RuntimeError(f'{name} failed: inspect preserved log and report')
                print(name, count, 'passed', flush=True)
            finally:
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as client:
                    service.stop(client)
        report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        write_json(args.output / 'report.json', report)


if __name__ == '__main__':
    main()
