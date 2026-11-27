import research as r
import numpy as np
import networkx as nx
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import lil_matrix
import json

results=[]
for mid,mat in r.M.items():
 if mat['закалённое']=='1':continue
 parts=[p for p in r.P if p['material_id']==mid]
 stocks=[(i,s) for i,s in enumerate(r.S) if s['material_id']==mid]
 variables=[(p,i) for p in parts for i in r.eligible[p['part_id']]]
 if not variables:continue
 indexes={(p['part_id'],i):k for k,(p,i) in enumerate(variables)}
 cons=[];upper=[]
 for p in parts:
  cons.append({indexes[p['part_id'],i]:1 for i in r.eligible[p['part_id']]});upper.append(1)
 for i,s in stocks:
  candidates=[p for p in parts if (p['part_id'],i) in indexes]
  cons.append({indexes[p['part_id'],i]:(p['w']+3)*(p['h']+3) for p in candidates});upper.append((s['w']-7)*(s['h']-7))
  graph=nx.Graph();graph.add_nodes_from(p['part_id'] for p in candidates)
  for ia,p in enumerate(candidates):
   for q in candidates[ia+1:]:
    compatible=False
    for w,h in [(p['w'],p['h']),(p['h'],p['w'])]:
     for u,v in [(q['w'],q['h']),(q['h'],q['w'])]:
      if (w+u+3<=s['w']-10 and max(h,v)<=s['h']-10) or (max(w,u)<=s['w']-10 and h+v+3<=s['h']-10):compatible=True
    if not compatible:graph.add_edge(p['part_id'],q['part_id'])
  for clique in nx.find_cliques(graph):
   if len(clique)>1:cons.append({indexes[pid,i]:1 for pid in clique});upper.append(1)
 A=lil_matrix((len(cons),len(variables)))
 for j,c in enumerate(cons):
  for k,x in c.items():A[j,k]=x
 c=np.array([-p['area']/1e6 for p,i in variables])
 opt=milp(c,integrality=np.ones(len(c)),bounds=Bounds(0,1),constraints=LinearConstraint(A.tocsr(),np.full(len(cons),-np.inf),np.array(upper)),options={'time_limit':15,'mip_rel_gap':0.00001})
 simple=min(sum((s['w']-10)*(s['h']-10) for i,s in stocks),sum(p['area'] for p in parts if r.eligible[p['part_id']]))/1e6
 premium=[p for p in parts if p['премиум']=='1'];nonprem=[p for p in parts if p['премиум']=='0']
 premium_bound=(sum((s['w']-10)*(s['h']-10) for i,s in stocks if s['дефект']=='0')+sum(p['area'] for p in nonprem))/1e6
 result={'material':mid,'variables':len(c),'constraints':len(cons),'simple_area_bound_m2':simple,'premium_bound_m2':premium_bound,'upper_bound_m2':-opt.mip_dual_bound,'relaxed_feasible_m2':-opt.fun,'solver_status':opt.message}
 results.append(result);print(result,flush=True)
bound=sum(min(x['simple_area_bound_m2'],x['premium_bound_m2'],x['upper_bound_m2']) for x in results)+r.metric(r.temp_sol)/1e6
out={'normal_materials':results,'tempered_exact_m2':r.metric(r.temp_sol)/1e6,'upper_bound_m2':bound,'upper_bound_coverage':bound/(r.total/1e6),'note':'Necessary conditions: material, premium, inflated area and pair incompatibility maximal cliques, integer assignment. This is an upper bound, not a feasible cutting plan.'}
(r.OUT/'upper_bound.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
