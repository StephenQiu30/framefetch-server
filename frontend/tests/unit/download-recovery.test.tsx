import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import DownloadHistoryList from '@/components/downloads/download-history-list';
import { DownloadTaskActions } from '@/components/downloads/download-state';
import { job } from '../fixtures/download-fixtures';

describe('source-aware download recovery', () => {
  it('requires a new inspection for context changes in detail and history', () => {
    const value = {
      ...job('failed'),
      error_code: 'context_changed' as const,
      source_label: 'WechatChannelsPublic',
    };
    const props = {
      action: null,
      onCancel: vi.fn(),
      onDownload: vi.fn(),
      onRetry: vi.fn(),
    };
    const view = render(<DownloadTaskActions {...props} job={value} />);
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
    fireEvent.pointerDown(
      screen.getByRole('button', { name: 'Changed media 的操作' }),
      { button: 0, ctrlKey: false },
    );
    expect(
      screen.queryByRole('menuitem', { name: '重新下载' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '重新解析' })).toHaveAttribute(
      'href',
      '/',
    );
    expect(screen.getByText('微信视频号')).toBeVisible();
    expect(screen.queryByText('WechatChannelsPublic')).not.toBeInTheDocument();
  });

  it.each(['failed', 'cancelled', 'succeeded'] as const)(
    'offers reimport instead of remote retry for a local %s resource',
    (status) => {
      const value = {
        ...job(status),
        source_kind: 'browser_import' as const,
        source_label: 'WechatChannelsPublic',
        file_available: false,
      };
      const props = {
        action: null,
        onCancel: vi.fn(),
        onDownload: vi.fn(),
        onRetry: vi.fn(),
      };
      const view = render(<DownloadTaskActions {...props} job={value} />);
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
      fireEvent.pointerDown(
        screen.getByRole('button', { name: 'local.mp4 的操作' }),
        { button: 0, ctrlKey: false },
      );
      expect(
        screen.queryByRole('menuitem', { name: '重新下载' }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('menuitem', { name: '返回首页重新导入' }),
      ).toHaveAttribute('href', '/');
      expect(screen.getByText('WechatChannelsPublic')).toBeVisible();
    },
  );
});
