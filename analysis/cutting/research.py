import csv, json, random, sys, importlib.util
from pathlib import Path
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'inputs/PACK_for_teams/1_ostatki'
OUT=Path(__file__).resolve().parent
def read(n): return list(csv.DictReader((D/n).open(encoding='utf-8')))
M={r['material_id']:r for r in read('materials.csv')}
S=read('stock_open.csv'); P=read('orders_open.csv')
for rows in (S,P):
 for r in rows:
  r['w']=int(r['длина_мм']);r['h']=int(r['ширина_мм']);r['area']=r['w']*r['h']
def fits(p,s):
 if p['material_id']!=s['material_id'] or (p['премиум']=='1' and s['дефект']=='1'):return False
 if M[p['material_id']]['закалённое']=='1':return (abs(p['w']-s['w'])<=2 and abs(p['h']-s['h'])<=2) or (abs(p['w']-s['h'])<=2 and abs(p['h']-s['w'])<=2)
 return (p['w']<=s['w']-10 and p['h']<=s['h']-10) or (p['w']<=s['h']-10 and p['h']<=s['w']-10)
eligible={p['part_id']:[i for i,s in enumerate(S) if fits(p,s)] for p in P}
tempered=[p for p in P if M[p['material_id']]['закалённое']=='1']
match={}
def augment(p,seen):
 for i in eligible[p['part_id']]:
  if i in seen:continue
  seen.add(i)
  if i not in match or augment(match[i],seen):match[i]=p;return True
 return False
for p in sorted(tempered,key=lambda p:-p['area']):augment(p,set())
temp_sol={p['part_id']:(i,0,0,0) for i,p in match.items()}
normal=[p for p in P if M[p['material_id']]['закалённое']=='0']
def run(seed,mode='guillotine',single=False):
 rng=random.Random(seed);sol=dict(temp_sol)
 frees={i:[(5,5,s['w']-10,s['h']-10)] for i,s in enumerate(S) if M[s['material_id']]['закалённое']=='0'}
 order=sorted(normal,key=lambda p:-p['area']*(1 if seed==0 else rng.uniform(0.55,1.6)))
 for p in order:
  options=[]
  for i in eligible[p['part_id']]:
   for k,(x,y,W,H) in enumerate(frees[i]):
    for rot,(w,h) in enumerate([(p['w'],p['h']),(p['h'],p['w'])]):
     if w<=W and h<=H:
      score=(W*H-w*h, min(W-w,H-h)) if seed%3==0 else (min(W-w,H-h),W*H-w*h)
      options.append((score,i,k,x,y,w,h,rot))
  if not options:continue
  _,i,k,x,y,w,h,rot=min(options)
  sol[p['part_id']]=(i,x,y,rot)
  if single:frees[i]=[];continue
  if mode=='guillotine':
   _,_,W,H=frees[i].pop(k)
   horiz=((W-w)*H>w*(H-h)) if seed%2 else ((W-w)<(H-h))
   new=[(x+w+3,y,W-w-3,H),(x,y+h+3,w,H-h-3)] if horiz else [(x+w+3,y,W-w-3,h),(x,y+h+3,W,H-h-3)]
   frees[i].extend(t for t in new if t[2]>0 and t[3]>0)
  else:
   new=[]
   for fx,fy,fw,fh in frees[i]:
    if x>=fx+fw or x+w+3<=fx or y>=fy+fh or y+h+3<=fy:new.append((fx,fy,fw,fh));continue
    if x>fx:new.append((fx,fy,x-fx-3,fh))
    if x+w+3<fx+fw:new.append((x+w+3,fy,fx+fw-x-w-3,fh))
    if y>fy:new.append((fx,fy,fw,y-fy-3))
    if y+h+3<fy+fh:new.append((fx,y+h+3,fw,fy+fh-y-h-3))
   new=list(set(t for t in new if t[2]>0 and t[3]>0))
   frees[i]=[a for a in new if not any(a!=b and a[0]>=b[0] and a[1]>=b[1] and a[0]+a[2]<=b[0]+b[2] and a[1]+a[3]<=b[1]+b[3] for b in new)]
 return sol
spec=importlib.util.spec_from_file_location('official',D/'validate.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
def export(sol,path):
 rows=[]
 for p in P:
  if p['part_id'] in sol:
   i,x,y,rot=sol[p['part_id']];rows.append(dict(part_id=p['part_id'],remnant_id=S[i]['remnant_id'],x_mm=x,y_mm=y,rot=rot))
  else:rows.append(dict(part_id=p['part_id'],remnant_id='NEW',x_mm='',y_mm='',rot=''))
 with path.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=['part_id','remnant_id','x_mm','y_mm','rot']);w.writeheader();w.writerows(rows)
 return rows
total=sum(p['area'] for p in P)
def metric(sol):return sum(p['area'] for p in P if p['part_id'] in sol)
summary={'parts':len(P),'orders':len(set(p['order_id'] for p in P)),'stock':len(S),'total_area_m2':total/1e6,'stock_area_m2':sum(s['area'] for s in S)/1e6,'eligible_parts':sum(bool(eligible[p['part_id']]) for p in P),'individually_feasible_area_m2':sum(p['area'] for p in P if eligible[p['part_id']])/1e6,'tempered_parts':len(tempered),'tempered_eligible':sum(bool(eligible[p['part_id']]) for p in tempered),'tempered_matched':len(temp_sol),'tempered_exact_area_m2':metric(temp_sol)/1e6,'defective_stock':sum(s['дефект']=='1' for s in S),'premium_parts':sum(p['премиум']=='1' for p in P)}
summary['materials']=[]
for mid in M:
 pp=[p for p in P if p['material_id']==mid];ss=[s for s in S if s['material_id']==mid]
 summary['materials'].append({'material':mid,'parts':len(pp),'stock':len(ss),'demand_m2':sum(p['area'] for p in pp)/1e6,'stock_m2':sum(s['area'] for s in ss)/1e6,'eligible_parts':sum(bool(eligible[p['part_id']]) for p in pp),'eligible_area_m2':sum(p['area'] for p in pp if eligible[p['part_id']])/1e6})
for mode,single,n in [('single',True,1),('guillotine',False,250),('maxrects',False,250)]:
 best=max((run(seed,mode,single) for seed in range(n)),key=metric)
 rows=export(best,OUT/(mode+'_research_solution.csv'))
 _,_,ok,bad=v.check(S,P,rows,list(M.values()))
 money=sum(p['area']/1e6*int(M[p['material_id']]['цена_нового_стекла_тг_за_м2']) for p in P if p['part_id'] in ok)
 summary[mode]={'covered_parts':len(ok),'used_remnants':len(set(ok.values())),'area_m2':metric(best)/1e6,'coverage':metric(best)/total,'invalid':bad,'money':money,'restarts':n}
 print(mode,summary[mode],flush=True)
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
