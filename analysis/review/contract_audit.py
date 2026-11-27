"""Research audit only. Original organizer files are never changed."""
from pathlib import Path
import csv, json, hashlib, importlib.util, copy, contextlib, io
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'inputs/PACK_for_teams'
OUT=Path(__file__).resolve().parent
def rd(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
v=module('official_cutting',DATA/'1_ostatki/validate.py')
b=module('official_other',DATA/'2_assistant_crm/selfcheck.py')
stock=rd(DATA/'1_ostatki/stock_open.csv');orders=rd(DATA/'1_ostatki/orders_open.csv');mats=rd(DATA/'1_ostatki/materials.csv')
sol=rd(ROOT/'analysis/cutting/patterns_research_solution.csv')
P,M,ok,bad=v.check(stock,orders,sol,mats)
ids=[r['part_id'] for r in sol];used={r['remnant_id'] for r in sol if r['remnant_id']!='NEW'}
report={
 'counts':{'stock':len(stock),'orders':len(orders),'solution':len(sol),'covered':len(ok),'used_remnants':len(used),'unused_remnants':len(stock)-len(used)},
 'cutting_contract':{'all_ids_once':len(set(ids))==len(ids) and set(ids)==set(P),'official_invalid':bad,'rot_01_or_blank':all(r['rot'] in ('','0','1') for r in sol),'at_least_five_unused':len(stock)-len(used)>=5},
 'scorer_limits':[]
}
# Show why an official success cannot replace a strict contract check.
_,_,_,empty_bad=v.check(stock,orders,[],mats)
report['scorer_limits'].append({'test':'empty solution','official_invalid_count':len(empty_bad),'interpretation':'Missing parts are reported separately by CLI; own completeness gate is necessary.'})
cuttable=next(r for r in sol if r['rot']=='1' and M[P[r['part_id']]['material_id']]['закалённое']=='0')
mut=copy.deepcopy(sol)
next(r for r in mut if r['part_id']==cuttable['part_id'])['rot']='2'
_,_,_,rot_bad=v.check(stock,orders,mut,mats)
report['scorer_limits'].append({'test':'rot 1 changed to 2','official_invalid_count':len(rot_bad),'interpretation':'Validator treats nonzero rotation as truthy; contract must enforce 0 or 1. Never exploit this.'})
report['scorer_limits'].append({'test':'price answer contains expected and contradictory number','parsed_numbers':sorted(b.nums('Цена 4500 тенге или 9000 тенге.')),'interpretation':'Numeric presence is not semantic correctness; human review and own factual checking remain necessary.'})
report['scorer_limits'].append({'test':'unknown answer repeats a dimension','has_price_claim':b.has_price_claim('Размер 1200 мм. Цену уточнит менеджер.'),'interpretation':'Numeric heuristic can flag a harmless dimension. Keep unknown-price escalation concise; preserve detail separately.'})
rows=rd(DATA/'2_assistant_crm/applications_open.csv')
keys=lambda r:(-int(r['прошлых_заявок']),int(r['жалоба']),r['manager']=='M4',int(r['дней_с_последнего_контакта']))
ranked=sorted(rows,key=keys);selected=ranked[:25]
report['crm']={'reference_positive':sum(int(r['вернулся_за_60_дней']) for r in selected),'selected_rows':len(selected),'selected_unique_clients':len({r['client_id'] for r in selected}),'tie_at_cutoff':keys(ranked[24])==keys(ranked[25]),'label_is_future_outcome':True}
report['price_roles']={'savings_and_sale_cards':'materials.csv','customer_catalog_quote':'ksm_knowledge_base.json','whole_sheet_price':'independent catalog field; not derived from square-meter price','stock_change':'invalidates availability/allocation, not automatically customer catalog price'}
report['temporal_metrics']={'historical_dashboard':'only observed labeled applications; stock replanning must not change them','closed_predictions':'no observed return label; display unavailable, not zero','live_sla':'requires operational timestamps/status not supplied by historical CSV'}
manifest=json.loads((ROOT/'docs/specification/input_manifest.json').read_text(encoding='utf-8'))
report['source_integrity']={'files':len(manifest),'changed':[p for p,item in manifest.items() if hashlib.sha256((ROOT/p.replace('\\', '/')).read_bytes()).hexdigest()!=item['sha256']]}
(OUT/'contract_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
