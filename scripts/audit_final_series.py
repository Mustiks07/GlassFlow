"""Comparable original-open-pack runs and examples from actual frozen services.

No KEY, model, synthetic labor, direct database mutation or organizer-code edits.
The two declared profiles and every accepted result are preserved separately.
"""

import argparse
import csv
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from post_acceptance import INPUTS, PACK, Service, digest, download, import_source, post, write_json


class Frozen(Service):
    def __init__(self, data, port, exe):
        super().__init__(data, port)
        self.exe = exe

    def start(self):
        with socket.socket() as probe:
            probe.settimeout(.5)
            if probe.connect_ex(('127.0.0.1', self.port)) == 0:
                raise RuntimeError('Refusing to touch an existing listener')
        env = {k: v for k, v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET|PYTHONPATH|PYTHONHOME", k, re.I)}
        env.update(GLASSFLOW_DATA_DIR=str(self.data), PYTHONUTF8="1")
        self.data.mkdir(parents=True, exist_ok=True)
        self.log = (self.data / 'host.log').open('ab')
        self.process = subprocess.Popen([str(self.exe), '--no-browser', '--port', str(self.port)],
            cwd=self.exe.parent, env=env, stdout=self.log, stderr=self.log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Owned EXE exited before readiness')
            try:
                r = httpx.get(f'http://127.0.0.1:{self.port}/api/v1/ready', trust_env=False, timeout=2)
                if r.status_code == 200 and r.json()['business_modules_ready']:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        raise RuntimeError('Frozen readiness timeout')


def read_csv(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline='')))


def run_profile(client, source, buyer, config, output, budget):
    started = time.monotonic()
    task = post(client, '/runs', dict(dataset_id=source['dataset_id'], config_version='audit-c6-original-open-v1',
        buyer_registry_version=buyer['version'], ai_profile='local_limited', solver_config=config,
        total_budget_seconds=budget, export_reserve_seconds=15 if budget < 60 else 30))
    first_ready = None
    report_at = 0
    while time.monotonic() - started < budget + 80:
        view = client.get('/api/v1/runs/' + task['run_id']).json()
        elapsed = time.monotonic() - started
        if view['manifest'].get('accepted_export_id') and first_ready is None:
            first_ready = elapsed
        if elapsed - report_at >= 20:
            print(config['profile'], round(elapsed, 1), 'seconds', [(j.get('stage', ''), j.get('state', '')) for j in view['jobs']], flush=True)
            report_at = elapsed
        if view['status'] != 'running':
            break
        time.sleep(.5)
    else:
        raise RuntimeError('Run observer deadline exceeded')
    exported = post(client, f"/runs/{task['run_id']}/export")
    if exported['status'] != 'ready':
        raise RuntimeError(f'Actual export is not ready: {exported}')
    files = download(client, exported, output / 'downloaded')
    manifest = json.loads((output / 'downloaded/manifest.json').read_text('utf-8'))
    cut_job = client.get('/api/v1/jobs/' + manifest['result_refs']['cutting']['job_id']).json()
    official = PACK / '1_ostatki/validate.py'
    validated = subprocess.run([sys.executable, '-X', 'utf8', str(official), str(PACK / '1_ostatki/stock_open.csv'),
        str(PACK / '1_ostatki/orders_open.csv'), str(output / 'downloaded/solution.csv'), str(PACK / '1_ostatki/materials.csv')],
        capture_output=True, encoding='utf-8', timeout=30)
    if validated.returncode or not re.search(r'RESULT coverage=[0-9.]+ invalid=0 ', validated.stdout) or 'не указано в решении: 0' not in validated.stdout:
        raise RuntimeError(validated.stdout + validated.stderr)
    result = dict(run_id=task['run_id'], dataset_id=manifest['dataset_id'], config=config, total_budget_seconds=budget,
        first_ready_seconds=round(first_ready, 3) if first_ready else None, elapsed_seconds=round(time.monotonic() - started, 3),
        view=view, manifest=manifest, files=files, accepted_cutting=cut_job,
        validator=dict(exit_code=validated.returncode, stdout=validated.stdout, stderr=validated.stderr, sha256=digest(official.read_bytes())))
    write_json(output / 'report.json', result)
    return result


def examples(client, selected, source, input_bytes, destination):
    manifest = selected['manifest']
    d, run_id = manifest['dataset_id'], manifest['run_id']
    plan = selected['accepted_cutting']['result']
    stock = {r['remnant_id']: r for r in read_csv(input_bytes['stock_open.csv'])}
    parts = {r['part_id']: r for r in read_csv(input_bytes['orders_open.csv'])}
    allocated = defaultdict(list)
    for placement in plan['placements']:
        if placement['remnant_id'] != 'NEW':
            allocated[placement['remnant_id']].append(placement)
    cutting = []
    for remnant_id in sorted(allocated, key=lambda r: (len(allocated[r]), r))[:3]:
        remnant = stock[remnant_id]
        placements = [{**p, 'length_mm': int(parts[p['part_id']]['длина_мм']), 'width_mm': int(parts[p['part_id']]['ширина_мм'])} for p in allocated[remnant_id]]
        cutting.append(dict(dataset_id=d, run_id=run_id, source_ref=f"plan:{plan['plan_id']}@{plan['revision']}#{remnant_id}",
            remnant_id=remnant_id, length_mm=int(remnant['длина_мм']), width_mm=int(remnant['ширина_мм']), placements=placements,
            description=f"Открытый набор организаторов. {remnant['место']}. Деталей на куске: {len(placements)}; координаты приняты официальным валидатором."))
    directory = destination / 'selected/downloaded'
    questions = {r['id']: r['question'] for r in read_csv(input_bytes['questions_open.csv'])}
    answers = [dict(dataset_id=d, run_id=run_id, source_ref=f"questions_open.csv#{r['id']};job:{manifest['result_refs']['assistant']['job_id']}",
                    question=questions[r['id']], answer=r['answer']) for r in read_csv((directory / 'answers.csv').read_bytes())[:3]]
    dialogs = {r['id']: r for r in read_csv(input_bytes['dialogs_open.csv'])}
    quality = [dict(dataset_id=d, run_id=run_id, source_ref=f"dialogs_open.csv#{r['id']};job:{manifest['result_refs']['quality']['job_id']}",
                   client=dialogs[r['id']]['client'], manager=dialogs[r['id']]['manager'], verdict=r['verdict'], correct=r['correct'])
               for r in read_csv((directory / 'verdicts.csv').read_bytes())[:3]]
    working = post(client, f"/datasets/{source['dataset_id']}/working-copy", {'name': 'Реальные локальные примеры напоминаний по открытому набору'})
    ranked = post(client, '/crm/rank', {'dataset_id': working['dataset_id'], 'policy': 'reference'})
    apps = {r['app_id']: r for r in read_csv(input_bytes['applications_open.csv'])}
    reminders, seen = [], set()
    for row in ranked['rows']:
        if row['client_id'] in seen:
            continue
        seen.add(row['client_id'])
        group = apps[row['app_id']]['группа_товара']
        r = post(client, '/crm/reminders', dict(dataset_id=working['dataset_id'], recipient_client_id=row['client_id'],
            source_app_ids=[row['app_id']], subject_type='interest', subject_ref=group,
            due_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(), owner=apps[row['app_id']]['manager'] or 'менеджер',
            text=f'Уточнить актуальный интерес к группе «{group}» и параметры новой заявки. Без обещания наличия и без внешней отправки.'))
        reminders.append({**r, 'run_id': run_id, 'source_ref': f"/crm/reminders/{r['reminder_id']}@{r['version']};source-run:{run_id}",
                          'reason': '; '.join(row['reasons']), 'subject_type': 'Интерес к товарной группе',
                          'text': r['text'] + ' Сохранён локальный черновик; сообщение клиенту не отправлялось.'})
        if len(reminders) == 3:
            break
    evidence = dict(synthetic=False, manifest=manifest, scope='actual_open_pack_not_closed_submission',
                    examples=dict(cutting=cutting, answers=answers, reminders=reminders, quality=quality))
    write_json(destination / 'examples-evidence.json', evidence)
    return {'cutting': len(cutting), 'answers': len(answers), 'quality': len(quality), 'reminders': len(reminders)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=19884)
    parser.add_argument('--selected-seconds', type=int, default=600)
    parser.add_argument('--workers', type=int, default=7)
    args = parser.parse_args()
    args.exe, args.data, args.output = args.exe.resolve(), args.data.resolve(), args.output.resolve()
    if args.output.exists():
        raise ValueError('Choose a new output version; prior evidence is protected')
    args.output.mkdir(parents=True)
    stamp = json.loads((args.exe.parent / '_internal/glassflow/build-info.json').read_text('utf-8'))
    report = dict(status='running', runtime=stamp, transport='actual_frozen_windows_tcp', human_labor='not_run', live_ai='not_run',
                  official_closed='not_run', cpu_count=os.cpu_count())
    server = Frozen(args.data, args.port, args.exe)
    server.start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{args.port}', trust_env=False, timeout=60) as client:
            client.get('/api/v1/session').raise_for_status()
            inputs = {Path(name).name: (PACK / name).read_bytes() for name in INPUTS}
            report['input_hashes'] = {n: digest(raw) for n, raw in inputs.items()}
            source, buyer = import_source(client, inputs, 'Неизменённый открытый набор: согласованная финальная серия после аудита')
            report['source'], report['registry'] = source, buyer
            baseline = run_profile(client, source, buyer, dict(profile='quick', seed=42, time_limit_seconds=5, workers=1, minimum_free_remnants=5), args.output / 'baseline', 45)
            report['baseline'] = baseline
            write_json(args.output / 'series.json', report)
            selected = run_profile(client, source, buyer, dict(profile='extended', seed=42, time_limit_seconds=args.selected_seconds, workers=args.workers, minimum_free_remnants=5), args.output / 'selected', args.selected_seconds + 60)
            report['selected'] = selected
            assert baseline['manifest']['source_hashes'] == selected['manifest']['source_hashes']
            report['examples'] = examples(client, selected, source, inputs, args.output)
            report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        write_json(args.output / 'series.json', report)
        with httpx.Client(base_url=f'http://127.0.0.1:{args.port}', trust_env=False, timeout=5) as client:
            server.stop(client)
        print(json.dumps({'status': report['status'], 'output': str(args.output)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
