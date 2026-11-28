/** Employee-facing labels. Machine values remain in API requests and diagnostics. */
export const FIELD_LABELS: Record<string, string> = {
  dataset_id: 'Набор данных', name: 'Название', customer_id: 'Заказчик', customer_ref: 'Заказчик',
  dimensions: 'Размеры', length_mm: 'Длина', width_mm: 'Ширина', quantity: 'Количество',
  material_id: 'Материал', catalog_product_id: 'Товар', processing: 'Обработка', sides: 'Стороны обработки',
  expected_version: 'Версия записи', expected_revision: 'Версия расчёта', revision: 'Версия',
  operator: 'Сотрудник', owner: 'Ответственный', confirmed_by: 'Кто подтверждает',
  remnant_id: 'Кусок', plan_id: 'План раскроя', file: 'Файл', files: 'Файлы', due_at: 'Срок',
  monthly_budget_tg: 'Денежный бюджет', quota_token_budget: 'Лимит включённой квоты',
  model_id: 'Модель', provider: 'Сервис ИИ', gateway_url: 'Адрес шлюза', api_key: 'Ключ доступа',
  active_seconds: 'Активное время', result_ref: 'Ссылка на результат', input_hash: 'Входные данные',
  price_basis: 'Единица расчёта цены', price_meaning: 'Основание цены', unit: 'Единица',
};
export function fieldLabel(name: string): string { return FIELD_LABELS[name] ?? 'Поле формы'; }

export function humanText(text: string | null | undefined, fallback = 'Требуется проверка данных.'): string {
  if (!text || !/[А-Яа-яЁё]/.test(text) || /[{}]|Traceback|\b(?:SELECT|INSERT|TypeError|KeyError|AssertionError)\b/.test(text)) return fallback;
  return text;
}

export function stageLabel(stage?: string): string {
  const labels: Record<string, string> = {
    queued: 'В очереди', running: 'Выполняется', starting: 'Подготовка', completed: 'Готово',
    failed: 'Не завершено из-за ошибки', cancelled: 'Остановлено', interrupted: 'Прервано перезапуском',
    preparing: 'Подготовка данных', validating: 'Проверка результата', exporting: 'Сохранение файлов',
    solving: 'Поиск раскроя', greedy: 'Первый допустимый раскрой', improving: 'Улучшение раскроя',
    baseline: 'Первый полный комплект', cards: 'Подготовка карточек', quality: 'Проверка диалогов',
    assistant: 'Ответы на вопросы', crm: 'Отбор заявок', budget_expired: 'Время прогона истекло',
  };
  return labels[stage ?? ''] ?? humanText(stage, 'Выполнение задания');
}

export function errorAction(code?: string | null): string {
  if (!code) return '—';
  if (/BUDGET|DEADLINE|TIMEOUT/.test(code)) return 'Время истекло. Проверьте сохранённый результат или задайте новый бюджет.';
  if (/STALE|VERSION|CONTEXT_CHANGED/.test(code)) return 'Данные изменились. Обновите запись и повторите проверку.';
  if (/QUOTA|RATE|429/.test(code)) return 'Достигнут лимит сервиса. Повторите позже или проверьте доступную квоту.';
  if (/CANCEL|INTERRUPT/.test(code)) return 'Выполнение остановлено. Сохранённые результаты доступны.';
  if (/INVALID|UNVERIFIED|REVIEW|CHECKPOINT/.test(code)) return 'Результат не прошёл проверку. Проверьте данные перед повтором.';
  return 'Не удалось завершить действие. Повторите проверку; если ошибка сохраняется, передайте подробности поддержке.';
}
