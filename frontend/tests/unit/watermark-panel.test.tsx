import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { createWatermarkTask, listWatermarkTasks } from '@/api/downloads';
import WatermarkPanel from '@/components/downloads/watermark-panel';

vi.mock('@/api/downloads', () => ({
  createWatermarkTask: vi.fn(),
  listWatermarkTasks: vi.fn(),
}));
beforeEach(() => vi.resetAllMocks());
it('shows automatic processing without a manual editor', async () => {
  vi.mocked(listWatermarkTasks).mockResolvedValue({
    available: true,
    items: [
      {
        id: 'task',
        job_id: 'job',
        status: 'running',
        attempt: 1,
        size_bytes: 0,
        created_at: '',
        error_code: null,
      },
    ],
  });
  render(<WatermarkPanel jobId="job" />);
  expect(await screen.findByRole('status')).toHaveTextContent('正在自动去水印');
  expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '框选区域' }),
  ).not.toBeInTheDocument();
});
it('keeps original and processed download links separate', async () => {
  vi.mocked(listWatermarkTasks).mockResolvedValue({
    available: true,
    items: [
      {
        id: 'task',
        job_id: 'job',
        status: 'succeeded',
        attempt: 1,
        size_bytes: 100,
        created_at: '',
        error_code: null,
      },
    ],
  });
  render(<WatermarkPanel jobId="job" />);
  expect(
    await screen.findByRole('link', { name: '保存处理版' }),
  ).toHaveAttribute('href', '/api/watermarks/task/file');
  expect(screen.getByRole('link', { name: '保存原片' })).toHaveAttribute(
    'href',
    '/api/downloads/job/file',
  );
});
it('retries automatically without submitting masks', async () => {
  vi.mocked(listWatermarkTasks).mockResolvedValue({
    available: true,
    items: [
      {
        id: 'task',
        job_id: 'job',
        status: 'failed',
        attempt: 1,
        size_bytes: 0,
        created_at: '',
        error_code: 'processing_failed',
      },
    ],
  });
  render(<WatermarkPanel jobId="job" />);
  fireEvent.click(await screen.findByRole('button', { name: '重试自动处理' }));
  await waitFor(() =>
    expect(createWatermarkTask).toHaveBeenCalledWith(
      { job_id: 'job' },
      { headers: { 'Idempotency-Key': expect.any(String) } },
    ),
  );
});
it('does not offer a futile retry for unsupported video specifications', async () => {
  vi.mocked(listWatermarkTasks).mockResolvedValue({
    available: true,
    items: [
      {
        id: 'task',
        job_id: 'job',
        status: 'failed',
        attempt: 1,
        size_bytes: 0,
        created_at: '',
        error_code: 'unsupported_media',
      },
    ],
  });
  render(<WatermarkPanel jobId="job" />);
  expect(await screen.findByRole('status')).toHaveTextContent(
    '暂不支持此视频规格',
  );
  expect(
    screen.queryByRole('button', { name: '重试自动处理' }),
  ).not.toBeInTheDocument();
});
