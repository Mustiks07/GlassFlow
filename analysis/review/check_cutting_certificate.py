"""Certificate verifier: Python stdlib + unchanged official validator; no solver."""
import csv,json,hashlib,importlib.util,itertools,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'inputs/PACK_for_teams/1_ostatki';OUT=ROOT/'analysis/review'
certificate=json.loads((OUT/'cutting_dual_certificate.json').read_text(encoding='utf-8'))
def read(n):return list(csv.DictReader((SRC/n).open(encoding='utf-8')))
M=read('materials.csv');S=read('stock_open.csv');P=read('orders_open.csv')
md={m['material_id']:m for m in M};sd={s['remnant_id']:s for s in S};pd={p['part_id']:p for p in P}
assert len(md)==len(M) and len(sd)==len(S) and len(pd)==len(P)
expected_materials={m['material_id'] for m in M if m['закалённое']=='0'}
certified_materials=[c['material'] for c in certificate['normal_materials']]
assert set(certified_materials)==expected_materials and len(certified_materials)==len(expected_materials)
assert isinstance(certificate['denominator'],int) and certificate['denominator']>0
assert all(c['denominator']==certificate['denominator'] for c in certificate['normal_materials'])
for name,digest in certificate['source_sha256'].items():assert hashlib.sha256((SRC/name).read_bytes()).hexdigest()==digest
spec=importlib.util.spec_from_file_location('official_validator',SRC/'validate.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
def area(p):return int(p['длина_мм'])*int(p['ширина_мм'])
def dims(p,rot):
 d=(int(p['длина_мм']),int(p['ширина_мм']))
 return d[::-1] if rot else d
def placement(pid,rid,x=5,y=5,rot=0):return dict(part_id=pid,remnant_id=rid,x_mm=x,y_mm=y,rot=rot)
def single_ok(p,s):
 return any(not v.check([s],[p],[placement(p['part_id'],s['remnant_id'],rot=rot)],M)[3] for rot in (0,1))
def pair_ok(p,q,s):
 # If separated by x or y, bottom/left normalization makes one of these placements possible.
 for a,b in itertools.product((0,1),repeat=2):
  w,h=dims(p,a)
  for x,y in [(5+w+3,5),(5,5+h+3)]:
   sol=[placement(p['part_id'],s['remnant_id'],rot=a),placement(q['part_id'],s['remnant_id'],x,y,b)]
   if not v.check([s],[p,q],sol,M)[3]:return True
 return False
num=0;num_columns=0;num_rows=0;pair_checks=0
for c in certificate['normal_materials']:
 den=c['denominator'];cols=c['columns']
 expected={(p['part_id'],s['remnant_id']) for p in P for s in S if p['material_id']==c['material'] and s['material_id']==c['material'] and single_ok(p,s)}
 actual={(x['part_id'],x['remnant_id']) for x in cols}
 assert len(actual)==len(cols) and actual==expected
 lhs=[0]*len(cols);value=0
 for row in c['constraints']:
  co={int(k):a for k,a in row['coef'].items()};dual=row['dual_numerator'];assert isinstance(dual,int) and dual>=0
  if row['kind']=='part':
   assert row['rhs']==1
   assert co=={i:1 for i,x in enumerate(cols) if x['part_id']==row['id']}
  elif row['kind']=='area':
   s=sd[row['id']];W,H=dims(s,0)
   assert row['rhs']==(W-7)*(H-7)
   assert co=={i:(dims(pd[x['part_id']],0)[0]+3)*(dims(pd[x['part_id']],0)[1]+3) for i,x in enumerate(cols) if x['remnant_id']==row['id']}
  elif row['kind']=='clique':
   assert row['rhs']==1 and all(a==1 for a in co.values())
   assert all(cols[i]['remnant_id']==row['id'] for i in co)
   for i,j in itertools.combinations(co,2):
    assert not pair_ok(pd[cols[i]['part_id']],pd[cols[j]['part_id']],sd[row['id']]);pair_checks+=1
  else:raise AssertionError('Unknown constraint')
  for i,a in co.items():lhs[i]+=dual*a
  value+=dual*row['rhs']
 assert all(lhs[i]>=area(pd[x['part_id']])*den for i,x in enumerate(cols))
 assert all(x['area_mm2']==area(pd[x['part_id']]) for x in cols)
 assert value==c['bound_numerator_mm2'];num+=value;num_columns+=len(cols);num_rows+=len(c['constraints'])
temp_upper=0;temp_candidates={}
for s in S:
 if md[s['material_id']]['закалённое']!='1':continue
 eligible=[p for p in P if p['material_id']==s['material_id'] and single_ok(p,s)]
 if eligible:temp_candidates[s['remnant_id']]=eligible
 temp_upper+=max([area(p) for p in eligible],default=0)
assert temp_upper==round(certificate['tempered_upper_m2']*1e6)
num+=temp_upper*certificate['denominator']
assert num==certificate['upper_bound_numerator_mm2']
total=sum(area(p) for p in P);assert total==certificate['total_demand_mm2']
# Exhaustively enumerate tiny tempered matching independently of weighted matching algorithms.
keys=list(temp_candidates);best=(0,[])
def search(k,selected,value,trace):
 global best
 if k==len(keys):
  if value>best[0]:best=(value,trace)
  return
 search(k+1,selected,value,trace)
 for p in temp_candidates[keys[k]]:
  if p['part_id'] not in selected:search(k+1,selected|{p['part_id']},value+area(p),trace+[(p['part_id'],keys[k])])
search(0,set(),0,[])
sol=list(csv.DictReader((ROOT/'analysis/cutting/patterns_research_solution.csv').open(encoding='utf-8')))
_,_,ok,bad=v.check(S,P,sol,M)
cov=sum(area(pd[p]) for p in ok)/total
assert len(sol)==len(P) and len({x['part_id'] for x in sol})==len(P) and not bad
points=max(0,min(20,20*(cov-.5)/.15)-min(6,.3*len(bad)))
report={'certificate_verified':True,'checker_requires_solver':False,'normal_assignment_columns':num_columns,'nonzero_dual_constraints':num_rows,'official_pair_incompatibility_checks':pair_checks,'exact_bound_numerator_mm2':num,'exact_bound_denominator':certificate['denominator'],'coverage_upper_bound':num/(certificate['denominator']*total),'strictly_below_65_percent':num*100<65*certificate['denominator']*total,'tempered_bruteforce_area_m2':best[0]/1e6,'tempered_bruteforce_assignment':best[1],'validated_solution_coverage':cov,'validated_solution_parts':len(ok),'validated_solution_invalid':len(bad),'validated_solution_score_of_20':points}
(OUT/'cutting_certificate_verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
