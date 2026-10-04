import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ContentResultView from '@/components/content/content-result-view';
import ContentWorkspace from '@/components/content/content-workspace';
import { httpClient } from '@/lib/request';
import { stubCryptoUuids } from '../helpers/crypto';
import { httpRequests, mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const result: API.ContentDocumentResult = {
  kind: 'content_document',
  document_type: 'article',
  language: 'zh-CN',
  title: '旋紧杯盖之后',
  blocks: [
    { id: 'opening', type: 'paragraph', text: '短暂倒置期间，桌面未见水滴。' },
  ],
  evidence_index: [
    {
      block_id: 'opening',
      material_id: 'notes',
      segment_id: 'segment-000',
      quote: '未见水滴',
    },
  ],
  source_set_ref: 'a'.repeat(64),
  review_status: 'needs_material',
  review_history: [
    {
      needs_material: true,
      findings: [
        {
          block_id: 'opening',
          severity: 'major',
          category: 'missing_material',
          problem: '缺少携带记录',
          correction: '补充实际携带测试',
        },
      ],
    },
  ],
};

describe('content workspace and reader output', () => {
  beforeEach(() => {
    vi.mocked(httpClient.request).mockReset();
  });
  it('requires purpose and factual materials before submitting a content task', async () => {
    mockHttpResponses({ items: [], next_cursor: null });
    render(<ContentWorkspace />);
    expect(screen.getByRole('button', { name: '开始创作' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('希望读者了解什么'), {
      target: { value: '介绍这次观察' },
    });
    fireEvent.change(screen.getByLabelText('材料名称'), {
      target: { value: '试用笔记' },
    });
    fireEvent.change(screen.getByLabelText('材料内容'), {
      target: { value: '短暂倒置未见水滴' },
    });
    expect(screen.getByRole('button', { name: '开始创作' })).toBeEnabled();
    stubCryptoUuids('11111111-1111-4111-8111-111111111111');
    mockHttpResponses({ id: 'task-1' });
    fireEvent.click(screen.getByRole('button', { name: '开始创作' }));
    await waitFor(() =>
      expect(
        httpRequests().some(
          (request) => request.url === '/api/content/analyses',
        ),
      ).toBe(true),
    );
    const call = httpRequests().find(
      (request) => request.url === '/api/content/analyses',
    );
    if (!call) throw new Error('Content request missing');
    expect((call.data as API.ContentAnalysisRequest).source.brief.purpose).toBe(
      '介绍这次观察',
    );
    expect(
      (call.data as API.ContentAnalysisRequest).source.materials[0].text,
    ).toBe('短暂倒置未见水滴');
    expect(call?.headers?.['Idempotency-Key']).toBeTruthy();
    const history = httpRequests().find(
      (request) => request.url === '/api/download-intents/history/records',
    );
    expect(history?.params).toEqual({
      record_type: ['content_creation'],
      limit: 10,
    });
    expect(history?.paramsSerializer).toEqual({ indexes: null });
  });

  it('keeps evidence and editorial findings outside reader prose', () => {
    render(
      <ContentResultView
        result={result}
        analysisId="task-1"
        reportId="report-1"
      />,
    );
    const reader = screen.getByRole('region', { name: '正文' });
    expect(
      within(reader).getByText('短暂倒置期间，桌面未见水滴。'),
    ).toBeInTheDocument();
    expect(
      within(reader).queryByText('补充实际携带测试'),
    ).not.toBeInTheDocument();
    expect(reader.textContent).not.toContain('segment-000');
    expect(reader.textContent).not.toContain('编辑附录');
    expect(screen.getByText('请补充材料后再采用')).toBeInTheDocument();
  });

  it('keeps historical drafts read-only without an editing action', () => {
    render(
      <ContentResultView
        result={{ ...result, review_status: 'needs_review' }}
        analysisId="task-1"
        reportId="report-2"
        historicalEdit
      />,
    );
    expect(screen.getByText('历史保存稿')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '修改正文' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: '正文' })).toHaveTextContent(
      '短暂倒置期间，桌面未见水滴。',
    );
  });

  it('does not add a review warning or empty editorial section to a passing result', () => {
    render(
      <ContentResultView
        result={{
          ...result,
          review_status: 'passed',
          review_history: [{ findings: [], needs_material: false }],
        }}
        analysisId="task-1"
        reportId="report-1"
      />,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/审校意见/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '修改正文' }),
    ).not.toBeInTheDocument();
  });

  it('reads historical report prose without enabling writes', async () => {
    mockHttpResponses([
      {
        id: 'report-1',
        run_no: 1,
        created_at: '2026-10-04T00:00:00Z',
        markdown: '## 原始报告\n\n原稿正文',
      },
      {
        id: 'report-2',
        run_no: 2,
        created_at: '2026-10-04T00:01:00Z',
        markdown: '## 历史保存稿\n\n历史稿正文',
      },
    ]);
    render(
      <ContentResultView
        result={result}
        analysisId="task-1"
        reportId="report-2"
        historicalEdit
      />,
    );
    const history = screen.getByText('报告历史').closest('details');
    if (!history) throw new Error('Report history missing');
    await act(async () => {
      history.open = true;
      fireEvent(history, new Event('toggle'));
    });
    expect(await screen.findByText('原稿正文')).toBeInTheDocument();
    expect(screen.getByText('历史稿正文')).toBeInTheDocument();
    expect(httpRequests()).toHaveLength(1);
    expect(httpRequests()[0]).toMatchObject({
      method: 'GET',
      url: '/api/content/analyses/task-1/versions',
    });
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
});
