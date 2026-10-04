import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DownloadHistoryView from '@/components/downloads/download-history-view';
import { QueryProvider } from '@/components/layout/query-provider';
import { advanceSessionGeneration } from '@/lib/session-events';

const runtime = vi.hoisted(() => ({ history: vi.fn(), skills: vi.fn() }));
vi.mock('@/api/downloads', () => ({ getDownloadHistory: runtime.history }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

function Routes() {
  const [visible, setVisible] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setVisible(!visible)}>
        Navigate
      </button>
      {visible && <DownloadHistoryView />}
    </>
  );
}

describe('private workspace view state', () => {
  beforeEach(() => {
    runtime.history.mockReset().mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
      total: 60,
      summary: { total: 60, active: 0, succeeded: 60, failed: 0 },
    });
  });

  it('restores pagination, applied filters and unsubmitted search text separately', async () => {
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    const search = screen.getByRole('textbox', { name: '搜索下载记录' });
    fireEvent.change(search, { target: { value: '已应用' } });
    fireEvent.keyDown(search, { key: 'Enter' });
    fireEvent.click(screen.getByRole('combobox', { name: '按状态筛选' }));
    fireEvent.click(await screen.findByRole('option', { name: '已完成' }));
    fireEvent.click(await screen.findByRole('button', { name: '下一页' }));
    await screen.findByText('2 / 3');
    fireEvent.change(search, { target: { value: '尚未搜索' } });
    fireEvent.click(screen.getByText('Navigate'));
    fireEvent.click(screen.getByText('Navigate'));
    expect(screen.getByRole('textbox', { name: '搜索下载记录' })).toHaveValue(
      '尚未搜索',
    );
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    expect(
      screen.getByRole('combobox', { name: '按状态筛选' }),
    ).toHaveTextContent('已完成');
    expect(runtime.history).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 2,
        search: '已应用',
        status: 'succeeded',
      }),
      expect.anything(),
    );
  });

  it('clears private filters when the identity changes', async () => {
    render(
      <QueryProvider>
        <Routes />
      </QueryProvider>,
    );
    fireEvent.change(screen.getByRole('textbox', { name: '搜索下载记录' }), {
      target: { value: 'private search' },
    });
    act(() => advanceSessionGeneration());
    expect(screen.getByRole('textbox', { name: '搜索下载记录' })).toHaveValue(
      '',
    );
  });
});
