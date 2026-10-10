import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { isVideoAnalysisResult } from '@/components/analysis/analysis-video-result';
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

    expect(await screen.findByLabelText('文档任务')).toHaveAttribute(
      'id',
      'screenplay-analysis-skill',
    );
    await waitFor(() =>
      expect(screen.getByLabelText('分析或整理要求')).toHaveValue(
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
      expect(screen.getByLabelText('文档任务')).toBeEnabled(),
    );
    fireEvent.click(screen.getByLabelText('文档任务'));
    fireEvent.click(await screen.findByRole('option', { name: '剧本改写' }));

    expect(screen.getByRole('button', { name: '开始剧本改写' })).toBeEnabled();
    expect(screen.getByLabelText('分析或整理要求')).toHaveValue(
      '保持故事意图与剧本格式，使用自然、可拍摄的表达。',
    );
  });

  it('labels fallback source units without claiming scene coverage', async () => {
    const job = screenplayAnalysisJob('analysis');
    if (job.result?.kind !== 'screenplay_analysis') throw new Error('fixture');
    mockHttpResponses({
      ...job,
      result: {
        ...job.result,
        scenes: job.result.scenes.map((scene) => ({
          ...scene,
          source_scene_id: 'unit-1',
        })),
      },
    });
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    const tab = await screen.findByRole('tab', { name: '文本单元' });
    expect(screen.queryByRole('tab', { name: '场景' })).not.toBeInTheDocument();
    fireEvent.mouseDown(tab, { button: 0, ctrlKey: false });
    fireEvent.click(tab);
    expect(await screen.findByText(/共 1 个文本单元/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /文本单元 1/ }),
    ).toBeInTheDocument();
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

  it('reads a legacy latest report and opens the original form without replaying the old method', async () => {
    const legacy = {
      ...screenplayAnalysisJob('analysis'),
      input_kind: 'skill',
      result_contract: 'skill-report',
      skill_id: 'article-format',
      result: {
        kind: 'skill_report',
        skill_id: 'article-format',
        title: '历史文档报告',
        summary: '历史结果保持原类型。',
        body: '不应将这个字段转换成新结果。',
      },
      report_markdown:
        '# 已保存的文档报告\n\n历史正文保持可读。\n\n```python\n  keep = "original"\n```\n',
    } satisfies API.AnalysisResponse;
    const catalog = [
      {
        ...screenplaySkills[0],
        id: 'article-format',
        display_name: '文章文档整理',
        default_prompt: '按原文论证顺序组织已有文档。',
        result_contract: 'structured-report',
      },
    ] satisfies API.AnalysisSkillResponse[];
    mockHttpResponses(legacy, catalog);
    const { container } = render(
      <ScreenplayAnalysisPanel documentId={documentId} />,
    );

    expect(await screen.findByText('历史正文保持可读。')).toBeInTheDocument();
    expect(container.querySelector('textarea')).toHaveValue(
      '  keep = "original"\n',
    );
    expect(screen.queryByText(legacy.result.body)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '导出 DOCX' })).toBeInTheDocument();
    const retry = screen.getByRole('button', { name: '重新执行' });
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    fireEvent.click(
      screen.getByRole('button', { name: '使用最新 Skill 新建任务' }),
    );
    expect(await screen.findByLabelText('文档任务')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText('分析或整理要求')).toHaveValue(
        catalog[0].default_prompt,
      ),
    );
    expect(httpRequests().every((request) => request.method === 'GET')).toBe(
      true,
    );
  });

  it('reads an ordinary-document report and source quotations in the existing report layout', async () => {
    const job = screenplayAnalysisJob('analysis');
    const quote = '整理保留作者观点与全文，只调整内容层次。';
    const sha = 'a'.repeat(64);
    const result: API.StructuredReportResultResponse = {
      kind: 'structured_report',
      language: 'zh-CN',
      title: '已有文章的结构整理',
      summary: '按原文内容组织章节，不添加新事实。',
      media: null,
      sections: [
        {
          id: 'source-block-01',
          heading: '原文的整理原则',
          body: `${quote}\n\n| 字段 | 状态 |\n| --- | --- |\n| 原文 | 保留 |\n\n\`\`\`text\n  keep spacing\n\`\`\`\n\n[来源链接](https://example.com/source)`,
          items: [],
          evidence: [],
          citations: [
            { source_sha256: sha, start: 0, end: quote.length, quote },
          ],
        },
      ],
      limitations: ['来源对应与覆盖不代表语义判断已经人工核验。'],
    };
    mockHttpResponses({
      ...job,
      skill_id: 'article-format',
      result_contract: 'structured-report',
      result,
      report_markdown: `# 已有文章的结构整理\n\n${quote}\n`,
    } satisfies API.AnalysisResponse);
    render(<ScreenplayAnalysisPanel documentId={documentId} />);

    expect(
      await screen.findByRole('heading', { name: result.title }),
    ).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '报告内容' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '报告预览' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '导出 DOCX' })).toBeInTheDocument();
    expect(await screen.findAllByText(quote)).toHaveLength(1);
    expect(
      (await screen.findByText('保留')).closest('.tc-cell'),
    ).toBeInTheDocument();
    const code = await screen.findByDisplayValue(/keep spacing/);
    expect(code).toHaveValue('  keep spacing\n');
    expect(code).toBeDisabled();
    expect(screen.getByRole('link', { name: '来源链接' })).toHaveAttribute(
      'href',
      'https://example.com/source',
    );
    expect(
      screen.getByText(`原文第 1–${quote.length} 个字符`),
    ).toBeInTheDocument();
    expect(screen.getByText(sha)).toBeInTheDocument();
    expect(screen.getByText('文档')).toBeInTheDocument();
    expect(screen.queryByText('视频时长')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /查看视频依据/ }),
    ).not.toBeInTheDocument();
    expect(isVideoAnalysisResult(result, 'screenplay')).toBe(false);
    expect(isVideoAnalysisResult(result, 'video')).toBe(false);
    const videoResult = {
      ...result,
      media: { duration_ms: 5000, container: 'mp4', size_bytes: 1000 },
    };
    expect(isVideoAnalysisResult(videoResult, 'video')).toBe(true);
    expect(isVideoAnalysisResult(videoResult, 'screenplay')).toBe(false);
    expect(httpRequests().every((request) => request.method === 'GET')).toBe(
      true,
    );
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
    expect(screen.getByText('简体中文')).toBeInTheDocument();
    expect(screen.getByText('English')).toBeInTheDocument();
    expect(screen.getByText('至')).toHaveClass('sr-only');
    const reportTab = screen.getByRole('tab', { name: '改写正文' });
    fireEvent.mouseDown(reportTab, { button: 0, ctrlKey: false });
    fireEvent.click(reportTab);
    const preview = await screen.findByLabelText('Markdown 分析报告预览');
    expect(
      await within(preview).findByText('Rewritten screenplay'),
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

  it.each(['analysis_outcome_unknown', 'analysis_cli_failed'] as const)(
    'only retries a document task with a known failure (%s)',
    async (errorCode) => {
      const failed = {
        ...screenplayAnalysisJob('analysis', 'failed'),
        error_code: errorCode,
      } satisfies API.AnalysisResponse;
      const queued = {
        ...screenplayAnalysisJob('analysis', 'queued'),
        run_no: 2,
        version: failed.version + 1,
      } satisfies API.AnalysisResponse;
      mockHttpResponses(failed, queued);
      render(<ScreenplayAnalysisPanel documentId={documentId} />);

      const retry = await screen.findByRole('button', { name: '重试任务' });
      if (errorCode === 'analysis_outcome_unknown') {
        expect(retry).toBeDisabled();
        fireEvent.click(retry);
        expect(
          httpRequests().every((request) => request.method === 'GET'),
        ).toBe(true);
      } else {
        expect(retry).toBeEnabled();
        fireEvent.click(retry);
        await screen.findByText('等待分析');
        expect(
          httpRequests().find((request) => request.method === 'POST'),
        ).toMatchObject({
          url: `/api/analyses/${failed.id}/retry`,
        });
      }
    },
  );
});
