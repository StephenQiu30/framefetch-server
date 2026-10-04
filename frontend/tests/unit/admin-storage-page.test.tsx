import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AdminStorageView } from '@/components/admin/admin-storage-view';

const runtime = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastWarning: vi.fn(),
  cleanupStoredFiles: vi.fn(),
  deleteStoredFile: vi.fn(),
  listStoredFiles: vi.fn(),
  user: {
    created_at: '2026-08-09T10:00:00Z',
    email: 'owner@example.com',
    id: 'owner-id',
    role: 'admin' as const,
    updated_at: '2026-08-09T10:00:00Z',
    username: 'owner',
  },
}));

vi.mock('sonner', () => ({
  toast: { success: runtime.toastSuccess, warning: runtime.toastWarning },
}));

vi.mock('@/components/auth/auth-provider', async (importOriginal) => ({
  ...(await importOriginal()),
  useAuth: () => ({ loading: false, user: runtime.user }),
}));

describe('administrator storage management', () => {
  beforeEach(() => {
    runtime.cleanupStoredFiles.mockReset();
    runtime.deleteStoredFile.mockReset();
    runtime.listStoredFiles.mockReset();
    runtime.toastSuccess.mockReset();
    runtime.toastWarning.mockReset();
  });

  it('shows each file uploader and keeps files whose account is unavailable', async () => {
    runtime.listStoredFiles.mockResolvedValue({
      items: [
        storedFile({ name: '其他用户的视频', uploader_username: 'alice' }),
        storedFile({
          id: 'file-2',
          name: '归属未知的文件',
          uploader_username: null,
        }),
      ],
      page: 1,
      page_size: 10,
      total: 2,
    });
    render(<AdminStorageView />);

    const file = (await screen.findByText('其他用户的视频')).closest('tr');
    const orphan = screen.getByText('归属未知的文件').closest('tr');
    if (!file || !orphan) throw new Error('File rows missing');
    expect(within(file).getByText('alice')).toBeInTheDocument();
    expect(within(file).getByText('上传人：alice')).toBeInTheDocument();
    expect(within(orphan).getByText('未知上传人')).toBeInTheDocument();
    expect(within(orphan).getByText('上传人：未知上传人')).toBeInTheDocument();
    expect(
      within(file).queryByText(runtime.user.username),
    ).not.toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole('button', { name: '显示列' }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(
      await screen.findByRole('menuitemcheckbox', {
        name: '上传人',
      }),
    );
    expect(
      screen.queryByRole('columnheader', { name: '上传人' }),
    ).not.toBeInTheDocument();
    expect(within(file).getByText('上传人：alice')).toBeInTheDocument();
  });

  it('paginates persistent files and cleans files older than 30 days by default', async () => {
    runtime.listStoredFiles.mockImplementation(async ({ page = 1 }) => ({
      items: [storedFile({ id: `file-${page}`, name: `视频 ${page}` })],
      page,
      page_size: 10,
      total: 11,
    }));
    runtime.cleanupStoredFiles.mockResolvedValue({
      failed_resources: 0,
      freed_bytes: 1_024,
      older_than_days: 30,
      removed_objects: 2,
      removed_resources: 1,
    });
    runtime.deleteStoredFile.mockResolvedValue(undefined);
    render(<AdminStorageView />);

    expect(await screen.findByText('视频 1')).toBeInTheDocument();
    expect(runtime.listStoredFiles).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 10,
    });

    const pagination = screen.getByRole('navigation', { name: '文件列表分页' });
    fireEvent.click(within(pagination).getByRole('button', { name: '下一页' }));
    await waitFor(() =>
      expect(runtime.listStoredFiles).toHaveBeenLastCalledWith({
        page: 2,
        page_size: 10,
      }),
    );
    expect(await screen.findByText('视频 2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '清理历史文件' }));
    const dialog = await screen.findByRole('alertdialog', {
      name: '清理历史文件？',
    });
    expect(within(dialog).getByLabelText('清理多少天前的文件')).toHaveValue(30);
    fireEvent.click(within(dialog).getByRole('button', { name: '确认清理' }));

    await waitFor(() =>
      expect(runtime.cleanupStoredFiles).toHaveBeenCalledWith({
        older_than_days: 30,
      }),
    );
    await waitFor(() =>
      expect(runtime.toastSuccess).toHaveBeenCalledWith(
        '已清理 1 项资源、2 个对象；0 项清理失败。',
      ),
    );
    await waitFor(() =>
      expect(runtime.listStoredFiles).toHaveBeenLastCalledWith({
        page: 1,
        page_size: 10,
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: '删除文件 视频 1' }));
    const deleteDialog = await screen.findByRole('alertdialog', {
      name: '删除文件？',
    });
    expect(deleteDialog).toHaveTextContent(
      '“视频 1”及其所有持久对象将被永久删除。',
    );
    fireEvent.click(
      within(deleteDialog).getByRole('button', { name: '确认删除' }),
    );

    await waitFor(() =>
      expect(runtime.deleteStoredFile).toHaveBeenCalledWith({
        category: 'video',
        file_id: 'file-1',
      }),
    );
    await waitFor(() =>
      expect(runtime.toastSuccess).toHaveBeenCalledWith('已删除文件“视频 1”。'),
    );
  });

  it('keeps the current table mounted when a refresh fails', async () => {
    runtime.listStoredFiles
      .mockResolvedValueOnce({
        items: [storedFile()],
        page: 1,
        page_size: 10,
        total: 11,
      })
      .mockRejectedValueOnce(new Error('文件服务暂不可用'));
    render(<AdminStorageView />);

    expect(await screen.findByText('视频 1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));

    await waitFor(() =>
      expect(runtime.listStoredFiles).toHaveBeenCalledTimes(2),
    );
    expect(screen.getByText('视频 1')).toBeInTheDocument();
    expect(screen.getByText('文件列表刷新失败')).toBeInTheDocument();
    expect(screen.getByText('文件服务暂不可用')).toBeInTheDocument();
  });

  it('shows a warning when cleanup only partially succeeds', async () => {
    runtime.listStoredFiles.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 10,
      total: 0,
    });
    runtime.cleanupStoredFiles.mockResolvedValue({
      failed_resources: 1,
      freed_bytes: 0,
      older_than_days: 30,
      removed_objects: 2,
      removed_resources: 1,
    });
    render(<AdminStorageView />);

    fireEvent.click(screen.getByRole('button', { name: '清理历史文件' }));
    const dialog = await screen.findByRole('alertdialog', {
      name: '清理历史文件？',
    });
    fireEvent.click(within(dialog).getByRole('button', { name: '确认清理' }));

    await waitFor(() =>
      expect(runtime.toastWarning).toHaveBeenCalledWith(
        '已清理 1 项资源、2 个对象；1 项清理失败。',
      ),
    );
    expect(runtime.toastSuccess).not.toHaveBeenCalled();
  });
});

function storedFile(
  overrides: Partial<API.StoredFileResponse> = {},
): API.StoredFileResponse {
  return {
    category: 'video',
    created_at: '2026-07-01T10:00:00Z',
    id: 'file-1',
    name: '视频 1',
    uploader_username: 'uploader',
    object_count: 1,
    size_bytes: 1_024,
    ...overrides,
  };
}

vi.mock('@/api/admin', async (original) => ({
  ...(await original<typeof import('@/api/admin')>()),
  cleanupStoredFiles: runtime.cleanupStoredFiles,
  deleteStoredFile: runtime.deleteStoredFile,
  listStoredFiles: runtime.listStoredFiles,
}));
vi.mock('@/lib/request-error', async (original) => ({
  ...(await original<typeof import('@/lib/request-error')>()),
  displayError: (reason: unknown) =>
    reason instanceof Error ? reason.message : '请求失败',
}));
