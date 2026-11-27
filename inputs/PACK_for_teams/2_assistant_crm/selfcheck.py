#!/usr/bin/env python3
"""Самопроверка кейса B на ОТКРЫТЫХ данных. Запуск:
  python score_B.py assistant answers.csv questions_closed_KEY.csv
  python score_B.py crm picks.csv applications_closed_KEY.csv
  python score_B.py dialogs verdicts.csv dialogs_closed_KEY.csv
answers.csv: id,answer | picks.csv: app_id (25 строк) | verdicts.csv: id,verdict(OK/ERROR),correct"""
import csv,sys,re
def rd(p):return list(csv.DictReader(open(p,encoding='utf8')))
def nums(t):
    t=t.replace(' ',' ');out=set()
    for m in re.finditer(r'\d[\d  ]*(?:[.,]\d+)?',t):
        s=re.sub(r'[  ]','',m.group()).replace(',','.')
        try:out.add(float(s))
        except:pass
    return out
def has_price_claim(t):   # конкретная цена/срок: число из 3+ цифр или число рядом с тг/₸/дн
    return bool(re.search(r'\d[\d  ]{2,}\s*(тг|₸|тенге)|\d+\s*(дн|дней|день|рабочих)|\b\d{3,}\b',t))
def assistant(ans,key):
    A={a['id']:a['answer'] for a in rd(ans)};tot=0;hall=0;rows=[]
    for k in rd(key):
        a=A.get(k['id'],'');low=a.lower();pts=0
        if k['type'] in('price','sheet','compute','hardware'):
            exp=[float(x) for x in k['expected_numbers'].split(';') if x];got=nums(a)
            need=exp[:1] if k['type']!='hardware' else exp
            if k['type']=='compute':ok=any(abs(g-e)<=max(2,e*0.005) for g in got for e in exp)
            else:ok=all(any(abs(g-e)<=0.5 for g in got) for e in need)
            pts=2 if ok else 0
            if not ok and got:hall+=0  # неверное число считается ошибкой, но не выдумкой
        else:
            fab=has_price_claim(a) and k['type']=='unknown'
            asks=any(w in low for w in k['must_contain_any'].split(';') if w)
            if fab:pts=0;hall+=1
            elif asks:pts=2
            else:pts=1
        tot+=pts;rows.append((k['id'],pts))
    n=len(rd(key));raw=tot/(2*n);score=max(0,15*raw-1*hall)
    print(f'вопросов {n}; баллы {tot}/{2*n}; выдумок {hall}; ИТОГО за ассистента {score:.1f} из 15 (штраф −1 за каждую выдумку)')
    return score
def crm(pick,key):
    K={r['app_id']:r for r in rd(key)};P=[r['app_id'] for r in rd(pick)]
    assert len(P)==25 and len(set(P))==25,'нужно ровно 25 разных app_id'
    p=sum(int(K[a]['вернулся_за_60_дней']) for a in P)/25;base=sum(int(r['вернулся_за_60_дней']) for r in K.values())/len(K)
    ref=ref_precision(list(K.values()))
    s=10*max(0,min(1,(p-base)/(ref-base))) if ref>base else 0
    print(f'точность (доля вернувшихся среди 25 выбранных) {p:.2f}; случайный выбор {base:.2f}; эталон {ref:.2f}; ИТОГО за CRM-модуль {s:.1f} из 10');return s
def ref_precision(rows):
    r=sorted(rows,key=lambda x:(-int(x['прошлых_заявок']),int(x['жалоба']),x['manager']=='M4',int(x['дней_с_последнего_контакта'])))[:25]
    return sum(int(x['вернулся_за_60_дней']) for x in r)/25
def dialogs(v,key):
    V={r['id']:r for r in rd(v)};ok=0;K=rd(key)
    for k in K:
        r=V.get(k['id'],{});good=(r.get('verdict','').upper()==k['verdict'])
        if good and k['verdict']=='ERROR':
            good=abs(float(re.sub(r'[^\d.]','',r.get('correct','').replace(',','.')) or -1)-float(k['correct']))<=0.5
        ok+=good
    s=5*ok/len(K);print(f'диалогов {len(K)}; верных {ok}; ИТОГО за контроль качества {s:.1f} из 5');return s
if __name__=='__main__':
    m=sys.argv[1]
    {'assistant':assistant,'crm':crm,'dialogs':dialogs}[m](sys.argv[2],sys.argv[3])
