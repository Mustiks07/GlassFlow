import research as r
import numpy as np,json
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import lil_matrix
from collections import defaultdict
patterns={}
for mode in ['guillotine','maxrects']:
 for seed in range(400):
  sol=r.run(seed,mode)
  bystock=defaultdict(dict)
  for pid,(i,x,y,rot) in sol.items():
   if r.M[r.S[i]['material_id']]['закалённое']=='0':bystock[i][pid]=(i,x,y,rot)
  for i,pp in bystock.items():
   patterns.setdefault((i,tuple(sorted(pp))),pp)
best=dict(r.temp_sol);stats=[]
for mid,mat in r.M.items():
 if mat['закалённое']=='1':continue
 pats=[(i,pp) for (i,key),pp in patterns.items() if r.S[i]['material_id']==mid]
 parts=[p for p in r.P if p['material_id']==mid];stocks=[i for i,s in enumerate(r.S) if s['material_id']==mid]
 rows={p['part_id']:j for j,p in enumerate(parts)};rows.update({i:j+len(parts) for j,i in enumerate(stocks)})
 A=lil_matrix((len(rows),len(pats)));c=[]
 for k,(i,pp) in enumerate(pats):
  A[rows[i],k]=1
  for pid in pp:A[rows[pid],k]=1
  c.append(-r.metric(pp)/1e6)
 opt=milp(np.array(c),integrality=np.ones(len(c)),bounds=Bounds(0,1),constraints=LinearConstraint(A.tocsr(),np.full(len(rows),-np.inf),np.ones(len(rows))),options={'time_limit':10,'mip_rel_gap':0.00001})
 for val,(i,pp) in zip(opt.x,pats):
  if val>0.5:best.update(pp)
 stats.append({'material':mid,'patterns':len(pats),'area_m2':-opt.fun,'gap':opt.mip_gap})
rows=r.export(best,r.OUT/'patterns_research_solution.csv')
_,_,ok,bad=r.v.check(r.S,r.P,rows,list(r.M.values()))
money=sum(p['area']/1e6*int(r.M[p['material_id']]['цена_нового_стекла_тг_за_м2']) for p in r.P if p['part_id'] in ok)
out={'materials':stats,'covered_parts':len(ok),'used_remnants':len(set(ok.values())),'covered_area_m2':r.metric(best)/1e6,'coverage':r.metric(best)/r.total,'money':money,'invalid':bad,'note':'Feasible pattern pool MIP. Not a proof of globally optimal cutting.'}
(r.OUT/'patterns_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
