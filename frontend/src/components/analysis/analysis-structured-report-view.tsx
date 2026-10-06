'use client';

import AnalysisEditorialReview from '@/components/analysis/analysis-editorial-review';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import { Button } from '@/components/ui/button';
import { Item, ItemDescription, ItemTitle } from '@/components/ui/item';
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
      <div className="grid grid-cols-2 gap-3 sm:gap-5">
        <Metric label="报告章节" value={`${result.sections.length}`} />
        <Metric
          label={result.media ? '视频时长' : '来源类型'}
          value={
            result.media ? formatMilliseconds(result.media.duration_ms) : '文档'
          }
        />
      </div>
      <div className="mt-8 w-full">
        <ItemTitle className="line-clamp-none">
          <h3>摘要</h3>
        </ItemTitle>
        <ItemDescription className="line-clamp-none mt-3 whitespace-pre-line">
          {result.summary}
        </ItemDescription>
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
                <ItemDescription className="line-clamp-none">
                  章节 {index + 1}
                </ItemDescription>
                <h4 className="mt-2">{section.heading}</h4>
                {result.media ? (
                  <ItemDescription className="line-clamp-none mt-4 whitespace-pre-line">
                    {section.body}
                  </ItemDescription>
                ) : (
                  <div className="mt-4 min-w-0">
                    <AnalysisReportPreview markdown={section.body} />
                  </div>
                )}
                {section.items.length ? (
                  <ul className="mt-4 flex flex-col gap-2 list-disc">
                    {section.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {result.media && section.evidence.length ? (
                  <div className="mt-5 flex flex-col gap-1">
                    {section.evidence.map((evidence) => (
                      <ItemDescription
                        className="line-clamp-none"
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
                      </ItemDescription>
                    ))}
                  </div>
                ) : null}
                {section.citations?.length ? (
                  <div className="mt-5 flex min-w-0 flex-col gap-3">
                    {section.citations.map((citation) => (
                      <ItemDescription
                        className="line-clamp-none"
                        key={`${citation.source_sha256}-${citation.start}-${citation.end}`}
                      >
                        原文第 {citation.start + 1}–{citation.end} 个字符
                      </ItemDescription>
                    ))}
                  </div>
                ) : null}
              </li>
            </Item>
          ))}
        </ol>
        {sourceDigests.length ? (
          <div className="mt-8 min-w-0">
            {sourceDigests.map((sha) => (
              <ItemDescription className="line-clamp-none" key={sha}>
                原文 SHA-256：<code className="break-all">{sha}</code>
              </ItemDescription>
            ))}
          </div>
        ) : null}
        {result.limitations.length ? (
          <div className="mt-8">
            <h4>事实边界与待核验项</h4>
            <ul className="mt-3 flex flex-col gap-2 list-disc">
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
      <ItemDescription className="line-clamp-none">{label}</ItemDescription>
      <ItemTitle className="line-clamp-none">
        <p className="mt-1 tabular-nums">{value}</p>
      </ItemTitle>
    </div>
  );
}
