import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import DownloadHistoryList from '@/components/downloads/download-history-list';
import DownloadState from '@/components/downloads/download-state';
import { job } from '../fixtures/download-fixtures';

describe('source-aware download recovery', () => {
  it('requires a new inspection for context changes in detail and history', () => {
    const value = {
      ...job('failed'),
      error_code: 'context_changed' as const,
    };
    const props = {
      action: null,
      onCancel: vi.fn(),
      onDownload: vi.fn(),
      onRetry: vi.fn(),
    };
    const view = render(<DownloadState {...props} job={value} />);
    expect(
      screen.queryByRole('button', { name: /重新下载|重试/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '重新解析' })).toHaveAttribute(
      'href',
      '/',
    );
    view.unmount();
    render(
      <DownloadHistoryList
        data={{
          items: [{ ...value, title: 'Changed media', format_name: 'MP4' }],
          page: 1,
          page_size: 20,
          total: 1,
          summary: { total: 1, active: 0, failed: 1, succeeded: 0 },
        }}
        loading={false}
        pendingActions={[]}
        onDownload={vi.fn()}
        onRetry={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole('button', { name: '重新下载' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '重新解析' })).toHaveAttribute(
      'href',
      '/',
    );
  });

  it.each(['failed', 'cancelled', 'succeeded'] as const)(
    'offers reimport instead of remote retry for a local %s resource',
    (status) => {
      const value = {
        ...job(status),
        source_kind: 'browser_import' as const,
        file_available: false,
      };
      const props = {
        action: null,
        onCancel: vi.fn(),
        onDownload: vi.fn(),
        onRetry: vi.fn(),
      };
      const view = render(<DownloadState {...props} job={value} />);
      expect(
        screen.queryByRole('button', { name: /重新下载|重试/ }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: '返回首页重新导入' }),
      ).toHaveAttribute('href', '/');
      view.unmount();
      render(
        <DownloadHistoryList
          data={{
            items: [{ ...value, title: 'local.mp4', format_name: 'MP4' }],
            page: 1,
            page_size: 20,
            total: 1,
            summary: { total: 1, active: 0, failed: 0, succeeded: 0 },
          }}
          loading={false}
          pendingActions={[]}
          onDownload={vi.fn()}
          onRetry={vi.fn()}
          onDelete={vi.fn()}
        />,
      );
      expect(
        screen.queryByRole('button', { name: '重新下载' }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: '返回首页重新导入' }),
      ).toHaveAttribute('href', '/');
    },
  );
});
