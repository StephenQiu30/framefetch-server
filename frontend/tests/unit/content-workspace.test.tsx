import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ContentEditor from '@/components/content/content-editor';
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
        editable={false}
        onSaved={async () => {}}
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

  it('invalidates automatic review after a manual edit', () => {
    render(
      <ContentResultView
        result={{ ...result, review_status: 'needs_review' }}
        analysisId="task-1"
        reportId="report-2"
        editable={false}
        manualRevision
        onSaved={async () => {}}
      />,
    );
    expect(screen.getByText('人工修订版，请核对修改内容')).toBeInTheDocument();
    expect(
      screen.getByText('新版本已保存，原自动审校结论已失效。'),
    ).toBeInTheDocument();
    expect(screen.queryByText('稿件仍有待修改之处')).not.toBeInTheDocument();
  });

  it('preserves the revision base and drops obsolete citations on changed prose', async () => {
    const saved = vi.fn(async () => {});
    render(
      <ContentEditor
        analysisId="task-1"
        reportId="report-1"
        result={result}
        onSaved={saved}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '修改正文' }));
    fireEvent.change(screen.getByLabelText('第 1 段'), {
      target: { value: '这次只观察了短暂倒置。' },
    });
    stubCryptoUuids('22222222-2222-4222-8222-222222222222');
    mockHttpResponses({ status: 'running' });
    fireEvent.click(screen.getByRole('button', { name: '保存新版本' }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    const request = httpRequests()[0];
    expect((request.data as API.ContentRevisionRequest).base_report_id).toBe(
      'report-1',
    );
    expect(
      (request.data as API.ContentRevisionRequest).draft.evidence_index,
    ).toEqual([]);
    expect(
      (request.data as API.ContentRevisionRequest).draft.blocks[0].id,
    ).toBe('opening');
  });
});
