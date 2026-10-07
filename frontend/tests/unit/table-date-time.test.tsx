import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { TableDateTime } from '@/components/layout/table-date-time';

it('preserves the timestamp while displaying a readable date and clock', () => {
  const value = '2026-10-07T12:34:56';
  const { container } = render(<TableDateTime value={value} />);

  expect(container.querySelector('time')).toHaveAttribute('datetime', value);
  expect(screen.getByText('2026年10月7日')).toBeInTheDocument();
  expect(screen.getByText('12:34')).toBeInTheDocument();
});

it('retains seconds for operation and execution records', () => {
  render(<TableDateTime value="2026-10-07T12:34:56" seconds />);

  expect(screen.getByText('12:34:56')).toBeInTheDocument();
});
