from pathlib import Path
import sys, json, csv
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'inputs/PACK_for_teams/2_assistant_crm'
df = pd.read_csv(BASE / 'applications_open.csv')
y = 'вернулся_за_60_дней'
lines = []
def out(s):
    lines.append(str(s))
    print(s)

out(f'Shape: {df.shape}; duplicate app_id {df.app_id.duplicated().sum()}; unique clients {df.client_id.nunique()}; NA {df.isna().sum().sum()}')
out(df.describe(include='all').to_string())
out(f'Base return rate {df[y].mean():.6f} ({df[y].sum()}/{len(df)})')
for c in ['manager','группа_товара','канал','тип_клиента','прошлых_заявок','жалоба','доставка','скидка','продано']:
    out(df.groupby(c)[y].agg(['count','sum','mean']).to_string())
out('Numeric correlation:\n'+df.select_dtypes('number').corr()[y].sort_values().to_string())
df['manager_M4']=(df.manager=='M4').astype(int)
def refsort(d):
    return d.sort_values(['прошлых_заявок','жалоба','manager_M4','дней_с_последнего_контакта'], ascending=[False,True,True,True],kind='stable')
out('Reference top25: '+str(refsort(df).head(25)[y].agg(['sum','mean']).to_dict()))
out('Dates:\n'+df.groupby(pd.cut(df['день_года'],bins=6),observed=True)[y].agg(['count','sum','mean']).to_string())
out('Client repeated-label variability:\n'+df.groupby('client_id')[y].nunique().value_counts().to_string())
out('Manager dashboard:\n'+df.groupby('manager').agg(applications=('app_id','count'),response_minutes=('ответ_через_мин','mean'),conversion=('продано','mean'),return_rate=(y,'mean'),mean_amount=('сумма_тг','mean'),complaint_rate=('жалоба','mean'),discount_rate=('скидка','mean')).round(4).to_string())
out('Mean sold amount:\n'+df.loc[df['продано']==1].groupby('manager')['сумма_тг'].mean().round(2).to_string())
out('Prior applications field vs preceding rows per client:')
chron = df.sort_values(['день_года','app_id'],kind='stable')
prior=chron.groupby('client_id').cumcount()
out({'equal':int((chron['прошлых_заявок']==prior).sum()),'rows':len(df),'max_error':int((chron['прошлых_заявок']-prior).abs().max())})
kb=json.loads((BASE/'ksm_knowledge_base.json').read_text(encoding='utf-8'))
out('KB counts: '+str(pd.Series([r['вид'] for r in kb['товары']]).value_counts().to_dict()))
out('KB ID duplicates: '+str(len(kb['товары'])-len({r['id'] for r in kb['товары']})))
out('Missing price fields: '+str({k:sum(r.get(k) is None for r in kb['товары'] if r['вид']=='material') for k in ['цена_за_м2_тг','цена_листа_тг']}))
(Path(__file__).parent/'audit.txt').write_text('\n\n'.join(lines),encoding='utf-8')
