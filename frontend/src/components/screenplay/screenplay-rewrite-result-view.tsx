'use client';

import { ArrowRightIcon } from '@phosphor-icons/react';
import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import {
  languageLabel,
  Metric,
  ResultTab,
} from '@/components/screenplay/screenplay-result-primitives';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList } from '@/components/ui/tabs';

const categoryLabels: Record<string, string> = {
  character: '人物',
  honorific: '称谓',
  location: '地点',
  other: '其他',
  term: '术语',
  title: '标题',
};

export default function ScreenplayRewriteResultView({
  reportMarkdown,
  result,
}: {
  reportMarkdown?: string | null;
  result: API.ScreenplayRewriteResultResponse;
}) {
  return (
    <Tabs className="mt-10 gap-0" defaultValue="summary">
      <div className="grid gap-5 sm:grid-cols-3">
        <Metric label="源场景" value={`${result.source_scene_count}`} />
        <Metric label="输出场景" value={`${result.output_scene_count}`} />
        <Metric
          label="语言"
          value={
            <span className="inline-flex flex-wrap items-center gap-1">
              <span>{languageLabel(result.source_language)}</span>
              <ArrowRightIcon aria-hidden className="size-4 shrink-0" />
              <span className="sr-only">至</span>
              <span>{languageLabel(result.target_language)}</span>
            </span>
          }
        />
      </div>
      <div className="mt-10 overflow-x-auto">
        <TabsList className="w-max" variant="line">
          <ResultTab value="summary">术语与摘要</ResultTab>
          {reportMarkdown ? (
            <ResultTab value="report">改写正文</ResultTab>
          ) : null}
        </TabsList>
      </div>
      <TabsContent value="summary">
        <div>
          <ItemTitle className="line-clamp-none">
            <h3 id="rewrite-glossary-title">统一术语</h3>
          </ItemTitle>
          {result.glossary.length ? (
            <Table className="table-borderless mt-4 text-left">
              <TableCaption className="sr-only">
                剧本改写统一术语表
              </TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-2/5 whitespace-nowrap">
                    原文
                  </TableHead>
                  <TableHead className="w-2/5 whitespace-nowrap">
                    统一写法
                  </TableHead>
                  <TableHead className="whitespace-nowrap">类别</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.glossary.map((term) => (
                  <TableRow key={`${term.category}:${term.source}`}>
                    <TableCell className="w-2/5 whitespace-normal [overflow-wrap:anywhere]">
                      {term.source}
                    </TableCell>
                    <TableCell className="w-2/5 whitespace-normal [overflow-wrap:anywhere]">
                      {term.target}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {categoryLabels[term.category] ?? term.category}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <ItemDescription className="line-clamp-none mt-4">
              本次改写没有需要单独统一的术语。
            </ItemDescription>
          )}
        </div>
        <div className="mt-10 max-w-4xl">
          <ItemTitle className="line-clamp-none">
            <h3 id="rewrite-summary-title">修改摘要</h3>
          </ItemTitle>
          <ul className="mt-4 flex flex-col gap-2 list-disc">
            {result.change_summary.map((summary) => (
              <li key={summary}>{summary}</li>
            ))}
          </ul>
        </div>
      </TabsContent>
      {reportMarkdown ? (
        <TabsContent value="report">
          <ItemDescription className="line-clamp-none mb-6 max-w-3xl">
            以下正文由受限 AI 按源场景顺序确定性合并，仅用于改写与本地化参考。
          </ItemDescription>
          <AnalysisReportPreview markdown={reportMarkdown} />
        </TabsContent>
      ) : null}
    </Tabs>
  );
}
