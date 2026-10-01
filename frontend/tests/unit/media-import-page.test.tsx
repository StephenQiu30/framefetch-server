import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DownloadWorkspace from '@/components/intake/download-workspace';
import { render } from '../helpers/query-render';

const toastInfo = vi.hoisted(() => vi.fn());

vi.mock('sonner', () => ({
  toast: { dismiss: vi.fn(), info: toastInfo },
}));

vi.mock('@/components/providers/use-provider-statuses', () => ({
  useProviderStatuses: () => ({
    data: { items: [] },
    error: null,
    loading: false,
    retry: vi.fn(),
  }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';
import * as mediaImportRuntime from '@/lib/upload/media-import';

const push = vi.fn();

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ user: { id: 'intent-test-owner', role: 'user' } }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

describe('DownloadWorkspace local video upload', () => {
  beforeEach(() => {
    push.mockReset();
    toastInfo.mockReset();
    window.history.replaceState({}, '', '/');
  });

  it('validates the selected MP4 without an extra confirmation step', async () => {
    renderWorkspace();
    expect(
      screen.getByRole('tablist', { name: '选择内容来源' }),
    ).toBeInTheDocument();
    selectUploadTab();
    const fileInput = screen.getByLabelText('选择本地 MP4 视频文件');
    expect(fileInput).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上传视频' })).toBeDisabled();

    fireEvent.change(fileInput, {
      target: {
        files: [new File(['text'], 'notes.txt', { type: 'text/plain' })],
      },
    });

    expect(
      await screen.findByText('当前只支持上传 MP4 视频。'),
    ).toHaveAttribute('id', 'download-workspace-error');
    expect(screen.getByRole('button', { name: /notes\.txt/u })).toHaveAttribute(
      'aria-invalid',
      'true',
    );

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上传视频' })).toBeDisabled();
  });

  it('uploads a local MP4 and opens the shared download detail route', async () => {
    const imported = mediaImportResponse();
    const importRequest = vi
      .spyOn(mediaImportRuntime, 'importLocalVideo')
      .mockImplementation(async (_file, _key, observer) => {
        observer.onPhase('hashing');
        observer.onProgress(100);
        observer.onResource(imported.id);
        observer.onPhase('uploading');
        observer.onProgress(72);
        return imported;
      });
    renderWorkspace();

    selectUploadTab();
    const file = new File(['video'], '我的样片.mp4', { type: 'video/mp4' });
    fireEvent.change(screen.getByLabelText('选择本地 MP4 视频文件'), {
      target: { files: [file] },
    });
    expect(screen.getByRole('button', { name: '上传视频' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '上传视频' }));

    await waitFor(() => expect(importRequest).toHaveBeenCalledOnce());
    expect(importRequest.mock.calls[0][0]).toBe(file);
    expect(importRequest.mock.calls[0][1]).toEqual(expect.any(String));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(
        `/downloads/detail?jobId=${encodeURIComponent(imported.download_id)}`,
      ),
    );
  });

  it('aborts an active multipart upload and confirms server cancellation', async () => {
    const cancelRequest = vi
      .spyOn(mediaImportRuntime, 'cancelLocalVideoImport')
      .mockResolvedValue(undefined);
    const importRequest = vi
      .spyOn(mediaImportRuntime, 'importLocalVideo')
      .mockImplementation(async (_file, _key, observer, signal) => {
        observer.onResource('import-to-cancel');
        observer.onPhase('uploading');
        return await new Promise((_, reject) => {
          signal.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          );
        });
      });
    renderWorkspace();

    selectUploadTab();
    fireEvent.change(screen.getByLabelText('选择本地 MP4 视频文件'), {
      target: {
        files: [new File(['video'], 'sample.mp4', { type: 'video/mp4' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: '上传视频' }));
    fireEvent.click(await screen.findByRole('button', { name: '取消上传' }));

    await waitFor(() =>
      expect(cancelRequest).toHaveBeenCalledWith('import-to-cancel'),
    );
    expect(importRequest).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(toastInfo).toHaveBeenCalledWith(
        '上传已取消，未完成的分片将由服务端清理。',
      ),
    );
  });
});

function renderWorkspace() {
  return render(
    <TooltipProvider>
      <DownloadWorkspace />
    </TooltipProvider>,
  );
}

function selectUploadTab() {
  fireEvent.mouseDown(screen.getByRole('tab', { name: '本地视频' }), {
    button: 0,
    ctrlKey: false,
  });
}

function mediaImportResponse(): API.MediaImportResponse {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    download_id: '11111111-1111-4111-8111-111111111111',
    source_format: 'mp4',
    display_name: '我的样片.mp4',
    declared_size_bytes: 5,
    status: 'verifying',
    attempt: 1,
    error_code: null,
    version: 1,
    created_at: '2026-08-14T00:00:00Z',
    updated_at: '2026-08-14T00:00:01Z',
    finished_at: null,
    declared_origin: 'user_file',
  };
}
