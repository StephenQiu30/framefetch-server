'use client';

import AnalysisEditorialReview from '@/components/analysis/analysis-editorial-review';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import { Button } from '@/components/ui/button';
import { Item } from '@/components/ui/item';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { formatMillisecondRange, formatMilliseconds } from '@/lib/format';

export default function AnalysisStructuredReportView({
  onSelectTime,
  reportMarkdown,
  result,
}: {
  onSelectTime?: (milliseconds: number) => void;
  reportMarkdown?: string | null;
  result: API.StructuredReportResultResponse;
}) {
  const sourceDigests = [
    ...new Set(
      result.sections.flatMap(
        (section) =>
          section.citations?.map((citation) => citation.source_sha256) ?? [],
      ),
    ),
  ];
  return (
    <Tabs className="mt-10 gap-0" defaultValue="report-sections">
      <AnalysisEditorialReview result={result} />
      <div className="grid grid-cols-2 gap-3 py-4 sm:gap-5">
        <Metric label="报告章节" value={`${result.sections.length}`} />
        <Metric
          label={result.media ? '视频时长' : '来源类型'}
          value={
            result.media ? formatMilliseconds(result.media.duration_ms) : '文档'
          }
        />
      </div>
      <div className="mt-8 w-full">
        <h3 className="text-xl font-medium tracking-tight">摘要</h3>
        <p className="mt-3 whitespace-pre-line text-base leading-8 text-muted-foreground">
          {result.summary}
        </p>
      </div>
      <div className="mt-10 overflow-x-auto">
        <TabsList className="w-max" variant="line">
          <TabsTrigger value="report-sections">报告内容</TabsTrigger>
          {reportMarkdown ? (
            <TabsTrigger value="report">报告预览</TabsTrigger>
          ) : null}
        </TabsList>
      </div>
      <TabsContent value="report-sections">
        <ol className="gap-2">
          {result.sections.map((section, index) => (
            <Item asChild className="block" key={section.id}>
              <li>
                <p className="text-xs text-muted-foreground">
                  章节 {index + 1}
                </p>
                <h4 className="mt-2 text-xl font-medium">{section.heading}</h4>
                {result.media ? (
                  <p className="mt-4 whitespace-pre-line leading-8 text-muted-foreground">
                    {section.body}
                  </p>
                ) : (
                  <div className="mt-4 min-w-0">
                    <AnalysisReportPreview markdown={section.body} />
                  </div>
                )}
                {section.items.length ? (
                  <ul className="mt-4 flex flex-col gap-2 list-disc pl-5 leading-7">
                    {section.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {result.media && section.evidence.length ? (
                  <div className="mt-5 flex flex-col gap-1 text-sm text-muted-foreground">
                    {section.evidence.map((evidence) => (
                      <p
                        key={`${evidence.start_ms}-${evidence.end_ms}-${evidence.note}`}
                      >
                        <Button
                          className="tabular-nums"
                          disabled={!onSelectTime}
                          onClick={() => onSelectTime?.(evidence.start_ms)}
                          type="button"
                          variant="link"
                          aria-label={`查看视频依据 ${formatMillisecondRange(evidence.start_ms, evidence.end_ms)}`}
                        >
                          {formatMillisecondRange(
                            evidence.start_ms,
                            evidence.end_ms,
                          )}
                        </Button>{' '}
                        {evidence.note}
                      </p>
                    ))}
                  </div>
                ) : null}
                {section.citations?.length ? (
                  <div className="mt-5 flex min-w-0 flex-col gap-3 text-sm text-muted-foreground">
                    {section.citations.map((citation) => (
                      <p
                        key={`${citation.source_sha256}-${citation.start}-${citation.end}`}
                      >
                        原文第 {citation.start + 1}–{citation.end} 个字符
                      </p>
                    ))}
                  </div>
                ) : null}
              </li>
            </Item>
          ))}
        </ol>
        {sourceDigests.length ? (
          <div className="mt-8 min-w-0 text-xs text-muted-foreground">
            {sourceDigests.map((sha) => (
              <p key={sha}>
                原文 SHA-256：<code className="break-all">{sha}</code>
              </p>
            ))}
          </div>
        ) : null}
        {result.limitations.length ? (
          <div className="mt-8 py-6">
            <h4 className="font-medium">事实边界与待核验项</h4>
            <ul className="mt-3 flex flex-col gap-2 list-disc pl-5 leading-7 text-muted-foreground">
              {result.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </TabsContent>
      {reportMarkdown ? (
        <TabsContent value="report">
          <AnalysisReportPreview markdown={reportMarkdown} />
        </TabsContent>
      ) : null}
    </Tabs>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl tabular-nums">{value}</p>
    </div>
  );
}
