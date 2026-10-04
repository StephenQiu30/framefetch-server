'use client';

import AnalysisEditorialReview from '@/components/analysis/analysis-editorial-review';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { formatMilliseconds } from '@/lib/format';

export default function AnalysisArticleResultView({
  onSelectTime,
  result,
}: {
  onSelectTime?: (milliseconds: number) => void;
  result: API.VideoArticleResultResponse;
}) {
  return (
    <Tabs className="mt-10 gap-0" defaultValue="article">
      <TabsList className="w-max" variant="line">
        <TabsTrigger value="article">文章正文</TabsTrigger>
        <TabsTrigger value="evidence">回查依据</TabsTrigger>
      </TabsList>
      <TabsContent value="article">
        <article
          aria-label="文章正文"
          className="mt-8 max-w-3xl break-words text-base leading-8"
        >
          <h2 className="text-2xl font-medium tracking-tight sm:text-3xl">
            {result.title}
          </h2>
          {result.lead ? (
            <p className="mt-6 whitespace-pre-line">{result.lead}</p>
          ) : null}
          {result.sections.map((section) => (
            <section
              className={section.title ? 'mt-10' : 'mt-6'}
              key={section.id}
            >
              {section.title ? (
                <h3 className="text-xl font-medium">{section.title}</h3>
              ) : null}
              <p
                className={
                  section.title
                    ? 'mt-4 whitespace-pre-line'
                    : 'whitespace-pre-line'
                }
              >
                {section.body}
              </p>
            </section>
          ))}
          {result.closing ? (
            <p className="mt-8 whitespace-pre-line">{result.closing}</p>
          ) : null}
        </article>
        <AnalysisEditorialReview result={result} />
      </TabsContent>
      <TabsContent value="evidence">
        <div className="mt-8 max-w-3xl break-words">
          {result.sections.map((section, index) => (
            <section className="mb-8" key={section.id}>
              <h3 className="text-lg font-medium">
                {section.title || `段落 ${index + 1}`}
              </h3>
              <ul className="mt-3 flex flex-col gap-3 text-sm leading-7 text-muted-foreground">
                {section.evidence.map((evidence) => (
                  <li
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
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {result.key_points.length ? (
            <>
              <h3 className="text-lg font-medium">要点核对</h3>
              <ul className="mt-3 flex flex-col gap-3 list-disc pl-5 leading-7 text-muted-foreground">
                {result.key_points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </>
          ) : null}
          {result.limitations.length ? (
            <section className="mt-8">
              <h3 className="text-lg font-medium">待核验信息</h3>
              <ul className="mt-3 flex flex-col gap-2 list-disc pl-5 leading-7 text-muted-foreground">
                {result.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </TabsContent>
    </Tabs>
  );
}
