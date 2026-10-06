import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ContentReportHistory from '@/components/content/content-report-history';
import ContentResultView from '@/components/content/content-result-view';
import ContentSourceReview from '@/components/content/content-source-review';
import { render } from '../helpers/query-render';

const { getContentSource, listContentVersions } = vi.hoisted(() => ({
  getContentSource: vi.fn(),
  listContentVersions: vi.fn(),
}));
vi.mock('@/api/analyses', () => ({ getContentSource, listContentVersions }));

const source: API.ContentSourceSet = {
  brief: { document_type: 'article', purpose: '整理已有材料' },
  materials: [
    { id: 'source-1', title: '访谈记录', text: '第一份材料的完整正文' },
    {
      id: 'source-2',
      title: '已有文章',
      text: '第二份材料的完整正文',
      role: 'author_style',
    },
  ],
};
const result: API.ContentDocumentResult = {
  document_type: 'article',
  language: 'zh-CN',
  title: '历史稿件',
  blocks: [],
  evidence_index: [],
  kind: 'content_document',
  source_set_ref: 'source-set',
  review_status: 'passed',
  review_history: [],
};
const versions: API.ContentVersion[] = [1, 2].map((run) => ({
  id: `report-${run}`,
  run_no: run,
  created_at: `2026-10-07T0${run}:00:00Z`,
  result,
  markdown: `# 第${run}次保存的完整稿件\n\n第${run}份报告的正文。`,
  content_sha256: 'a'.repeat(64),
}));

describe('read-only content report panels', () => {
  beforeEach(() => {
    getContentSource.mockReset().mockResolvedValue(source);
    listContentVersions.mockReset().mockResolvedValue(versions);
  });

  it('loads source material on expansion and preserves independent selections when reopened', async () => {
    render(<ContentSourceReview analysisId="analysis-source" citations={[]} />);
    const panel = screen.getByRole('button', { name: '来源回查' });
    expect(panel).toHaveAttribute('aria-expanded', 'false');
    expect(getContentSource).not.toHaveBeenCalled();

    fireEvent.click(panel);
    const first = await screen.findByRole('button', { name: '访谈记录' });
    const second = screen.getByRole('button', { name: '已有文章 · 作者范文' });
    expect(getContentSource).toHaveBeenCalledTimes(1);
    expect(getContentSource).toHaveBeenCalledWith(
      { analysis_id: 'analysis-source' },
      { signal: expect.any(AbortSignal) },
    );
    expect(
      screen.queryByText(source.materials[0].text),
    ).not.toBeInTheDocument();
    fireEvent.click(first);
    fireEvent.click(second);
    expect(first).toHaveAttribute('aria-expanded', 'true');
    expect(second).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(source.materials[0].text)).toBeVisible();
    expect(screen.getByText(source.materials[1].text)).toBeVisible();

    fireEvent.click(panel);
    fireEvent.click(panel);
    expect(screen.getByRole('button', { name: '访谈记录' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByText(source.materials[1].text)).toBeVisible();
    expect(getContentSource).toHaveBeenCalledTimes(1);
  });

  it('recovers a failed source request without losing its citation', async () => {
    getContentSource.mockRejectedValueOnce(new Error('材料请求失败'));
    render(
      <ContentSourceReview
        analysisId="analysis-retry"
        citations={[
          {
            block_id: 'paragraph-1',
            material_id: 'source-1',
            segment_id: 'segment-1',
            quote: '原始引用内容',
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '来源回查' }));
    expect(await screen.findByText('材料读取失败')).toBeVisible();
    expect(screen.getByRole('listitem')).toHaveTextContent('原始引用内容');
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(screen.queryByText('材料读取失败')).toBeNull());
    expect(screen.getByRole('listitem')).toHaveTextContent(
      '访谈记录 · segment-1',
    );
    expect(getContentSource).toHaveBeenCalledTimes(2);
  });

  it('loads history on expansion and keeps multiple complete reports open across reopening', async () => {
    render(
      <ContentReportHistory
        analysisId="analysis-history"
        currentReportId="report-2"
      />,
    );
    const panel = screen.getByRole('button', { name: '报告历史' });
    expect(listContentVersions).not.toHaveBeenCalled();
    fireEvent.click(panel);
    const first = await screen.findByRole('button', { name: /第 1 份报告/ });
    const second = screen.getByRole('button', {
      name: /第 2 份报告 · 当前报告/,
    });
    expect(listContentVersions).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('第1份报告的正文。')).not.toBeInTheDocument();
    fireEvent.click(first);
    fireEvent.click(second);
    expect(await screen.findByText('第1份报告的正文。')).toBeVisible();
    expect(await screen.findByText('第2份报告的正文。')).toBeVisible();
    expect(first).toHaveAttribute('aria-expanded', 'true');
    expect(second).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(panel);
    fireEvent.click(panel);
    expect(await screen.findByText('第1份报告的正文。')).toBeVisible();
    expect(await screen.findByText('第2份报告的正文。')).toBeVisible();
    expect(listContentVersions).toHaveBeenCalledTimes(1);
  });

  it('keeps historical review labels and exposes findings only after expansion', () => {
    render(
      <ContentResultView
        analysisId="historical-edit"
        reportId="report-2"
        historicalEdit
        result={{
          ...result,
          review_history: [
            {
              needs_material: false,
              findings: [
                {
                  block_id: 'paragraph-1',
                  severity: 'major',
                  category: 'expression',
                  problem: '重复解释材料',
                  correction: '保留具体事实',
                },
              ],
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('历史保存稿')).toBeVisible();
    const review = screen.getByRole('button', { name: '历史审校记录（1）' });
    expect(review).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('保留具体事实')).not.toBeInTheDocument();
    fireEvent.click(review);
    expect(review).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('listitem')).toHaveTextContent('重复解释材料');
    expect(screen.getByRole('listitem')).toHaveTextContent('保留具体事实');
    expect(getContentSource).not.toHaveBeenCalled();
    expect(listContentVersions).not.toHaveBeenCalled();
  });
});
