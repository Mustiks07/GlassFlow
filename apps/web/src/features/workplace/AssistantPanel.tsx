import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowDownToLine, MessageSquareText, Send, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useApi } from '../../api/context';
import { asApiError } from '../../api/errors';
import type { AssistantReply, Dataset, Quote } from '../../api/types';
import { parseDimensionsPair } from '../../lib/units';
import { useAppStore, useQuoteDraft } from '../../state/store';
import { Button, Details, ErrorState, Field, OfflineAiNotice, Panel, StatusBadge } from '../../ui/kit';
import { kbVersionOf } from '../shell/dataset';
import { EvidenceList } from './EvidenceList';

interface Turn {
  role: 'user' | 'assistant';
  text: string;
  reply?: AssistantReply;
}

const REPLY_STATUS: Record<string, string> = {
  clarification: 'Нужно уточнение',
  manager_handoff: 'Передача менеджеру',
  limited: 'Ограниченный режим',
};

const PARAM_LABEL: Record<string, string> = {
  catalog_product_id: 'Товар',
  length_mm: 'Длина, мм',
  width_mm: 'Ширина, мм',
  quantity: 'Количество',
  processing: 'Обработка',
  sides: 'Стороны',
  thickness_mm: 'Толщина, мм',
  color: 'Цвет',
};

export function AssistantPanel({ dataset, onQuote }: { dataset: Dataset; onQuote: (quote: Quote) => void }) {
  const { api } = useApi();
  const draft = useQuoteDraft(dataset.dataset_id);
  const updateDraft = useAppStore(state => state.updateQuoteDraft);
  const [turns, setTurns] = useState<Turn[]>([]);
  const kbVersion = kbVersionOf(dataset);

  // Restore an existing conversation after refresh (GET /assistant/conversations/{id}).
  const restored = useQuery({
    queryKey: ['conversation', dataset.dataset_id, draft.conversationId],
    enabled: Boolean(draft.conversationId) && turns.length === 0,
    queryFn: ({ signal }) => api.getConversation(draft.conversationId as string, dataset.dataset_id, signal),
    retry: false,
  });
  useEffect(() => {
    if (restored.data && turns.length === 0) {
      setTurns(
        restored.data.turns.flatMap(turn => [
          { role: 'user' as const, text: turn.user_text },
          { role: 'assistant' as const, text: turn.reply.answer, reply: turn.reply },
        ]),
      );
    }
  }, [restored.data, turns.length]);

  const send = useMutation({
    mutationFn: (text: string) =>
      api.assistantTurn({
        dataset_id: dataset.dataset_id,
        text,
        conversation_id: draft.conversationId,
        customer_id: draft.customerId || null,
        kb_version: kbVersion ?? '',
        inventory_mode: 'free_whole_remnants',
      }),
    onSuccess: (reply, text) => {
      setTurns(current => [...current, { role: 'user', text }, { role: 'assistant', text: reply.answer, reply }]);
      updateDraft(dataset.dataset_id, { conversationId: reply.conversation_id, request: '' });
      if (reply.quote) onQuote(reply.quote);
    },
  });

  const lastReply = [...turns].reverse().find(turn => turn.reply)?.reply;
  const offline = lastReply?.mode === 'local_limited' || Boolean(lastReply?.ai_unavailable_reason) || (send.error && ['unavailable', 'offline', 'timeout', 'rate_limited'].includes(asApiError(send.error).kind));

  const applyParameters = (reply: AssistantReply) => {
    const params = reply.card?.confirmed_parameters ?? reply.quote?.confirmed_parameters ?? {};
    updateDraft(dataset.dataset_id, {
      catalogProductId: params.catalog_product_id ?? draft.catalogProductId,
      length: params.length_mm ?? draft.length,
      width: params.width_mm ?? draft.width,
      quantity: params.quantity ?? draft.quantity,
      processing: (params.processing as typeof draft.processing) ?? draft.processing,
    });
  };

  /** Local, deterministic helper: if the request contains "450×370 мм", offer it to the form. */
  const detected = parseDimensionsPair((draft.request.match(/\d+(?:[.,]\d+)?\s*[a-zа-яё]*\s*[x×х*]\s*\d+(?:[.,]\d+)?\s*[a-zа-яё]*/i) ?? [''])[0]);

  return (
    <Panel
      title="Запрос клиента"
      subtitle="Свободный текст по-русски. Ассистент уточняет недостающее и вызывает те же сервисы расчета и подбора."
      actions={
        turns.length > 0 && (
          <Button
            variant="ghost"
            icon={<Trash2 size={14} aria-hidden="true" />}
            onClick={() => {
              setTurns([]);
              updateDraft(dataset.dataset_id, { conversationId: null });
            }}
          >
            Новый диалог
          </Button>
        )
      }
    >
      {turns.length > 0 && (
        <ol className="chat" aria-label="История уточнений">
          {turns.map((turn, index) => (
            <li key={index} className={`chat-turn ${turn.role}`}>
              <span className="chat-role">{turn.role === 'user' ? 'Клиент' : 'Ответ клиенту'}</span>
              <p>{turn.text}</p>
              {turn.reply && <ReplyDetails reply={turn.reply} onApply={() => applyParameters(turn.reply!)} />}
            </li>
          ))}
        </ol>
      )}
      {offline && <OfflineAiNotice detail={send.error ? asApiError(send.error).message : lastReply?.ai_unavailable_reason ?? 'ответ сформирован локальными правилами'} />}
      {!kbVersion && <StatusBadge tone="warn">Версия базы знаний не определена для этого набора — расчет недоступен</StatusBadge>}
      <form
        className="stack"
        onSubmit={event => {
          event.preventDefault();
          const text = draft.request.trim();
          if (text && !send.isPending) send.mutate(text);
        }}
      >
        <Field label="Текст запроса" hint="Например: «стекло прозрачное 6 мм 450×370, евро-кромка по кругу»">
          {props => (
            <textarea
              {...props}
              rows={3}
              maxLength={16000}
              value={draft.request}
              onChange={event => updateDraft(dataset.dataset_id, { request: event.target.value })}
              onKeyDown={event => {
                if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
          )}
        </Field>
        <div className="row">
          <Button type="submit" variant="primary" icon={<Send size={14} aria-hidden="true" />} busy={send.isPending} disabled={!draft.request.trim() || !kbVersion}>
            Отправить ассистенту
          </Button>
          {detected && detected.length.ok && detected.width.ok && (
            <Button
              variant="ghost"
              icon={<ArrowDownToLine size={14} aria-hidden="true" />}
              onClick={() =>
                updateDraft(dataset.dataset_id, {
                  length: detected.length.ok ? detected.length.original.trim() : draft.length,
                  width: detected.width.ok ? detected.width.original.trim() : draft.width,
                })
              }
            >
              Перенести размеры {detected.length.mm}×{detected.width.mm} мм в форму
            </Button>
          )}
          <small className="muted">Ctrl+Enter — отправить</small>
        </div>
        {send.error && !offline && <ErrorState error={send.error} onRetry={() => send.mutate(draft.request.trim())} context="Ассистент" />}
        {send.error && offline && <p className="small muted">Текст запроса сохранен. Заполните параметры вручную ниже — расчет выполнится локально.</p>}
      </form>
    </Panel>
  );
}

function ReplyDetails({ reply, onApply }: { reply: AssistantReply; onApply: () => void }) {
  const card = reply.card;
  const params = Object.entries(card?.confirmed_parameters ?? reply.quote?.confirmed_parameters ?? {});
  const assumptions = card?.assumptions ?? reply.quote?.assumptions ?? [];
  return (
    <div className="reply-details">
      {reply.clarification && (
        <p className="clarification">
          <MessageSquareText size={14} aria-hidden="true" /> Уточнение: {reply.clarification}
        </p>
      )}
      <div className="row wrap small">
        <StatusBadge tone={reply.mode === 'online' ? 'info' : 'warn'}>{reply.mode === 'online' ? 'AI-ответ' : 'Локальный режим'}</StatusBadge>
        {reply.status && reply.status !== 'answered' && <StatusBadge tone="warn">{REPLY_STATUS[reply.status]}</StatusBadge>}
        {reply.verifier_status === 'unsupported_replaced' && <StatusBadge tone="warn">Непроверенное утверждение заменено</StatusBadge>}
        {card?.needs_manager && <StatusBadge tone="warn">Нужен менеджер</StatusBadge>}
        {reply.provider && (
          <span className="muted">
            {reply.provider} · {reply.model_id}
          </span>
        )}
      </div>
      {params.length > 0 && (
        <div className="confirmed-params">
          <strong className="small">Подтвержденные параметры</strong>
          <ul className="chips">
            {params.map(([key, value]) => (
              <li key={key}>
                {PARAM_LABEL[key] ?? key}: <b>{value}</b>
              </li>
            ))}
          </ul>
          <Button variant="ghost" onClick={onApply} icon={<ArrowDownToLine size={14} aria-hidden="true" />}>
            Перенести в форму расчета
          </Button>
        </div>
      )}
      {assumptions.length > 0 && (
        <div className="assumptions small">
          <strong>Предположения (не подтверждены):</strong> {assumptions.join('; ')}
        </div>
      )}
      {card && card.missing_parameters.length > 0 && (
        <div className="small">
          <strong>Не хватает:</strong> {card.missing_parameters.join(', ')}
        </div>
      )}
      {card?.normalized_dimensions && <div className="small">Размеры после нормализации: {card.normalized_dimensions}</div>}
      {(reply.evidence.length > 0 || Boolean(reply.tool_calls?.length) || Boolean(card?.facts.length)) && (
        <Details summary="Источники, проверенные факты и вызовы инструментов">
          <EvidenceList evidence={reply.evidence} />
          {card && card.facts.length > 0 && (
            <ul className="plain small">
              {card.facts.map(fact => (
                <li key={fact.fact_id}>
                  {fact.kind}: <b>{fact.value}</b>
                  {fact.unit ? ` ${fact.unit}` : ''} · <span className="mono">{fact.source_ref}</span> · {fact.status === 'supported' ? 'подтверждено' : fact.status === 'unknown' ? 'неизвестно' : 'не подтверждено'}
                </li>
              ))}
            </ul>
          )}
          {reply.tool_calls && reply.tool_calls.length > 0 && (
            <ul className="plain small mono">
              {reply.tool_calls.map((call, index) => (
                <li key={index}>
                  {call.tool}: {call.status}
                  {call.summary ? ` — ${call.summary}` : ''}
                </li>
              ))}
            </ul>
          )}
          {reply.answer_path && <p className="small muted">Путь ответа: {reply.answer_path}{reply.latency_ms ? ` · ${reply.latency_ms} мс` : ''}</p>}
        </Details>
      )}
    </div>
  );
}
