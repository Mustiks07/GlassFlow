from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from glassflow.contracts.insights import ComparableRequest
from glassflow.main import create_app
from glassflow.modules.insights import comparable


def row(identity, manager, group, response, sold, amount, returned, **changes):
    return SimpleNamespace(public_id=identity, source_row=int(identity[1:]), data={
        'app_id': identity, 'client_id': 'same-client', 'manager': manager, 'группа_товара': group,
        'канал': 'chat', 'тип_клиента': 'company', 'день_года': '100', 'ответ_через_мин': str(response),
        'продано': str(sold), 'сумма_тг': str(amount), 'вернулся_за_60_дней': returned,
        'жалоба': '0', 'скидка': '0', **changes})


def test_comparable_groups_preserve_organizer_denominators_and_reveal_mix(monkeypatch):
    # M1 is faster in each stratum but has mostly difficult work. No causal/rank inference.
    rows = []
    for manager, group, n, response in [('M1','simple',1,1),('M1','hard',9,20),('M2','simple',9,2),('M2','hard',1,21)]:
        for _ in range(n):
            rows.append(row(f'A{len(rows)+1}',manager,group,response,1,100,'1'))
    monkeypatch.setattr(comparable,'records',lambda *_: rows)
    result = comparable.compare(None,ComparableRequest(dataset_id='d',managers=['M1','M2']))
    assert result.overall[0].mean_response_minutes > result.overall[1].mean_response_minutes
    assert all(g.managers[0].mean_response_minutes < g.managers[1].mean_response_minutes for g in result.groups)
    assert result.matched_application_count==20 and result.total_groups==2
    assert all(g.warnings for g in result.groups)
    assert 'не является рейтингом' in result.caveat_ru


def test_missing_labels_and_zero_sales_remain_unknown(monkeypatch):
    rows=[row('A1','M1',None,10,0,90000,None),row('A2','M1',None,30,0,10000,'1')]
    monkeypatch.setattr(comparable,'records',lambda *_:rows)
    result=comparable.compare(None,ComparableRequest(dataset_id='d',managers=['M1']))
    value=result.groups[0].managers[0]
    assert result.groups[0].dimensions['product_group'] is None
    assert value.mean_response_minutes==20 and value.mean_sale_tg is None
    assert value.returns.denominator==1 and value.returns.numerator==1
    assert value.evidence['returns'].total==2 and value.evidence['returns'].completeness==.5
    assert any(w.code=='INCOMPLETE' for w in result.groups[0].warnings)


def test_question_is_an_allowlisted_projection_and_complete_metric_is_not_overasked(monkeypatch):
    from glassflow.contracts.insights import AnalyticsQuestion
    monkeypatch.setattr(comparable,'records',lambda *_:[row('A1','M1','glass',10,1,15000,'1')])
    result=comparable.answer(None,AnalyticsQuestion(dataset_id='d',question='Сколько средний чек у М1 по группе glass?'))
    assert result.status=='answered' and result.metric=='mean_sale_tg'
    assert result.comparison.overall[0].mean_sale_tg=='15000.00'
    assert comparable.answer(None,AnalyticsQuestion(dataset_id='d',question='DROP TABLE applications')).status=='clarification'
    with pytest.raises(ValueError):
        ComparableRequest(dataset_id='d',dimensions=['channel','channel'])


def test_actual_api_reuses_the_original_metrics_on_the_imported_dataset(tmp_path):
    with TestClient(create_app(tmp_path,testing=True)) as client:
        client.get('/api/v1/session')
        source=client.post('/api/v1/datasets/demo',headers={'Idempotency-Key':'analytics-real'}).json()
        d=source['dataset_id']
        original=client.get('/api/v1/analytics/managers',params={'dataset_id':d}).json()
        response=client.post('/api/v1/analytics/comparable',json={'dataset_id':d})
        assert response.status_code==200,response.text
        view=response.json()
        assert view['overall']==original and sum(g['application_count'] for g in view['groups'])==700
        answer=client.post('/api/v1/analytics/questions',json={'dataset_id':d,'question':'Сравни время ответа M1 и M2 по каналам'})
        assert answer.status_code==200 and answer.json()['status']=='answered'
        assert answer.json()['origin']=='deterministic_aggregates'
