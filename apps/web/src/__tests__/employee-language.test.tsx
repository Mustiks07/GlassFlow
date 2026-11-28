import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ApiError } from '../api/errors';
import { ErrorState } from '../ui/kit';

afterEach(cleanup);

it('shows a human next action and field name while retaining machine details for support', () => {
  render(<ErrorState error={new ApiError('validation', 422, 'VALIDATION_ERROR', 'Ошибка {"field":"length_mm"}', [
    { field: 'body.dimensions.length_mm', name: 'length_mm', message: 'Нужно целое число' },
  ], [], false, 'test-correlation')} />);
  expect(screen.getByText('Длина')).toBeVisible();
  expect(screen.getByRole('listitem')).toHaveTextContent('Длина: Нужно целое число');
  expect(screen.getByText(/Проверьте данные и связь с приложением/)).toBeVisible();
  expect(screen.getByText('VALIDATION_ERROR')).not.toBeVisible();
  expect(screen.getByText('Ошибка {"field":"length_mm"}')).not.toBeVisible();
  fireEvent.click(screen.getByText('Технические подробности'));
  expect(screen.getByText('VALIDATION_ERROR')).toBeVisible();
});
