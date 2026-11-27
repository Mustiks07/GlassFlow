"""Independent LP upper-bound audit; exact integer dual certificate repair/check."""
from pathlib import Path
import csv, json, sys, math, hashlib
from collections import defaultdict
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
import networkx as nx
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'inputs/PACK_for_teams/1_ostatki'
OUT=ROOT/'analysis/review'
OUT.mkdir(exist_ok=True)
def read(name):return list(csv.DictReader((SRC/name).open(encoding='utf-8')))
materials={x['material_id']:x for x in read('materials.csv')}
parts=read('orders_open.csv');stock=read('stock_open.csv')
assert len({p['part_id'] for p in parts})==len(parts)
assert len({s['remnant_id'] for s in stock})==len(stock)
for rows in (parts,stock):
 for row in rows:
  assert all(v!='' for v in row.values())
  row['dim']=tuple(map(int,(row['длина_мм'],row['ширина_мм'])))
  assert min(row['dim'])>0
  assert row['material_id'] in materials
  assert row.get('дефект',row.get('премиум')) in ('0','1')
def rotations(dim):return set((dim,dim[::-1]))
def eligible(p,s):
 if p['material_id']!=s['material_id']:return False
 if p['премиум']=='1' and s['дефект']=='1':return False
 if materials[p['material_id']]['закалённое']=='1':
  return any(abs(a-s['dim'][0])<=2 and abs(b-s['dim'][1])<=2 for a,b in rotations(p['dim']))
 return any(a+10<=s['dim'][0] and b+10<=s['dim'][1] for a,b in rotations(p['dim']))
def compatible(a,b,s):
 W,H=s['dim']
 return any((x+u+13<=W and max(y,v)+10<=H) or
            (max(x,u)+10<=W and y+v+13<=H)
            for x,y in rotations(a['dim']) for u,v in rotations(b['dim']))
den=10**6
certs=[]
for mid,mat in materials.items():
 if mat['закалённое']=='1':continue
 pp=[p for p in parts if p['material_id']==mid];ss=[s for s in stock if s['material_id']==mid]
 columns=[(p,s) for p in pp for s in ss if eligible(p,s)]
 indices={(p['part_id'],s['remnant_id']):i for i,(p,s) in enumerate(columns)}
 rows=[];part_row={}
 for p in pp:
  part_row[p['part_id']]=len(rows)
  rows.append({'kind':'part','id':p['part_id'],'rhs':1,'coef':{indices[p['part_id'],s['remnant_id']]:1 for s in ss if (p['part_id'],s['remnant_id']) in indices}})
 for s in ss:
  cp=[p for p in pp if (p['part_id'],s['remnant_id']) in indices]
  rows.append({'kind':'area','id':s['remnant_id'],'rhs':(s['dim'][0]-7)*(s['dim'][1]-7),'coef':{indices[p['part_id'],s['remnant_id']]:(p['dim'][0]+3)*(p['dim'][1]+3) for p in cp}})
  graph=nx.Graph();graph.add_nodes_from(range(len(cp)))
  for i in range(len(cp)):
   for j in range(i+1,len(cp)):
    if not compatible(cp[i],cp[j],s):graph.add_edge(i,j)
  for clique in nx.find_cliques(graph):
   if len(clique)<2:continue
   rows.append({'kind':'clique','id':s['remnant_id'],'rhs':1,'coef':{indices[cp[i]['part_id'],s['remnant_id']]:1 for i in clique}})
 rr=[];cc=[];dd=[]
 for i,row in enumerate(rows):
  for j,val in row['coef'].items():rr.append(i);cc.append(j);dd.append(val)
 A=coo_matrix((dd,(rr,cc)),shape=(len(rows),len(columns))).tocsr()
 areas=np.array([p['dim'][0]*p['dim'][1] for p,s in columns])
 opt=linprog(-areas/1e6,A_ub=A,b_ub=np.array([row['rhs'] for row in rows]),bounds=(0,None),method='highs')
 assert opt.success,opt.message
 # lambda = -marginal * 1e6 rescales objective from m² to mm².
 # Integer numerators encode nonnegative rational multipliers / den.
 numer=[max(0,math.ceil(-float(v)*1e6*den)) for v in opt.ineqlin.marginals]
 lhs=[0]*len(columns)
 for val,row in zip(numer,rows):
  for j,a in row['coef'].items():lhs[j]+=val*a
 repair={}
 for j,(p,s) in enumerate(columns):
  deficit=int(areas[j])*den-lhs[j]
  repair[p['part_id']]=max(repair.get(p['part_id'],0),deficit)
 for pid,delta in repair.items():numer[part_row[pid]]+=delta
 lhs=[0]*len(columns)
 for val,row in zip(numer,rows):
  assert val>=0
  for j,a in row['coef'].items():lhs[j]+=val*a
 assert all(lhs[j]>=int(areas[j])*den for j in range(len(columns)))
 numerator=sum(v*row['rhs'] for v,row in zip(numer,rows))
 for val,row in zip(numer,rows):row['dual_numerator']=val
 cert={'material':mid,'denominator':den,'bound_numerator_mm2':numerator,'lp_bound_m2':-float(opt.fun),'certified_bound_m2':numerator/den/1e6,'columns':[{'part_id':p['part_id'],'remnant_id':s['remnant_id'],'area_mm2':int(area)} for (p,s),area in zip(columns,areas)],'constraints':[row for row in rows if row['dual_numerator']>0],'repair_mm2':sum(repair.values())/den}
 certs.append(cert)
 print(mid,'LP',-opt.fun,'certified',numerator/den/1e6,'nonzero rows',len(cert['constraints']),flush=True)
# Tempered: a deliberately simple upper bound, sum of max eligible part area per remnant.
temp=[]
for s in stock:
 if materials[s['material_id']]['закалённое']!='1':continue
 candidates=[p for p in parts if eligible(p,s)]
 area=max([p['dim'][0]*p['dim'][1] for p in candidates],default=0)
 if area:temp.append({'remnant_id':s['remnant_id'],'max_eligible_area_mm2':area,'eligible_part_ids':[p['part_id'] for p in candidates]})
temp_upper=sum(x['max_eligible_area_mm2'] for x in temp)
total=sum(p['dim'][0]*p['dim'][1] for p in parts)
numerator=sum(c['bound_numerator_mm2'] for c in certs)+temp_upper*den
output={'method':'Independent continuous LP and exact nonnegative rational dual certificate. No previous research module imported. Tempered upper bound sums largest eligible part per remnant, independent of matching.','source_sha256':{name:hashlib.sha256((SRC/name).read_bytes()).hexdigest() for name in ['materials.csv','stock_open.csv','orders_open.csv']},'total_demand_mm2':total,'denominator':den,'upper_bound_numerator_mm2':numerator,'upper_bound_m2':numerator/den/1e6,'upper_bound_coverage':numerator/(den*total),'normal_materials':certs,'tempered':temp,'tempered_upper_m2':temp_upper/1e6}
(OUT/'cutting_dual_certificate.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXACT CERTIFICATE coverage <=',output['upper_bound_coverage'],'m2 <=',output['upper_bound_m2'],'tempered',temp_upper/1e6)
