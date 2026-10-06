import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import DownloadState, {
  DownloadTaskActions,
} from '@/components/downloads/download-state';
import { job } from '../fixtures/download-fixtures';

describe('server artifact readiness is not device delivery', () => {
  it.each(['video', 'image_gallery', 'video_collection'] as const)(
    'does not claim a %s was saved when the browser download has no completion signal',
    (media_kind) => {
      const onDownload = vi.fn();
      render(
        <>
          <DownloadState job={{ ...job('succeeded'), media_kind }} />
          <DownloadTaskActions
            action={null}
            job={{ ...job('succeeded'), media_kind }}
            onDownload={onDownload}
            onRetry={vi.fn()}
          />
        </>,
      );

      expect(
        screen.getByRole('table', { name: '任务时间记录' }),
      ).toHaveTextContent('服务端已完成');
      expect(screen.getByText(/文件已在服务器完成校验/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /获取/ }));
      expect(onDownload).toHaveBeenCalledOnce();
      expect(
        screen.queryByText(/已保存到设备|下载已完成/),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(/保存结果请查看浏览器下载记录/),
      ).toBeInTheDocument();
    },
  );
});
