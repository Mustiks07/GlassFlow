"""Independent arithmetic/input audit of proposed final demo. No app implementation."""
from pathlib import Path
from decimal import Decimal
import csv,json,importlib.util
ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'inputs/PACK_for_teams'
def rd(p):
 with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
stock=rd(D/'1_ostatki/stock_open.csv');mats=rd(D/'1_ostatki/materials.csv')
solution=rd(ROOT/'analysis/cutting/patterns_research_solution.csv')
used={r['remnant_id'] for r in solution if r['remnant_id']!='NEW'}
free=[s for s in stock if s['remnant_id'] not in used]
kb=json.loads((D/'2_assistant_crm/ksm_knowledge_base.json').read_text(encoding='utf-8'))
products={p['id']:p for p in kb['товары']}
spec=importlib.util.spec_from_file_location('organizer',D/'1_ostatki/validate.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
results=[]
for w,h in [(450,370),(451,370)]:
 part={'part_id':'DEMO_NEW_PART','material_id':'clear-6','длина_мм':str(w),'ширина_мм':str(h),'премиум':'0'}
 fits=[]
 for s in free:
  for rot in (0,1):
   sol=[dict(part_id=part['part_id'],remnant_id=s['remnant_id'],x_mm='5',y_mm='5',rot=str(rot))]
   _,_,ok,bad=v.check(stock,[part],sol,mats)
   if not bad and ok:
    fits.append(s['remnant_id']);break
 area=Decimal(w)*h/1000000
 price=area*products['steklo-6-prozrachnoe']['цена_за_м2_тг']
 edge=Decimal(2*(w+h))/1000*400
 results.append({'w_mm':w,'h_mm':h,'eligible_free_ids':fits,'glass_price_tg':str(price),'edge_price_tg':str(edge),'total_tg':str(price+edge),'saved_material_tg':str(price if fits else Decimal(0))})
assert results[0]['eligible_free_ids']==['R006'] and results[1]['eligible_free_ids']==[]
assert Decimal(results[0]['total_tg'])==Decimal('1988') and Decimal(results[1]['total_tg'])==Decimal('1991.76')
apps={r['app_id']:r for r in rd(D/'2_assistant_crm/applications_open.csv')}
assert apps['A0680']['client_id']=='C066' and apps['A0680']['группа_товара']=='стекло'
special=products['riflenoe-prozrachnoe-8']
assert special['цена_листа_тг']==170000 and special['цена_за_м2_тг'] is None
out={'scope':'Frozen current assignments; choose among completely unused original remnants only. Not a global impossibility proof. No new demo row is added to the official research result.', 'demo':results,'R006':next(s for s in stock if s['remnant_id']=='R006'),'reminder_subject':'Ask C066 about interest in a similar glass calculation; do not assign current visitor order to C066 or promise R006 to two clients.','catalog_counterexample':{'rippled8_sheet':170000,'rippled8_m2':None,'rippled_in_stock_materials':any('rifl' in m['material_id'] for m in mats),'generic_grey_m2':products['steklo-seroe']['цена_за_м2_тг'],'grey8_m2':products['steklo-seroe-8']['цена_за_м2_тг']}}
(Path(__file__).parent/'final_demonstration_verified.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
