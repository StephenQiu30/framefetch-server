import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ScreenplayAnalysisPanel from '@/components/screenplay/screenplay-analysis-panel';
import { httpClient } from '@/lib/request';
import { screenplayAnalysisJob } from '../fixtures/screenplay-analysis-fixtures';
import { stubCryptoUuids } from '../helpers/crypto';
import { httpRequests, mockHttpResponses } from '../helpers/http';
import { render } from '../helpers/query-render';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const documentId = '99999999-9999-4999-8999-999999999999';

describe('ScreenplayAnalysisPanel', () => {
  beforeEach(() => {
    vi.mocked(httpClient.request).mockReset();
    push.mockReset();
    stubCryptoUuids('22222222-2222-4222-8222-222222222222');
  });

  it('renders the screenplay evidence reading path', async () => {
    mockHttpResponses(screenplayAnalysisJob('analysis'));
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    expect(
      await screen.findByRole('heading', { name: '午夜来客' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/剪辑师必须在天亮前/)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '结构' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '人物' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '场景' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '对白' })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '优先修改' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '完整报告' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '导出 DOCX' })).toHaveAttribute(
      'href',
      '#report-docx',
    );
    const link = screen.getByRole('link', { name: '导出 DOCX' });
    const blob = new Blob(['report']);
    mockHttpResponses(blob);
    const createUrl = vi
      .spyOn(URL, 'createObjectURL')
      .mockReturnValue('blob:screenplay-report');
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    expect(fireEvent.click(link)).toBe(false);
    await waitFor(() => expect(createUrl).toHaveBeenCalledWith(blob));
    expect(httpRequests().at(-1)).toMatchObject({
      url: `/api/analyses/${screenplayAnalysisJob('analysis').id}/report.docx`,
      responseType: 'blob',
    });
    expect(click).toHaveBeenCalledOnce();
    createUrl.mockRestore();
    click.mockRestore();
  });

  it('expands and collapses a scene review with the disclosure control', async () => {
    mockHttpResponses(screenplayAnalysisJob('analysis'));
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    const scenesTab = await screen.findByRole('tab', { name: '场景' });
    fireEvent.mouseDown(scenesTab, { button: 0, ctrlKey: false });
    fireEvent.click(scenesTab);

    const scene = screen.getByRole('button', {
      name: /场景 1 · 建立任务与时限/,
    });
    expect(scene).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(scene);
    expect(scene).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('素材缺失且备份不可用')).toBeVisible();
    fireEvent.click(scene);
    expect(scene).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps rewritten text in the canonical report view', async () => {
    mockHttpResponses(screenplayAnalysisJob('rewrite'));
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    expect(
      await screen.findByRole('heading', { name: '剧本改写已完成' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Lin Zhou')).toBeInTheDocument();
    expect(screen.getByText('统一人物名译法。')).toBeInTheDocument();
    const reportTab = screen.getByRole('tab', { name: '改写正文' });
    fireEvent.mouseDown(reportTab, { button: 0, ctrlKey: false });
    fireEvent.click(reportTab);
    const preview = await screen.findByLabelText('Markdown 分析报告预览');
    expect(
      within(preview).getByText('Rewritten screenplay'),
    ).toBeInTheDocument();
    expect(screen.getByText(/仅用于改写与本地化参考/)).toBeInTheDocument();
  });

  it('explains screenplay resource failures without implying partial output', async () => {
    const failed = {
      ...screenplayAnalysisJob('rewrite', 'failed'),
      error_code: 'analysis_resource_limit',
    } satisfies API.AnalysisResponse;
    mockHttpResponses(failed);
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    expect(
      await screen.findByText(
        '剧本任务达到当前执行器资源上限，未发布部分结果；请稍后重试，持续出现时联系管理员调整分析配置。',
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '重试任务' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: '到内容工作台新建任务' }),
    ).toHaveAttribute('href', '/content');
  });
});
