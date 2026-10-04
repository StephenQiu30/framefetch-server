import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import AnalysisVideoResult from '@/components/analysis/analysis-video-result';
import { articleResult } from '../fixtures/analysis-fixtures';

describe('article delivery', () => {
  it('shows complete article copy without review metadata or a historical appendix', () => {
    render(
      <AnalysisVideoResult
        result={articleResult}
        reportMarkdown="# 历史稿件\n\n## 编辑附录：视频证据\n旧的编辑备注"
      />,
    );

    const article = within(screen.getByRole('article', { name: '文章正文' }));
    expect(
      article.getByRole('heading', { name: articleResult.title }),
    ).toBeTruthy();
    expect(article.getByText(articleResult.lead)).toBeTruthy();
    expect(article.getByText(articleResult.sections[0].body)).toBeTruthy();
    expect(article.getByText(articleResult.closing)).toBeTruthy();
    for (const metadata of [
      articleResult.sections[0].evidence[0].note,
      ...articleResult.key_points,
      ...articleResult.limitations,
      '旧的编辑备注',
      '章节 1',
    ]) {
      expect(screen.queryByText(metadata)).toBeNull();
    }
    expect(screen.queryByRole('button', { name: /查看视频依据/ })).toBeNull();
    expect(screen.queryByRole('tab', { name: '报告预览' })).toBeNull();
  });

  it('renders paragraph-only articles without empty headings or editorial metadata', () => {
    const result = {
      ...articleResult,
      lead: '',
      closing: '',
      key_points: [],
      sections: articleResult.sections.map((section) => ({
        ...section,
        title: '',
      })),
      review_status: 'needs_review' as const,
      review_history: [
        {
          needs_material: false,
          findings: [
            {
              block_id: 'section-000',
              severity: 'major' as const,
              category: 'expression' as const,
              problem: '开头重复解释材料',
              correction: '直接写具体对象',
            },
          ],
        },
      ],
    };
    render(<AnalysisVideoResult result={result} />);
    const article = within(screen.getByRole('article', { name: '文章正文' }));
    expect(article.getAllByRole('heading')).toHaveLength(1);
    expect(article.queryByText('开头重复解释材料')).toBeNull();
    expect(screen.getByText('审校仍有问题')).toBeTruthy();
    fireEvent.click(screen.getByText('审校意见（1）'));
    expect(screen.getByText('直接写具体对象')).toBeTruthy();
  });

  it('keeps evidence and review notes available in their own tab with playback', () => {
    const onSelectTime = vi.fn();
    render(
      <AnalysisVideoResult
        result={articleResult}
        onSelectTime={onSelectTime}
      />,
    );
    fireEvent.mouseDown(screen.getByRole('tab', { name: '回查依据' }), {
      button: 0,
      ctrlKey: false,
    });

    expect(screen.queryByRole('article')).toBeNull();
    expect(
      screen.getByText(articleResult.sections[0].evidence[0].note),
    ).toBeTruthy();
    expect(screen.getByText(articleResult.key_points[0])).toBeTruthy();
    expect(screen.getByText(articleResult.limitations[0])).toBeTruthy();
    fireEvent.click(
      screen.getByRole('button', { name: '查看视频依据 0:30–1:02' }),
    );
    expect(onSelectTime).toHaveBeenCalledWith(30_000);
    fireEvent.mouseDown(screen.getByRole('tab', { name: '文章正文' }), {
      button: 0,
      ctrlKey: false,
    });
    expect(screen.getByRole('article')).toHaveTextContent(
      articleResult.closing,
    );
  });
});
