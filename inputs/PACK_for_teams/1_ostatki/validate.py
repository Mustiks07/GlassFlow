#!/usr/bin/env python3
"""Проверка решения кейса A. Запуск: python validate.py stock.csv orders.csv solution.csv [materials.csv]
Печатает долю площади деталей, закрытую остатками, экономию в тенге и список ошибок. Жюри считает ровно этим же скриптом."""
import csv,sys,collections
TRIM=5      # мм: отступ от края остатка (обрезь)
GAP=3       # мм: ширина реза между деталями
TOL=2       # мм: допуск для калёного стекла (его резать нельзя)
def rd(p):return list(csv.DictReader(open(p,encoding='utf8')))
def load(stock,orders,mats):
    M={m['material_id']:m for m in mats};S={s['remnant_id']:s for s in stock};P={o['part_id']:o for o in orders}
    return M,S,P
def check(stock,orders,sol,mats):
    M,S,P=load(stock,orders,mats);bad=[];ok={};placed=collections.defaultdict(list);seen=set()
    for r in sol:
        pid=r['part_id'].strip();rid=r['remnant_id'].strip()
        if pid in seen:bad.append((pid,'деталь указана дважды'));continue
        seen.add(pid)
        if pid not in P:bad.append((pid,'такой детали нет в заказах'));continue
        if rid.upper()=='NEW' or rid=='':continue
        if rid not in S:bad.append((pid,f'остатка {rid} нет на складе'));continue
        p,s=P[pid],S[rid]
        if p['material_id']!=s['material_id']:bad.append((pid,'материал детали и остатка не совпадает'));continue
        if p['премиум']=='1' and s['дефект']=='1':bad.append((pid,'премиум-деталь нельзя резать из остатка с дефектом'));continue
        pw,ph=int(p['длина_мм']),int(p['ширина_мм']);W,H=int(s['длина_мм']),int(s['ширина_мм'])
        if M[s['material_id']]['закалённое']=='1':
            if not ((abs(pw-W)<=TOL and abs(ph-H)<=TOL) or (abs(pw-H)<=TOL and abs(ph-W)<=TOL)):bad.append((pid,'калёное стекло резать нельзя: размеры должны совпасть ±2 мм'));continue
            placed[rid].append((pid,0,0,pw,ph));continue
        try:x=int(float(r['x_mm']));y=int(float(r['y_mm']));rot=int(float(r['rot']))
        except Exception:bad.append((pid,'нет координат x_mm, y_mm, rot'));continue
        w,h=(ph,pw) if rot else (pw,ph)
        if x<TRIM or y<TRIM or x+w>W-TRIM or y+h>H-TRIM:bad.append((pid,'деталь выходит за границу остатка с отступом 5 мм'));continue
        placed[rid].append((pid,x,y,w,h))
    for rid,L in placed.items():
        if M[S[rid]['material_id']]['закалённое']=='1' and len(L)>1:
            for pid,*_ in L[1:]:bad.append((pid,'в калёный остаток можно поставить только одну деталь'))
            L[:]=L[:1]
        for i in range(len(L)):
            for j in range(i+1,len(L)):
                a,b=L[i],L[j]
                if a[1]<b[1]+b[3]+GAP and b[1]<a[1]+a[3]+GAP and a[2]<b[2]+b[4]+GAP and b[2]<a[2]+a[4]+GAP:bad.append((b[0],f'пересекается с {a[0]} (нужен зазор {GAP} мм)'))
    badp={b[0] for b in bad}
    for rid,L in placed.items():
        for pid,*_ in L:
            if pid not in badp:ok[pid]=rid
    return P,M,ok,bad
def main():
    if len(sys.argv)<4:print(__doc__);sys.exit(1)
    stock,orders,sol=rd(sys.argv[1]),rd(sys.argv[2]),rd(sys.argv[3])
    mats=rd(sys.argv[4]) if len(sys.argv)>4 else rd(__file__.rsplit('/',1)[0]+'/materials.csv' if '/' in __file__ else 'materials.csv')
    P,M,ok,bad=check(stock,orders,sol,mats)
    tot=sum(int(p['длина_мм'])*int(p['ширина_мм']) for p in P.values())/1e6
    cov=sum(int(P[p]['длина_мм'])*int(P[p]['ширина_мм']) for p in ok)/1e6
    money=sum(int(P[p]['длина_мм'])*int(P[p]['ширина_мм'])/1e6*int(M[P[p]['material_id']]['цена_нового_стекла_тг_за_м2']) for p in ok)
    missing=len(set(P)-{r['part_id'].strip() for r in sol})
    print(f'деталей всего: {len(P)}; из остатков: {len(ok)}; ошибок: {len(bad)}; не указано в решении: {missing}')
    print(f'площадь деталей: {tot:.2f} м²; закрыто остатками: {cov:.2f} м²; ДОЛЯ = {100*cov/tot:.2f} %')
    print(f'не пришлось резать нового стекла на {money:,.0f} тг'.replace(',',' '))
    for pid,why in bad[:30]:print('  ОШИБКА',pid,why)
    print(f'RESULT coverage={cov/tot:.6f} invalid={len(bad)} money={money:.0f}')
if __name__=='__main__':main()
