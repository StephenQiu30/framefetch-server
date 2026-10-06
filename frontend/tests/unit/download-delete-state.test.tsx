import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { DownloadDeleteDialog } from '@/components/downloads/download-delete-dialog';
import DownloadHistoryList from '@/components/downloads/download-history-list';
import { render } from '../helpers/query-render';

it('does not show a spinner when no rows are selected or the button is disabled', () => {
  const { container, rerender } = render(
    <DownloadDeleteDialog
      active={false}
      busy={false}
      disabled
      count={0}
      onDelete={vi.fn()}
    />,
  );
  expect(screen.getByRole('button', { name: '批量删除（0）' })).toBeDisabled();
  expect(container.querySelector('[data-slot="spinner"]')).toBeNull();
  rerender(
    <DownloadDeleteDialog
      active={false}
      busy={true}
      count={2}
      onDelete={vi.fn()}
    />,
  );
  expect(screen.getByRole('button', { name: '批量删除（2）' })).toHaveAttribute(
    'aria-busy',
    'true',
  );
  expect(container.querySelector('[data-slot="spinner"]')).not.toBeNull();
  rerender(
    <DownloadDeleteDialog
      active={false}
      busy={false}
      disabled
      count={0}
      onDelete={vi.fn()}
    />,
  );
  expect(container.querySelector('[data-slot="spinner"]')).toBeNull();
});

it('refreshing a populated list disables its actions without claiming to delete every row', async () => {
  const item = {
    id: 'one',
    title: '示例',
    status: 'succeeded',
    file_available: true,
    created_at: '2026-09-25T00:00:00Z',
  } as API.DownloadHistoryItemResponse;
  const props = {
    data: { items: [item] } as API.DownloadHistoryResponse,
    loading: false,
    onDownload: vi.fn(),
    onDelete: vi.fn(),
    onRetry: vi.fn(),
    pendingActions: [],
    selection: { ids: [], busy: true, toggle: vi.fn() },
  };
  const { container, rerender } = render(<DownloadHistoryList {...props} />);
  expect(screen.getByRole('button', { name: '示例 的操作' })).toBeDisabled();
  expect(container.querySelector('[data-slot="spinner"]')).toBeNull();
  rerender(
    <DownloadHistoryList
      {...props}
      selection={{ ...props.selection, busy: false }}
    />,
  );
  fireEvent.pointerDown(screen.getByRole('button', { name: '示例 的操作' }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.click(screen.getByRole('menuitem', { name: '删除下载记录' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '确认删除' })).toBeEnabled(),
  );
  expect(props.onDelete).not.toHaveBeenCalled();
});
