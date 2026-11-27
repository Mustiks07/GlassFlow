from audit import df, y, refsort
from pathlib import Path
import numpy as np
import pandas as pd
import json

# Research-only regularized logistic regression. No ID/day or future outcome features.
def features(d, full=False):
    num=['прошлых_заявок','дней_с_последнего_контакта','жалоба']
    cat=['manager','тип_клиента']
    if full:
        num+=['сумма_тг','доставка','скидка','ответ_через_мин','продано']
        cat+=['группа_товара','канал']
    f=d[num].astype(float).copy()
    if full:f['сумма_тг']=np.log1p(f['сумма_тг'])
    return pd.concat([f,pd.get_dummies(d[cat],dtype=float)],axis=1).astype(float)

def fit_predict(train,test,full=False,C=1.0):
    a=features(train,full); b=features(test,full).reindex(columns=a.columns,fill_value=0)
    mean=a.mean();std=a.std().replace(0,1)
    X=np.column_stack([np.ones(len(a)),((a-mean)/std).values]);Z=np.column_stack([np.ones(len(b)),((b-mean)/std).values])
    target=train[y].values;w=np.zeros(X.shape[1]);reg=np.eye(X.shape[1])/C;reg[0,0]=0
    for _ in range(60):
        p=1/(1+np.exp(-np.clip(X@w,-30,30)))
        g=X.T@(p-target)+reg@w
        h=(X.T*(p*(1-p)))@X+reg+1e-8*np.eye(X.shape[1])
        step=np.linalg.solve(h,g);w-=step
        if np.linalg.norm(step)<1e-7:break
    return 1/(1+np.exp(-np.clip(Z@w,-30,30)))

def score(train,test):
    res={'n_train':len(train),'n_test':len(test),'base':float(test[y].mean()),'reference_p25':float(refsort(test).head(25)[y].mean())}
    for name,full in [('logit_core',False),('logit_full',True)]:
        pr=fit_predict(train,test,full)
        res[name+'_p25']=float(test.iloc[np.argsort(-pr,kind='stable')[:25]][y].mean())
    return res

results=[]
for seed in range(10):
    rng=np.random.default_rng(seed);idx=rng.permutation(len(df));
    results.append({'split':f'random_{seed}',**score(df.iloc[idx[260:]],df.iloc[idx[:260]])})
clients=df.client_id.unique()
for seed in range(10):
    rng=np.random.default_rng(seed);ix=rng.permutation(clients);n=round(len(clients)*260/700)
    test=df[df.client_id.isin(ix[:n])];train=df[~df.client_id.isin(ix[:n])]
    results.append({'split':f'group_{seed}',**score(train,test)})
test=df.iloc[-260:];train=df.iloc[:-260];cutoff=int(test['день_года'].min())
results.append({'split':'temporal_unpurged',**score(train,test)})
results.append({'split':'temporal_60day_purge',**score(df[df['день_года']<=cutoff-60],test)})
r=pd.DataFrame(results)
print('\nEVALUATION\n'+r.to_string(index=False))
print('\nSPLIT MEANS\n'+r.assign(kind=r.split.str.replace(r'_\d+$','',regex=True)).groupby('kind').mean(numeric_only=True).to_string())
chron=df.sort_values(['день_года','app_id'],kind='stable').copy()
chron['next_day']=chron.groupby('client_id')['день_года'].shift(-1)
observable=(chron['день_года']<=chron['день_года'].max()-60)
next60=(chron['next_day']-chron['день_года']).between(0,60).astype(int)
print('Return labels vs observed future rows for mature records:',{'n':int(observable.sum()),'actual_next60_rate':float(next60[observable].mean()),'label_rate':float(chron.loc[observable,y].mean()),'agreement':float((next60[observable]==chron.loc[observable,y]).mean())})
print('Recency consistency:',{'rows_with_history':int((df['прошлых_заявок']>0).sum()),'exact_match':int(((chron['день_года']-chron.groupby('client_id')['день_года'].shift(1))==chron['дней_с_последнего_контакта']).sum())})
r.to_csv(Path(__file__).parent/'baseline_evaluation.csv',index=False)
