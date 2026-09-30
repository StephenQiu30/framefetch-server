'use client';

import { cn } from 'cn';

import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import { Button } from '@/components/ui/button';
import { Item } from '@/components/ui/item';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { formatMilliseconds } from '@/lib/format';

export default function AnalysisArticleResultView({
  onSelectTime,
  reportMarkdown,
  result,
}: {
  onSelectTime?: (milliseconds: number) => void;
  reportMarkdown?: string | null;
  result: API.VideoArticleResultResponse;
}) {
  return (
    <Tabs className="mt-10 gap-0" defaultValue="article">
      <div className="grid grid-cols-3 gap-3 py-4 sm:gap-5">
        <Metric label="文章章节" value={`${result.sections.length}`} />
        <Metric
          label="视频时长"
          value={formatMilliseconds(result.media.duration_ms)}
        />
        <Metric label="核心观点" value={`${result.key_points.length}`} />
      </div>
      <div className="mt-8 w-full">
        <h3 className="text-xl font-medium tracking-tight">导读</h3>
        <p className="mt-3 text-base leading-8 text-muted-foreground">
          {result.lead}
        </p>
      </div>
      <div className="mt-10 overflow-x-auto">
        <TabsList className="w-max" variant="line">
          <Tab value="article">文章正文</Tab>
          <Tab value="points">核心观点</Tab>
          {reportMarkdown ? <Tab value="report">报告预览</Tab> : null}
        </TabsList>
      </div>
      <TabsContent value="article">
        <ol className={cn('gap-2')}>
          {result.sections.map((section, index) => (
            <Item asChild className="block" key={section.id}>
              <li>
                <p className="text-xs text-muted-foreground">
                  章节 {index + 1}
                </p>
                <h4 className="mt-2 text-xl font-medium">{section.title}</h4>
                <p className="mt-4 whitespace-pre-line leading-8 text-muted-foreground">
                  {section.body}
                </p>
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
                        aria-label={`查看视频依据 ${formatMilliseconds(evidence.start_ms)}–${formatMilliseconds(evidence.end_ms)}`}
                      >
                        {formatMilliseconds(evidence.start_ms)}–
                        {formatMilliseconds(evidence.end_ms)}
                      </Button>{' '}
                      {evidence.note}
                    </p>
                  ))}
                </div>
              </li>
            </Item>
          ))}
        </ol>
      </TabsContent>
      <TabsContent value="points">
        <ul className="flex flex-col gap-3 list-disc py-4 pl-5 leading-7 text-muted-foreground">
          {result.key_points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
        {result.limitations.length ? (
          <div className="mt-8 py-6">
            <h4 className="font-medium">说明与局限</h4>
            <ul className="mt-3 flex flex-col gap-2 list-disc pl-5 leading-7 text-muted-foreground">
              {result.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="mt-8 leading-7 text-muted-foreground">{result.closing}</p>
      </TabsContent>
      {reportMarkdown ? (
        <TabsContent value="report">
          <AnalysisReportPreview markdown={reportMarkdown} />
        </TabsContent>
      ) : null}
    </Tabs>
  );
}

function Tab({ children, value }: { children: string; value: string }) {
  return <TabsTrigger value={value}>{children}</TabsTrigger>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl tabular-nums">{value}</p>
    </div>
  );
}
