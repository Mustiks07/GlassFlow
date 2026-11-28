"""Readable presentation of genuine saved outputs; raw evidence and CSVs stay unchanged."""

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from post_acceptance import PACK, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--series', type=Path, required=True)
    args = parser.parse_args()
    output = args.series / 'examples-readable-evidence.json'
    if output.exists():
        raise ValueError('Existing presentation evidence is protected')
    evidence = json.loads((args.series / 'examples-evidence.json').read_text('utf-8'))
    manifest = evidence['manifest']
    directory = args.series / 'selected/downloaded'
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest, name
    tables = {}
    for role, filename, key in [('stock', 'stock_open.csv', 'remnant_id'), ('materials', 'materials.csv', 'material_id'), ('orders', 'orders_open.csv', 'part_id')]:
        raw_source = (PACK / '1_ostatki' / filename).read_bytes()
        assert hashlib.sha256(raw_source).hexdigest() == manifest['source_hashes'][role]
        tables[role] = {r[key]: r for r in csv.DictReader(io.StringIO(raw_source.decode('utf-8-sig')))}
    series = json.loads((args.series / 'series.json').read_text('utf-8'))
    plan = series['selected']['accepted_cutting']['result']
    allocated = defaultdict(list)
    for placement in plan['placements']:
        if placement['remnant_id'] != 'NEW':
            allocated[placement['remnant_id']].append(placement)
    chosen_pieces = []
    for count in (1, 2):
        matching = sorted(r for r in allocated if len(allocated[r]) == count)
        if matching:
            chosen_pieces.append(matching[0])
    remaining = sorted((r for r in allocated if r not in chosen_pieces), key=lambda r: (-min(len(allocated[r]), 6), r))
    chosen_pieces += [r for r in remaining if len(allocated[r]) <= 6][:3-len(chosen_pieces)]
    assert len(chosen_pieces) == 3
    evidence['examples']['cutting'] = []
    for rid in chosen_pieces:
        stock = tables['stock'][rid]
        placements = [{**p, 'length_mm': int(tables['orders'][p['part_id']]['длина_мм']),
            'width_mm': int(tables['orders'][p['part_id']]['ширина_мм'])} for p in allocated[rid]]
        evidence['examples']['cutting'].append(dict(dataset_id=manifest['dataset_id'], run_id=manifest['run_id'],
            source_ref=f"plan:{plan['plan_id']}@{plan['revision']}#{rid}", remnant_id=rid,
            length_mm=int(stock['длина_мм']), width_mm=int(stock['ширина_мм']), placements=placements,
            description=f"Открытый набор организаторов. {stock['место']}. Деталей: {len(placements)}; координаты приняты официальным валидатором. Поворот: 0 — без поворота, 1 — на 90°."))
    for item in evidence['examples']['cutting']:
        stock = tables['stock'][item['remnant_id']]
        material = tables['materials'][stock['material_id']]
        item['description'] = material['название'] + '. ' + item['description']
        item['description'] += ' В исходных данных отмечен дефект.' if stock['дефект'] == '1' else ' В исходных данных дефект не отмечен.'
    raw = (PACK / '2_assistant_crm/dialogs_open.csv').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['source_hashes']['dialogs']
    dialogs = {r['id']: r for r in csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))}
    rows = list(csv.DictReader(io.StringIO((directory / 'verdicts.csv').read_text('utf-8'))))
    # Illustrate both a correct answer and detected errors; the complete CSV remains available.
    chosen = [r for r in rows if r['verdict'] == 'OK'][:1] + [r for r in rows if r['verdict'] == 'ERROR'][:2]
    chosen += [r for r in rows if r not in chosen][:3-len(chosen)]
    assert len(chosen) == 3
    evidence['examples']['quality'] = [dict(
        dataset_id=manifest['dataset_id'], run_id=manifest['run_id'],
        source_ref=f"dialogs_open.csv#{r['id']};job:{manifest['result_refs']['quality']['job_id']}",
        client=dialogs[r['id']]['client'], manager=dialogs[r['id']]['manager'],
        raw_verdict=r['verdict'], raw_correct=r['correct'],
        verdict={'OK': 'Ответ верен', 'ERROR': 'В ответе найдена ошибка'}[r['verdict']],
        correct=format(Decimal(r['correct']), ',').replace(',', ' ') if r['correct'] else 'Исправление числа не требуется',
    ) for r in chosen]
    for reminder in evidence['examples']['reminders']:
        reminder['raw_source_app_ids'] = reminder['source_app_ids']
        reminder['source_app_ids'] = ', '.join(reminder['source_app_ids'])
    evidence['presentation_transforms'] = [
        'Вердикты показаны по-русски; raw_verdict/raw_correct сохраняют точные значения CSV.',
        'Основания напоминаний перечислены через запятую; исходный список сохранён.',
        'Выбраны первый OK и первые два ERROR для иллюстрации; точность по этим трём примерам не оценивается.',
        'Схемы показывают одночастный, двухчастный и наиболее плотный вариант до шести деталей; полный результат сохранён в CSV.',
    ]
    write_json(output, evidence)
    print(output)


if __name__ == '__main__':
    main()
