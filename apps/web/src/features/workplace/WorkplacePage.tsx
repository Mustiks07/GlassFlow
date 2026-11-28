import { useEffect, useState } from 'react';
import type { Dataset, Quote } from '../../api/types';
import { RequireDataset } from '../shell/RequireDataset';
import { AssistantPanel } from './AssistantPanel';
import { CandidatePanel } from './CandidatePanel';
import { CrmBlock } from './CrmBlock';
import { QualityPanel } from './QualityPanel';
import { QuotePanel } from './QuotePanel';
import { MODE_LABEL } from '../shell/dataset';
import { OrderFlowPanel } from './OrderFlowPanel';
import { BasketPanel } from './BasketPanel';
import { EconomicsPanel } from './EconomicsPanel';
import { WorkflowPanel } from './WorkflowPanel';
import { ReviewPanel } from './ReviewPanel';
import { useRoute } from '../../state/router';

export function WorkplacePage() {
  return <RequireDataset>{dataset => <Workplace dataset={dataset} key={dataset.dataset_id} />}</RequireDataset>;
}

function Workplace({ dataset }: { dataset: Dataset }) {
  const route = useRoute();
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteStale, setQuoteStale] = useState(false);
  const [tab, setTab] = useState<'request' | 'quality' | 'basket' | 'economics'>('request');
  useEffect(() => {
    if (route.params.has('basket_id')) setTab('basket');
    else if (route.params.has('order_id')) setTab('request');
  }, [route]);
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Рабочее место · {MODE_LABEL[dataset.mode]}</p>
          <h1>Запрос клиента → проверенный расчет → остаток → действие</h1>
        </div>
        <div className="segmented" role="tablist" aria-label="Режим рабочего места">
          <button role="tab" aria-selected={tab === 'request'} className={tab === 'request' ? 'active' : ''} onClick={() => setTab('request')}>
            Запрос и расчет
          </button>
          <button role="tab" aria-selected={tab === 'quality'} className={tab === 'quality' ? 'active' : ''} onClick={() => setTab('quality')}>
            Проверка ответа менеджера
          </button>
          <button role="tab" aria-selected={tab === 'basket'} className={tab === 'basket' ? 'active' : ''} onClick={() => setTab('basket')}>Корзина и расход</button>
          <button role="tab" aria-selected={tab === 'economics'} className={tab === 'economics' ? 'active' : ''} onClick={() => setTab('economics')}>Экономика</button>
        </div>
      </header>
      <WorkflowPanel dataset={dataset} />
      <ReviewPanel dataset={dataset} />
      {tab === 'economics' ? <EconomicsPanel dataset={dataset} /> : tab === 'basket' ? <BasketPanel dataset={dataset} /> : tab === 'quality' ? (
        <QualityPanel dataset={dataset} />
      ) : (
        <div className="workplace-grid">
          <div className="stack">
            <AssistantPanel dataset={dataset} onQuote={setQuote} />
            <QuotePanel dataset={dataset} quote={quote} onQuote={setQuote} onStaleChange={setQuoteStale} />
          </div>
          <div className="stack">
            <CandidatePanel dataset={dataset} quote={quote} quoteStale={quoteStale} onQuote={setQuote} />
            <CrmBlock dataset={dataset} quote={quote} />
            <OrderFlowPanel dataset={dataset} quote={quote} />
          </div>
        </div>
      )}
    </div>
  );
}
