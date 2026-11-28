import type { ReactNode } from 'react';
import type { Dataset } from '../../api/types';
import { href } from '../../state/router';
import { EmptyState, ErrorState, LoadingState } from '../../ui/kit';
import { useCurrentDataset } from './dataset';

/** Every domain screen is scoped to an explicitly selected dataset. */
export function RequireDataset({ children }: { children: (dataset: Dataset) => ReactNode }) {
  const { dataset, datasets, missing } = useCurrentDataset();
  if (datasets.isLoading) return <LoadingState label="Загружаем наборы данных…" />;
  if (datasets.isError) return <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} context="Список наборов" />;
  if (!dataset)
    return (
      <EmptyState
        title={missing ? 'Выбранный набор больше не существует' : 'Набор данных не выбран'}
        action={
          <a className="btn btn-primary" href={href('settings', 'data')}>
            <span>Импорт и наборы данных</span>
          </a>
        }
      >
        {datasets.data && datasets.data.length > 0
          ? 'Выберите набор в верхней панели. Все расчеты, резервы и задачи привязаны к выбранному dataset_id.'
          : 'Импортируйте пакет организаторов или собственные файлы: предпросмотр покажет ошибки до создания снимка.'}
      </EmptyState>
    );
  return <>{children(dataset)}</>;
}
