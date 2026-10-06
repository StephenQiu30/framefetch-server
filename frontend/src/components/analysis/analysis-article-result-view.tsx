'use client';

import AnalysisEditorialReview from '@/components/analysis/analysis-editorial-review';
import { Button } from '@/components/ui/button';
import { ItemDescription, ItemTitle } from '@/components/ui/item';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { formatMillisecondRange } from '@/lib/format';

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
        <article aria-label="文章正文" className="mt-8 max-w-3xl break-words">
          <ItemTitle className="line-clamp-none">
            <h2>{result.title}</h2>
          </ItemTitle>
          {result.lead ? (
            <ItemDescription className="line-clamp-none mt-6 whitespace-pre-line">
              {result.lead}
            </ItemDescription>
          ) : null}
          {result.sections.map((section) => (
            <section
              className={section.title ? 'mt-10' : 'mt-6'}
              key={section.id}
            >
              {section.title ? (
                <ItemTitle className="line-clamp-none">
                  <h3>{section.title}</h3>
                </ItemTitle>
              ) : null}
              <ItemDescription
                className={
                  section.title
                    ? 'mt-4 whitespace-pre-line'
                    : 'whitespace-pre-line'
                }
              >
                {section.body}
              </ItemDescription>
            </section>
          ))}
          {result.closing ? (
            <ItemDescription className="line-clamp-none mt-8 whitespace-pre-line">
              {result.closing}
            </ItemDescription>
          ) : null}
        </article>
        <AnalysisEditorialReview result={result} />
      </TabsContent>
      <TabsContent value="evidence">
        <div className="mt-8 max-w-3xl break-words">
          {result.sections.map((section, index) => (
            <section className="mb-8" key={section.id}>
              <ItemTitle className="line-clamp-none">
                <h3>{section.title || `段落 ${index + 1}`}</h3>
              </ItemTitle>
              <ul className="mt-3 flex flex-col gap-3">
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
                      aria-label={`查看视频依据 ${formatMillisecondRange(evidence.start_ms, evidence.end_ms)}`}
                    >
                      {formatMillisecondRange(
                        evidence.start_ms,
                        evidence.end_ms,
                      )}
                    </Button>{' '}
                    {evidence.note}
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {result.key_points.length ? (
            <>
              <ItemTitle className="line-clamp-none">
                <h3>要点核对</h3>
              </ItemTitle>
              <ul className="mt-3 flex flex-col gap-3 list-disc">
                {result.key_points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </>
          ) : null}
          {result.limitations.length ? (
            <section className="mt-8">
              <ItemTitle className="line-clamp-none">
                <h3>待核验信息</h3>
              </ItemTitle>
              <ul className="mt-3 flex flex-col gap-2 list-disc">
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
