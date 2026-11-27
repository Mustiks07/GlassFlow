import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { newIdempotencyKey } from '../../api/client';
import { useApi } from '../../api/context';
import { asApiError } from '../../api/errors';
import type { Dataset, Material, Remnant } from '../../api/types';
import { formatDims } from '../../lib/format';
import { parseLength } from '../../lib/units';
import { ConfirmDialog, Field } from '../../ui/kit';

/** Add a working remnant: material, integer size, location, explicit defect; age unknown stays unknown. */
export function AddRemnantDialog({ dataset, materials, open, onOpenChange }: { dataset: Dataset; materials: Material[]; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ material_id: '', length: '', width: '', location: '', defect: '' as '' | '0' | '1', age: '' });
  const [key, setKey] = useState(newIdempotencyKey);
  const [touched, setTouched] = useState(false);
  const length = parseLength(form.length);
  const width = parseLength(form.width);
  const errors: Record<string, string | undefined> = {
    material_id: form.material_id ? undefined : 'Выберите материал',
    length: length.ok ? undefined : length.reason,
    width: width.ok ? undefined : width.reason,
    location: form.location.trim() ? undefined : 'Укажите место хранения',
    defect: form.defect ? undefined : 'Укажите явно: есть дефект или нет',
    age: form.age === '' || /^\d+$/.test(form.age) ? undefined : 'Целое число дней или пусто (неизвестно)',
  };
  const valid = Object.values(errors).every(value => !value);
  const mutation = useMutation({
    mutationFn: () =>
      api.addRemnant(
        {
          dataset_id: dataset.dataset_id,
          material_id: form.material_id,
          dimensions: { length_mm: length.ok ? length.mm : 0, width_mm: width.ok ? width.mm : 0 },
          defect: form.defect === '1',
          location_raw: form.location.trim(),
          age_days: form.age === '' ? null : Number(form.age),
        },
        key,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
      setKey(newIdempotencyKey());
      setForm({ material_id: '', length: '', width: '', location: '', defect: '', age: '' });
      setTouched(false);
      onOpenChange(false);
    },
  });
  const show = (name: string) => (touched ? errors[name] : undefined) ?? (mutation.error ? asApiError(mutation.error).fieldMessage(name) : undefined);
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={value => {
        onOpenChange(value);
        if (!value) mutation.reset();
      }}
      title="Добавить остаток"
      action="Новый кусок появится в рабочей копии со статусом «свободен». Исходный снимок не меняется."
      affected={[{ label: 'Набор', value: dataset.name }]}
      confirmLabel="Добавить остаток"
      onConfirm={() => {
        setTouched(true);
        if (valid) mutation.mutate();
      }}
      busy={mutation.isPending}
      error={mutation.error}
    >
      <div className="form-grid">
        <Field label="Материал" required error={show('material_id')}>
          {props => (
            <select {...props} value={form.material_id} onChange={event => setForm({ ...form, material_id: event.target.value })}>
              <option value="">Выберите</option>
              {materials.map(material => (
                <option key={material.material_id} value={material.material_id}>
                  {material.material_id} · {material.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Место хранения" required error={show('location')} hint="например: Стеллаж A, ячейка 7">
          {props => <input {...props} value={form.location} onChange={event => setForm({ ...form, location: event.target.value })} />}
        </Field>
        <Field label="Длина" required error={show('length')} hint={length.ok && length.converted ? `= ${length.mm} мм` : 'мм'}>
          {props => <input {...props} value={form.length} onChange={event => setForm({ ...form, length: event.target.value })} />}
        </Field>
        <Field label="Ширина" required error={show('width')} hint={width.ok && width.converted ? `= ${width.mm} мм` : 'мм'}>
          {props => <input {...props} value={form.width} onChange={event => setForm({ ...form, width: event.target.value })} />}
        </Field>
        <Field label="Дефект" required error={show('defect')}>
          {props => (
            <select {...props} value={form.defect} onChange={event => setForm({ ...form, defect: event.target.value as '' | '0' | '1' })}>
              <option value="">Не указано</option>
              <option value="0">Без дефекта</option>
              <option value="1">Есть дефект</option>
            </select>
          )}
        </Field>
        <Field label="Возраст, дней" error={show('age')} hint="Пусто — неизвестно (не ноль)">
          {props => <input {...props} inputMode="numeric" value={form.age} onChange={event => setForm({ ...form, age: event.target.value })} />}
        </Field>
      </div>
    </ConfirmDialog>
  );
}

export function MeasureDialog({ dataset, remnant, onClose }: { dataset: Dataset; remnant: Remnant; onClose: () => void }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const [length, setLength] = useState(String(remnant.dimensions.length_mm));
  const [width, setWidth] = useState(String(remnant.dimensions.width_mm));
  const [reason, setReason] = useState('');
  const [key] = useState(newIdempotencyKey);
  const l = parseLength(length);
  const w = parseLength(width);
  const mutation = useMutation({
    mutationFn: () =>
      api.measureRemnant(
        remnant.remnant_id,
        {
          dataset_id: dataset.dataset_id,
          expected_version: remnant.version ?? 0,
          previous_dimensions: remnant.dimensions,
          dimensions: { length_mm: l.ok ? l.mm : 0, width_mm: w.ok ? w.mm : 0 },
          reason: reason.trim(),
        },
        key,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
      queryClient.invalidateQueries({ queryKey: ['plans', dataset.dataset_id] });
      onClose();
    },
  });
  return (
    <ConfirmDialog
      open
      onOpenChange={open => !open && onClose()}
      title={`Новый замер ${remnant.remnant_id}`}
      action="Замер создаст новую версию куска. Зависимые планы, предложения и карточки станут устаревшими и потребуют перепроверки; действующий план не меняется автоматически."
      affected={[
        { label: 'Прежний размер', value: formatDims(remnant.dimensions) },
        { label: 'Новый размер', value: l.ok && w.ok ? formatDims({ length_mm: l.mm, width_mm: w.mm }) : 'введите целые мм' },
        { label: 'Ожидаемая версия', value: String(remnant.version ?? 0) },
      ]}
      confirmLabel="Сохранить замер"
      onConfirm={() => l.ok && w.ok && reason.trim() && mutation.mutate()}
      busy={mutation.isPending}
      error={mutation.error}
    >
      <div className="form-grid">
        <Field label="Длина" error={l.ok ? undefined : l.reason}>
          {props => <input {...props} value={length} onChange={event => setLength(event.target.value)} />}
        </Field>
        <Field label="Ширина" error={w.ok ? undefined : w.reason}>
          {props => <input {...props} value={width} onChange={event => setWidth(event.target.value)} />}
        </Field>
      </div>
      <Field label="Причина замера" required>
        {props => <input {...props} value={reason} onChange={event => setReason(event.target.value)} />}
      </Field>
    </ConfirmDialog>
  );
}

export function ConsumeDialog({ dataset, remnant, onClose }: { dataset: Dataset; remnant: Remnant; onClose: () => void }) {
  const { api } = useApi();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState('');
  const [key] = useState(newIdempotencyKey);
  const mutation = useMutation({
    // Reserved pieces are consumed against their reservation; a free piece is withdrawn from stock (C2 contract).
    mutationFn: () =>
      remnant.status === 'reserved' && remnant.active_reservation_id
        ? api.consumeRemnant(remnant.remnant_id, { dataset_id: dataset.dataset_id, expected_version: remnant.version ?? 0, reservation_id: remnant.active_reservation_id, reason: reason.trim() }, key)
        : api.withdrawRemnant(remnant.remnant_id, { dataset_id: dataset.dataset_id, expected_version: remnant.version ?? 0, reason: reason.trim() }, key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['remnants', dataset.dataset_id] });
      onClose();
    },
  });
  return (
    <ConfirmDialog
      open
      onOpenChange={open => !open && onClose()}
      title={remnant.status === 'reserved' ? `Списать использованный ${remnant.remnant_id}` : `Исключить ${remnant.remnant_id} со склада`}
      action={
        remnant.status === 'reserved'
          ? 'Зарезервированный кусок будет списан по его резерву и исчезнет из подбора. История сохраняется; отмена — отдельная корректирующая операция.'
          : 'Свободный кусок будет исключен со склада (withdrawn) и не попадет в подбор. Возврат — отдельная операция восстановления.'
      }
      affected={[
        { label: 'Остаток', value: <span className="mono">{remnant.remnant_id}</span> },
        { label: 'Размер', value: formatDims(remnant.dimensions) },
        { label: 'Место', value: remnant.location_raw },
        { label: 'Ожидаемая версия', value: String(remnant.version ?? 0) },
      ]}
      confirmLabel={remnant.status === 'reserved' ? 'Списать по резерву' : 'Исключить со склада'}
      danger
      onConfirm={() => reason.trim() && mutation.mutate()}
      busy={mutation.isPending}
      error={mutation.error}
    >
      <Field label="Причина списания" required>
        {props => <input {...props} value={reason} onChange={event => setReason(event.target.value)} />}
      </Field>
    </ConfirmDialog>
  );
}
