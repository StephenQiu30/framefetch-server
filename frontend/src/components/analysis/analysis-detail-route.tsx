'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { getAnalysisHistoryRecord, listAnalysisRuns } from '@/api/analyses';
import AnalysisDeleteDialog from '@/components/analysis/analysis-delete-dialog';
import {
  stageLabels,
  statusLabels,
} from '@/components/analysis/analysis-panel-model';
import AnalysisReportDownloadLink from '@/components/analysis/analysis-report-download-link';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import AnalysisVideoResult, {
  isVideoAnalysisResult,
} from '@/components/analysis/analysis-video-result';
import { useAnalysisJob } from '@/components/analysis/use-analysis-job';
import { useAnalysisSkills } from '@/components/analysis/use-analysis-skills';
import ContentResultView from '@/components/content/content-result-view';
import { historyRecordLabel } from '@/components/intake/history-record-presentation';
import { DataTable } from '@/components/layout/data-table';
import { FeedbackNotice } from '@/components/layout/feedback-notice';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { PageErrorNotice } from '@/components/layout/page-error-notice';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import { ScreenplayResultView } from '@/components/screenplay/screenplay-result-view';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { localizedErrorMessage } from '@/lib/error-messages';
import { privateQueryKey } from '@/lib/query-keys';
import { displayError } from '@/lib/request-error';

export default function AnalysisDetailRoute() {
  const id = useSearchParams().get('analysisId')?.trim();
  return (
    <div className="inner-page">
      <PageNavigation fallbackHref="/history/activity" />
      {id ? (
        <AnalysisDetail key={id} id={id} />
      ) : (
        <div className="flex flex-col gap-8">
          <PageHeader title="AI 分析详情" />
          <PageEmptyNotice
            title="缺少分析记录"
            description="请从我的处理记录选择一条分析记录。"
          />
        </div>
      )}
    </div>
  );
}

function AnalysisDetail({ id }: { id: string }) {
  const record = useQuery({
    queryKey: privateQueryKey('analysis-history-record', id),
    queryFn: ({ signal }) =>
      getAnalysisHistoryRecord({ analysis_id: id }, { signal }),
  });
  if (record.isPending)
    return (
      <div
        className="flex flex-col gap-6"
        role="status"
        aria-label="正在读取分析记录"
      >
        <PageHeader title="AI 分析详情" />
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="aspect-video w-full" />
      </div>
    );
  if (record.error && !record.data)
    return (
      <div className="flex flex-col gap-8">
        <PageHeader title="AI 分析详情" />
        <PageErrorNotice
          title="分析记录不可用"
          titleAs="h2"
          message={displayError(record.error)}
          onRetry={() => void record.refetch()}
        />
      </div>
    );
  if (!record.data) return null;
  return <AnalysisDetailContent record={record.data} />;
}

function AnalysisDetailContent({
  record,
}: {
  record:
    | API.VideoAnalysisHistoryRecordResponse
    | API.ScreenplayAnalysisHistoryRecordResponse
    | API.ContentCreationHistoryRecordResponse
    | API.SkillAnalysisHistoryRecordResponse;
}) {
  const kind =
    record.record_type === 'skill_analysis'
      ? 'skill'
      : record.record_type === 'content_creation'
        ? 'content'
        : record.record_type === 'screenplay_analysis'
          ? 'screenplay'
          : 'video';
  const state = useAnalysisJob('', 3000, kind, record.id);
  const skills = useAnalysisSkills(kind);
  const skillName =
    skills.skills.find((skill) => skill.id === record.skill_id)?.display_name ??
    record.skill_id;
  const [confirmRetry, setConfirmRetry] = useState(false);
  const job = state.job;
  const active =
    job && ['queued', 'running', 'retry_wait'].includes(job.status);
  const sourceHref = record.document_id
    ? `/documents/detail?documentId=${encodeURIComponent(record.document_id)}`
    : record.download_id
      ? `/downloads/detail?jobId=${encodeURIComponent(record.download_id)}`
      : null;
  const allHref = record.document_id
    ? `/history/activity?document_id=${encodeURIComponent(record.document_id)}`
    : record.download_id
      ? `/history/activity?download_id=${encodeURIComponent(record.download_id)}`
      : '/history/activity';
  return (
    <>
      <PageHeader
        title={<span className="[overflow-wrap:anywhere]">{record.title}</span>}
        description={`${historyRecordLabel(record)} · ${skillName} · ${record.output_language}`}
      />
      <div className="mt-6 flex flex-wrap gap-3">
        <Button asChild variant="outline">
          <Link href={allHref}>查看本素材全部记录</Link>
        </Button>
        {sourceHref && record.source_availability === 'available' ? (
          <Button asChild variant="outline">
            <Link href={sourceHref}>查看源文件 / 新建分析</Link>
          </Button>
        ) : null}
      </div>
      {record.source_availability === 'unavailable' ? (
        <ItemDescription className="line-clamp-none mt-4">
          源文件不可用，无法重新执行；已有分析结果仍可查看。
        </ItemDescription>
      ) : null}
      {state.loading ? (
        <ItemDescription className="line-clamp-none" role="status">
          正在读取分析结果…
        </ItemDescription>
      ) : null}
      {state.error ? (
        <FeedbackNotice
          className="mt-6"
          presentation={state.errorKind === 'action' ? 'toast' : 'inline'}
          title="无法完成操作"
          description={state.error}
          tone="error"
          action={
            <Button onClick={() => void state.retryPoll()} variant="outline">
              重新读取
            </Button>
          }
        />
      ) : null}
      {!state.loading && !job && !state.error ? (
        <PageEmptyNotice
          title="分析记录已删除"
          description="返回我的处理记录查看其他记录。"
        />
      ) : null}
      {job ? (
        <>
          <div
            className="mt-8 flex flex-wrap items-center gap-3"
            aria-live="polite"
          >
            <Badge variant="secondary">
              {record.cancel_requested_at && active
                ? '正在取消'
                : statusLabels[job.status]}
            </Badge>
            <span>
              {job.run_trigger === 'manual_edit'
                ? `第 ${job.run_no} 份报告 · 历史人工稿`
                : `第 ${job.run_no} 次执行`}
              {active
                ? ` · ${job.progress}%${job.stage ? ` · ${stageLabels[job.stage]}` : ''}`
                : ''}
            </span>
            {active ? (
              <Button
                disabled={
                  Boolean(state.action) || Boolean(record.cancel_requested_at)
                }
                variant="outline"
                onClick={() => void state.cancel()}
              >
                取消分析
              </Button>
            ) : (
              <Button
                disabled={
                  Boolean(state.action) ||
                  job.error_code === 'analysis_outcome_unknown' ||
                  record.record_type === 'skill_analysis' ||
                  record.record_type === 'content_creation' ||
                  record.source_availability !== 'available'
                }
                variant="outline"
                onClick={() => setConfirmRetry(true)}
              >
                {job.status === 'succeeded' ? '重新运行' : '重试'}
              </Button>
            )}
            <AnalysisDeleteDialog
              busy={state.action === 'delete'}
              disabled={Boolean(state.action)}
              onDelete={state.remove}
            />
            {job.report?.status === 'available'
              ? (['md', 'docx'] as const).map((format) => (
                  <Button key={format} asChild variant="outline">
                    <AnalysisReportDownloadLink
                      analysisId={job.id}
                      format={format}
                      download={`analysis-${job.id}.${format}`}
                    >
                      导出 {format === 'md' ? 'Markdown' : 'DOCX'}
                    </AnalysisReportDownloadLink>
                  </Button>
                ))
              : null}
          </div>
          {confirmRetry ? (
            <FeedbackNotice
              className="mt-5"
              title="按原配置重新运行"
              description="将保留任务编号并增加执行次数，可能消耗模型额度。调整材料或目的请新建任务。"
              action={
                <div className="flex gap-2">
                  <Button
                    disabled={
                      Boolean(state.action) ||
                      job.error_code === 'analysis_outcome_unknown'
                    }
                    onClick={() => {
                      setConfirmRetry(false);
                      void state.retry();
                    }}
                  >
                    确认执行
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setConfirmRetry(false)}
                  >
                    取消
                  </Button>
                </div>
              }
            />
          ) : null}
          {job.error_code ? (
            <FeedbackNotice
              className="mt-4"
              description={
                localizedErrorMessage(job.error_code) ??
                `错误代码：${job.error_code}`
              }
              title="分析任务未完成"
              tone="error"
            />
          ) : null}
          {job.result?.kind === 'skill_report' ? (
            <AnalysisReportPreview
              markdown={job.report_markdown ?? job.result.body}
            />
          ) : isVideoAnalysisResult(job.result, job.input_kind) ? (
            <AnalysisVideoResult
              result={job.result}
              reportMarkdown={job.report_markdown}
            />
          ) : job.result?.kind === 'content_document' ? (
            <ContentResultView
              result={job.result}
              markdown={job.report_markdown}
              analysisId={job.id}
              reportId={job.current_report_id}
              historicalEdit={job.run_trigger === 'manual_edit'}
            />
          ) : job.result ? (
            <ScreenplayResultView
              result={job.result}
              reportMarkdown={job.report_markdown}
            />
          ) : null}
          <AnalysisRuns
            key={`${job.id}:${job.run_no}`}
            id={job.id}
            runNo={job.run_no}
            active={Boolean(active)}
          />
        </>
      ) : null}
    </>
  );
}

export function AnalysisRuns({
  id,
  runNo,
  active,
}: {
  id: string;
  runNo: number;
  active: boolean;
}) {
  const [cursors, setCursors] = useState<(number | undefined)[]>([undefined]);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const before = cursors.at(-1);
  const runs = useQuery({
    queryKey: privateQueryKey(
      'analysis-runs',
      id,
      runNo,
      before,
      pageSize,
      active,
    ),
    queryFn: ({ signal }) =>
      listAnalysisRuns(
        { analysis_id: id, before_run_no: before, limit: pageSize },
        { signal },
      ),
    refetchInterval: (query) => (active && !query.state.error ? 3000 : false),
  });
  return (
    <section className="mt-12" aria-label="运行记录">
      <ItemTitle className="line-clamp-none">
        <h2>运行记录</h2>
      </ItemTitle>
      {runs.error ? (
        <FeedbackNotice
          className="mt-4"
          title="运行记录读取失败"
          description={displayError(runs.error)}
          tone="error"
          action={<Button onClick={() => void runs.refetch()}>重试</Button>}
        />
      ) : null}
      {runs.isPending ? (
        <ItemDescription className="line-clamp-none" role="status">
          正在读取运行记录…
        </ItemDescription>
      ) : null}
      {runs.data?.items.length ? (
        <DataTable
          data={runs.data.items}
          caption="分析运行记录"
          getRowId={(run) => run.id}
          columns={[
            {
              id: 'run',
              header: '执行',
              hideable: false,
              cell: (run) => (
                <div className="flex flex-col gap-2">
                  <ItemTitle>
                    {run.trigger === 'manual_edit'
                      ? `第 ${run.run_no} 份报告 · 历史人工稿`
                      : `第 ${run.run_no} 次`}
                  </ItemTitle>
                  <div className="flex flex-col gap-2 sm:hidden">
                    <Badge variant="secondary">
                      {statusLabels[run.status]}
                    </Badge>
                    <time dateTime={run.created_at}>
                      {new Date(run.created_at).toLocaleString('zh-CN', {
                        hour12: false,
                      })}
                    </time>
                  </div>
                  {run.error_code ? (
                    <ItemDescription className="line-clamp-none">
                      {localizedErrorMessage(run.error_code) ??
                        '这次运行未完成，请查看任务状态。'}
                    </ItemDescription>
                  ) : null}
                </div>
              ),
            },
            {
              id: 'status',
              header: '状态',
              className: 'hidden sm:table-cell',
              cell: (run) => (
                <Badge variant="secondary">{statusLabels[run.status]}</Badge>
              ),
            },
            {
              id: 'created',
              header: '创建时间',
              className: 'hidden sm:table-cell',
              cell: (run) => (
                <time dateTime={run.created_at}>
                  {new Date(run.created_at).toLocaleString('zh-CN', {
                    hour12: false,
                  })}
                </time>
              ),
            },
          ]}
        />
      ) : null}
      {runs.data ? (
        <PagePagination
          pageSize={pageSize}
          onPageSizeChange={(size) => {
            setPageSize(size);
            setCursors([undefined]);
          }}
          ariaLabel="运行记录分页"
          page={cursors.length}
          hasNext={Boolean(runs.data.next_before_run_no)}
          busy={runs.isFetching}
          onPageChange={(page) => {
            const nextBefore = runs.data?.next_before_run_no;
            if (page < cursors.length) {
              setCursors((value) => value.slice(0, page));
            } else if (page === cursors.length + 1 && nextBefore != null) {
              setCursors((value) => [...value, nextBefore]);
            }
          }}
        />
      ) : null}
    </section>
  );
}
