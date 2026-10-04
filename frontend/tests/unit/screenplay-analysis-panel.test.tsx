import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ScreenplayAnalysisPanel from '@/components/screenplay/screenplay-analysis-panel';
import { httpClient } from '@/lib/request';
import {
  screenplayAnalysisJob,
  screenplaySkills,
} from '../fixtures/screenplay-analysis-fixtures';
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

  it('opens the source document before creating from a selected historical analysis', async () => {
    const job = screenplayAnalysisJob('analysis');
    const record = {
      id: job.id,
      document_id: documentId,
    };
    vi.mocked(httpClient.request).mockImplementation(async (config) => {
      const payload = config.url?.endsWith('/history-record')
        ? record
        : config.url === '/api/analysis-skills'
          ? screenplaySkills
          : job;
      return { data: { code: 'ok', message: 'OK', data: payload } } as never;
    });

    render(
      <ScreenplayAnalysisPanel documentId={documentId} analysisId={job.id} />,
    );
    fireEvent.click(
      await screen.findByRole('button', {
        name: '使用最新 Skill 新建任务',
      }),
    );

    expect(push).toHaveBeenCalledWith(
      `/documents/detail?documentId=${documentId}`,
    );
    expect(httpRequests().every((request) => request.method === 'GET')).toBe(
      true,
    );
  });

  it('discloses cloud processing and creates a document-bound task', async () => {
    mockHttpResponses(
      null,
      screenplaySkills,
      screenplayAnalysisJob('analysis', 'queued'),
    );
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    expect(await screen.findByLabelText('剧本任务')).toHaveAttribute(
      'id',
      'screenplay-analysis-skill',
    );
    await waitFor(() =>
      expect(screen.getByLabelText('分析或改写要求')).toHaveValue(
        '重点分析故事结构、人物弧光、场景功能、节奏与对白。',
      ),
    );
    expect(
      screen.getByText(/剧本文本和任务要求会发送到所选云端模型/),
    ).toBeInTheDocument();
    expect(screen.getByText(/需要统一的术语和相邻场景/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '开始剧本分析' }));
    expect(await screen.findByText('等待分析')).toBeInTheDocument();
    const create = httpRequests().find((request) => request.method === 'POST');
    expect(create?.url).toBe(`/api/documents/${documentId}/analyses`);
    expect(create?.headers?.['Idempotency-Key']).toBe(
      '22222222-2222-4222-8222-222222222222',
    );
    expect(
      httpRequests().some(
        (request) =>
          request.method === 'GET' &&
          request.url === `/api/documents/${documentId}/analysis`,
      ),
    ).toBe(true);
  });

  it('turns the primary action into a rewrite action for the rewrite Skill', async () => {
    mockHttpResponses(null, screenplaySkills);
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    await waitFor(() =>
      expect(screen.getByLabelText('剧本任务')).toBeEnabled(),
    );
    fireEvent.click(screen.getByLabelText('剧本任务'));
    fireEvent.click(await screen.findByRole('option', { name: '剧本改写' }));

    expect(screen.getByRole('button', { name: '开始剧本改写' })).toBeEnabled();
    expect(screen.getByLabelText('分析或改写要求')).toHaveValue(
      '保持故事意图与剧本格式，使用自然、可拍摄的表达。',
    );
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
    expect(screen.getByRole('button', { name: '重试任务' })).toBeEnabled();
  });
});
