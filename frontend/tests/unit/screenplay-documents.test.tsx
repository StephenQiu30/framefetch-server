import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MissingScreenplayDocument } from '@/components/screenplay/missing-screenplay-document';
import ScreenplayDocumentDetailView from '@/components/screenplay/screenplay-document-detail-view';
import ScreenplayDocumentsView from '@/components/screenplay/screenplay-documents-view';
import {
  screenplayDocument,
  screenplayDocumentPage,
  screenplayDocumentSummary,
} from '../fixtures/document-fixtures';
import { render } from '../helpers/query-render';

const runtime = vi.hoisted(() => ({
  deleteScreenplayDocument: vi.fn(),
  getScreenplayDocument: vi.fn(),
  listScreenplayDocuments: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: runtime.push, replace: runtime.replace }),
}));

vi.mock('@/components/screenplay/screenplay-analysis-panel', () => ({
  default: ({ documentId }: { documentId: string }) => (
    <div data-testid="screenplay-analysis-workspace">{documentId}</div>
  ),
}));

describe('screenplay documents', () => {
  beforeEach(() => {
    runtime.deleteScreenplayDocument.mockReset();
    runtime.getScreenplayDocument.mockReset();
    runtime.listScreenplayDocuments.mockReset();
    runtime.push.mockReset();
    runtime.replace.mockReset();
  });

  it('renders metadata rows, paging and a stable refresh action', async () => {
    runtime.listScreenplayDocuments.mockImplementation(
      async ({ page = 1 }: { page?: number }) =>
        screenplayDocumentPage({
          items: [screenplayDocumentSummary()],
          page,
          total: 11,
        }),
    );
    render(<ScreenplayDocumentsView />);

    expect(screen.getByRole('status')).toHaveTextContent('正在加载剧本文档');
    expect(await screen.findByText('午夜来客')).toBeInTheDocument();
    expect(screen.getByText('Fountain')).toBeInTheDocument();
    expect(screen.getAllByText(/2 个场景/)).toHaveLength(2);
    expect(screen.getByText('中英混合')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '午夜来客' })).toHaveAttribute(
      'href',
      '/documents/detail?documentId=99999999-9999-4999-8999-999999999999',
    );
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() =>
      expect(runtime.listScreenplayDocuments).toHaveBeenLastCalledWith(
        {
          page: 2,
          page_size: 10,
        },
        { signal: expect.any(AbortSignal) },
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '刷新' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() =>
      expect(runtime.listScreenplayDocuments).toHaveBeenCalledTimes(3),
    );
  });

  it('keeps document format, content statistics, language and update time in the compact primary cell', async () => {
    runtime.listScreenplayDocuments.mockResolvedValue(screenplayDocumentPage());
    render(<ScreenplayDocumentsView />);

    const title = await screen.findByRole('link', { name: '午夜来客' });
    const primaryCell = title.closest('td');
    expect(primaryCell).not.toBeNull();
    const cell = within(primaryCell as HTMLTableCellElement);
    const compactFormat = cell.getByText('Fountain · 中英混合');
    const compactMetadata = compactFormat.parentElement;

    expect(compactMetadata).toHaveClass('lg:hidden');
    expect(cell.getByText('2 个场景 · 1,280 个字符')).toBeInTheDocument();
    expect(cell.getByText(/^更新于/u)).toHaveAttribute(
      'datetime',
      '2026-08-14T10:02:00Z',
    );
    expect(cell.getByText('midnight-visitor.fountain')).toBeInTheDocument();
    expect(cell.getByText('可以核对')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '删除剧本文档' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: '选择 午夜来客' }),
    ).toBeInTheDocument();
  });

  it('keeps the empty and request-failure states actionable', async () => {
    runtime.listScreenplayDocuments.mockResolvedValueOnce(
      screenplayDocumentPage({ items: [], total: 0 }),
    );
    const { unmount } = render(<ScreenplayDocumentsView />);
    expect(await screen.findByText('还没有剧本文档')).toBeInTheDocument();
    unmount();

    runtime.listScreenplayDocuments.mockRejectedValueOnce(
      new Error('文档服务暂时不可用'),
    );
    render(<ScreenplayDocumentsView />);
    expect(await screen.findByText('文档服务暂时不可用')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument();
  });

  it('exposes screenplay upload as the primary empty-state entry', async () => {
    runtime.listScreenplayDocuments.mockResolvedValueOnce(
      screenplayDocumentPage({ items: [], total: 0 }),
    );
    render(<ScreenplayDocumentsView />);

    await screen.findByText('还没有剧本文档');
    fireEvent.click(screen.getByRole('button', { name: '上传剧本' }));
    expect(
      screen.getByRole('heading', { name: '上传剧本文档' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上传剧本' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: '选择剧本文档' }),
    ).toHaveAccessibleDescription(
      '支持 DOCX、PDF、TXT、Markdown 和 Fountain 格式。选择文件后，点击“上传剧本”开始导入。',
    );
  });

  it('deletes an owned screenplay from the document list', async () => {
    runtime.listScreenplayDocuments.mockResolvedValue(screenplayDocumentPage());
    runtime.deleteScreenplayDocument.mockResolvedValue(undefined);
    render(<ScreenplayDocumentsView />);

    fireEvent.click(
      await screen.findByRole('button', { name: '删除剧本文档' }),
    );
    fireEvent.click(await screen.findByRole('button', { name: '确认删除' }));

    await waitFor(() =>
      expect(runtime.deleteScreenplayDocument).toHaveBeenCalledWith({
        document_id: '99999999-9999-4999-8999-999999999999',
      }),
    );
    await waitFor(() =>
      expect(runtime.listScreenplayDocuments).toHaveBeenCalledTimes(2),
    );
  });

  it('deletes a screenplay from detail and returns to the document list', async () => {
    runtime.getScreenplayDocument.mockResolvedValue(
      screenplayDocument({ id: 'document-id' }),
    );
    runtime.deleteScreenplayDocument.mockResolvedValue(undefined);
    render(<ScreenplayDocumentDetailView documentId="document-id" />);

    fireEvent.click(await screen.findByRole('button', { name: '删除文档' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认删除' }));

    await waitFor(() =>
      expect(runtime.deleteScreenplayDocument).toHaveBeenCalledWith({
        document_id: 'document-id',
      }),
    );
    expect(runtime.replace).toHaveBeenCalledWith('/documents');
  });

  it('renders screenplay Markdown safely with a table of contents', async () => {
    runtime.getScreenplayDocument.mockResolvedValue(
      screenplayDocument({
        id: 'document-id',
        preview:
          '# 午夜来客\n\n## INT. LOBBY - NIGHT\n\n<script>只作为台词文本</script>\n\nA visitor waits in the lobby.',
      }),
    );
    const { container } = render(
      <ScreenplayDocumentDetailView documentId="document-id" />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('正在读取剧本文档');
    expect(
      await screen.findByRole('heading', { level: 1, name: '午夜来客' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 2, name: '午夜来客' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 3, name: 'INT. LOBBY - NIGHT' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('article', { name: '规范化剧本 Markdown 预览' }),
    ).toHaveTextContent('<script>只作为台词文本</script>');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('pre')).toBeNull();
    const tableOfContents = screen.getByRole('navigation', { name: '目录' });
    expect(tableOfContents).toHaveAttribute('data-slot', 'navigation-menu');
    expect(screen.getByRole('link', { name: '午夜来客' })).toHaveAttribute(
      'href',
      '#screenplay-heading-0',
    );
    expect(
      screen.getByRole('link', { name: 'INT. LOBBY - NIGHT' }),
    ).toHaveAttribute('href', '#screenplay-heading-1');
    expect(
      screen.getByRole('heading', { name: '文档信息' }),
    ).toBeInTheDocument();
    const truncationTitle = screen.getByText('预览已截断');
    expect(truncationTitle.parentElement).toHaveTextContent(
      '当前内容仍受接口读取上限约束',
    );
    const warningTitle = screen.getByText('需要人工核对');
    expect(warningTitle.parentElement).toHaveTextContent(
      '未识别到明确场景标题',
    );
    expect(screen.getByText('中英混合')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '基础解析' }),
    ).toBeInTheDocument();
    expect(screen.getByText('24 段')).toBeInTheDocument();
    expect(screen.getByText('8 个')).toBeInTheDocument();
    const workspace = screen.getByTestId('screenplay-document-workspace');
    const analysis = screen.getByTestId('screenplay-analysis-workspace');
    expect(analysis).toHaveTextContent('document-id');
    expect(workspace.nextElementSibling).toBe(analysis);
    expect(screen.getByRole('link', { name: '返回上一步' })).toHaveAttribute(
      'href',
      '/documents',
    );
  });

  it('explains active, failed and missing document states', async () => {
    runtime.getScreenplayDocument.mockResolvedValueOnce(
      screenplayDocument({
        id: 'verifying-id',
        preview: null,
        preview_truncated: false,
        status: 'verifying',
      }),
    );
    const { unmount } = render(
      <ScreenplayDocumentDetailView
        documentId="verifying-id"
        pollIntervalMs={60_000}
      />,
    );
    expect(
      await screen.findByText('正在解析剧本文本，请稍后刷新。'),
    ).toBeInTheDocument();
    unmount();

    runtime.getScreenplayDocument.mockResolvedValueOnce(
      screenplayDocument({
        error_code: 'document_text_unavailable',
        id: 'failed-id',
        preview: null,
        preview_truncated: false,
        status: 'failed',
      }),
    );
    const failedView = render(
      <ScreenplayDocumentDetailView documentId="failed-id" />,
    );
    expect(
      await screen.findByText('没有提取到可用的剧本文本。'),
    ).toBeInTheDocument();
    failedView.unmount();

    runtime.getScreenplayDocument.mockResolvedValueOnce(
      screenplayDocument({
        error_code: 'upload_session_expired',
        id: 'expired-upload-id',
        preview: null,
        preview_truncated: false,
        status: 'uploading',
      }),
    );
    const expiredUpload = render(
      <ScreenplayDocumentDetailView documentId="expired-upload-id" />,
    );
    expect(await screen.findByText('上传会话已过期。')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '重新上传' }),
    ).toBeInTheDocument();
    expiredUpload.unmount();

    runtime.getScreenplayDocument.mockRejectedValueOnce(
      new Error('文档服务暂时不可用'),
    );
    const requestFailure = render(
      <ScreenplayDocumentDetailView documentId="unavailable-id" />,
    );
    expect(
      await screen.findByRole('heading', { name: '剧本文档暂时不可用' }),
    ).toBeInTheDocument();
    expect(screen.getByText('文档服务暂时不可用')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '重新加载' }),
    ).toBeInTheDocument();
    requestFailure.unmount();

    render(<MissingScreenplayDocument />);
    expect(
      screen.getByRole('heading', { name: '剧本文档不存在' }),
    ).toBeInTheDocument();
  });
});

vi.mock('@/lib/request-error', async (original) => ({
  ...(await original<typeof import('@/lib/request-error')>()),
  displayError: (reason: unknown) =>
    reason instanceof Error ? reason.message : '请求失败',
}));
vi.mock('@/api/documents', async (original) => ({
  ...(await original<typeof import('@/api/documents')>()),
  getDocumentImport: runtime.getScreenplayDocument,
  deleteDocument: runtime.deleteScreenplayDocument,
  listDocuments: runtime.listScreenplayDocuments,
}));
