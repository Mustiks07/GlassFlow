"""Verify data/buyers/registry_source.py by downloading each source page, then write
buyers_candidate.csv (exact schema name,city,category,url,why,source_url,score) and evidence.json.
Usage: python3 data/buyers/verify_buyers.py  (needs network; CA bundle via SSL_CERT_FILE if behind a proxy)
"""
import csv, datetime, html, importlib.util, io, json, os, re, ssl, sys, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('reg', ROOT / 'registry_source.py')
reg = importlib.util.module_from_spec(spec); spec.loader.exec_module(reg)
ALLOWED = {'мебельная фабрика', 'дизайн-студия', 'строительная компания', 'окна и двери', 'магазин', 'торговый центр', 'кафе или ресторан', 'салон', 'другое'}
cafile = os.environ.get('SSL_CERT_FILE') or ('/root/.ccr/ca-bundle.crt' if os.path.exists('/root/.ccr/ca-bundle.crt') else None)
ctx = ssl.create_default_context(cafile=cafile)
CITY = {'Астана': r'Астан|Astana|Нур-Султан|Nur-Sultan', 'Караганда': r'Караганд|Karaganda|Qaragandy'}

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (GlassFlow buyer research check)', 'Accept-Language': 'ru'})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        body = r.read(2_000_000).decode('utf-8', 'replace'); return r.status, r.geturl(), body

def fetch_page(url, attempts=3):
    """Some sites briefly serve an anti-bot interstitial ('Секундочку…'); retry before judging the page."""
    import time
    for attempt in range(attempts):
        status, final, body = fetch(url)
        if status == 200 and not re.search(r'<title[^>]*>\s*(Секундочку|Just a moment|Attention Required)', body, re.I):
            break
        time.sleep(2 + attempt * 2)
    return status, final, body

def check(row):
    bid, name, city, cat, url, src, keys, why, score = row
    result = {'id': bid, 'name': name, 'city': city, 'category': cat, 'url': url, 'source_url': src}
    try:
        status, final, body = fetch_page(src)
        title = re.search(r'<title[^>]*>(.*?)</title>', body, re.S | re.I)
        title = re.sub(r'\s+', ' ', html.unescape(title.group(1))).strip() if title else ''
        text = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', body, flags=re.S | re.I))))
        hay = title + ' ' + text
        cm = re.search(CITY[city], hay); km = next((k for k in keys if k.lower() in hay.lower()), None)
        excerpt = ''
        if km:
            i = hay.lower().find(km.lower()); excerpt = hay[max(0, i - 90): i + 110].strip()
        result.update(http_status=status, final_url=final, page_title=title, city_confirmed=bool(cm),
                      profile_keyword=km, excerpt=excerpt, ok=status == 200 and bool(cm) and bool(km))
    except Exception as exc:
        result.update(http_status=None, ok=False, error=str(exc)[:160])
    if url != src:
        try:
            ustatus = fetch(url)[0]; result['url_status'] = ustatus
        except Exception as exc:
            result['url_status'] = f'ERR {str(exc)[:80]}'
    return result

def main():
    rows = reg.ROWS
    names = [r[1].strip().lower() for r in rows]
    assert len(rows) == 50, len(rows)
    assert len(set(names)) == 50, 'duplicate names'
    assert len({r[0] for r in rows}) == 50
    for r in rows:
        assert r[3] in ALLOWED, r
        assert isinstance(r[8], int) and 0 <= r[8] <= 100, r
        assert r[7].count('.') <= 1 and len(r[7]) < 240, ('why must be one sentence', r[0])
    with ThreadPoolExecutor(10) as ex: results = list(ex.map(check, rows))
    today = datetime.date.today().isoformat()
    failed = [r for r in results if not r['ok']]
    astana = sum(1 for r in rows if r[2] == 'Астана'); cats = Counter(r[3] for r in rows)
    evidence = {
        'generated_at': today,
        'reviewer': 'Claude 1 (агент Ильяса): ручной отбор публичных организаций; автоматическая загрузка source_url с проверкой города и профиля; ручной просмотр заголовка и фрагмента',
        'dedup_rule': 'Одна запись на организацию/бренд: филиалы, точки сети и залы одного бренда объединяются в одну запись; запись указывает город проверенного объекта. Разные юридические бренды одной группы считаются разными только при разных сайтах и профилях.',
        'score_meaning': 'Экспертная релевантность профиля для небольших кусков стекла и зеркал (0-100), не вероятность покупки и не факт прошлых заказов.',
        'privacy': 'Только публичные организации и их публичные страницы; контакты частных лиц не собирались; сообщения не отправлялись.',
        'summary': {'total': len(rows), 'unique_names': len(set(names)), 'astana': astana, 'categories': dict(cats), 'failed_checks': [r['id'] for r in failed]},
        'buyers': [{**res, 'verified_at': today, 'why': row[7], 'score': row[8]} for res, row in zip(results, rows)],
    }
    (ROOT / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    out = io.StringIO(newline='')
    w = csv.writer(out, lineterminator='\n')
    w.writerow(['name', 'city', 'category', 'url', 'why', 'source_url', 'score'])
    for r in rows: w.writerow([r[1], r[2], r[3], r[4], r[7], r[5], r[8]])
    (ROOT / 'buyers_candidate.csv').write_bytes(out.getvalue().encode('utf-8'))
    print(f"rows={len(rows)} astana={astana} categories={len(cats)} {dict(cats)}")
    for r in failed: print('FAIL', r['id'], r['name'], r.get('http_status'), r.get('error') or f"city={r.get('city_confirmed')} key={r.get('profile_keyword')} title={r.get('page_title')}")
    bad_url = [r for r in results if isinstance(r.get('url_status'), str) or (r.get('url_status') not in (None, 200))]
    for r in bad_url: print('URL', r['id'], r['url'], r['url_status'])
    sys.exit(1 if failed else 0)

if __name__ == '__main__':
    main()
