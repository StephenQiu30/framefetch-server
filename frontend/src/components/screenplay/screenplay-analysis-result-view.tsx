'use client';

import { useState } from 'react';

import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import {
  DEFAULT_PAGE_SIZE,
  PagePagination,
} from '@/components/layout/page-pagination';
import {
  Detail,
  FindingList,
  languageLabel,
  Metric,
  ResultTab,
} from '@/components/screenplay/screenplay-result-primitives';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { Tabs, TabsContent, TabsList } from '@/components/ui/tabs';

function SceneReviewList({
  scenes,
  unitLabel,
}: {
  scenes: API.ScreenplaySceneResponse[];
  unitLabel: string;
}) {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const pageCount = Math.ceil(scenes.length / pageSize);
  const visiblePage = Math.min(page, Math.max(pageCount - 1, 0));
  const first = visiblePage * pageSize;
  const visibleScenes = scenes.slice(first, first + pageSize);

  return (
    <div className="flex flex-col gap-6">
      <ItemDescription className="line-clamp-none">
        共 {scenes.length} 个{unitLabel}
        。按原文顺序查看；展开条目可阅读具体判断。
      </ItemDescription>
      <Accordion type="multiple">
        <ol className="flex flex-col gap-3" start={first + 1}>
          {visibleScenes.map((scene, index) => (
            <li key={scene.id}>
              <AccordionItem value={scene.id}>
                <AccordionTrigger>
                  {unitLabel} {first + index + 1} ·{' '}
                  {scene.purpose || '未说明作用'}
                </AccordionTrigger>
                <AccordionContent>
                  <ItemGroup className="grid gap-4 sm:grid-cols-3">
                    <Detail label="冲突">{scene.conflict}</Detail>
                    <Detail label="变化">{scene.turn}</Detail>
                    <Detail label="节奏">{scene.pacing}</Detail>
                  </ItemGroup>
                  {scene.findings.length > 0 && (
                    <ul className="mt-4 list-disc flex flex-col gap-1">
                      {scene.findings.map((finding) => (
                        <li key={finding}>{finding}</li>
                      ))}
                    </ul>
                  )}
                </AccordionContent>
              </AccordionItem>
            </li>
          ))}
        </ol>
      </Accordion>
      {scenes.length > 0 && (
        <PagePagination
          ariaLabel={`${unitLabel}分页`}
          page={visiblePage + 1}
          pages={pageCount}
          onPageChange={(value) => setPage(value - 1)}
          pageSize={pageSize}
          onPageSizeChange={(size) => {
            setPageSize(size);
            setPage(0);
          }}
        />
      )}
    </div>
  );
}

export default function ScreenplayAnalysisResultView({
  reportMarkdown,
  result,
}: {
  reportMarkdown?: string | null;
  result: API.ScreenplayAnalysisResultResponse;
}) {
  const unitLabel = result.scenes.some((scene) =>
    scene.source_scene_id.startsWith('unit-'),
  )
    ? '文本单元'
    : '场景';
  return (
    <div className="mt-10 flex flex-col gap-10">
      <section
        aria-labelledby="screenplay-review-heading"
        className="flex flex-col gap-6"
      >
        <div>
          <ItemTitle className="line-clamp-none">
            <h2 id="screenplay-review-heading">审稿重点</h2>
          </ItemTitle>
          <ItemDescription className="line-clamp-none mt-2">
            先看需要修改的地方，再看值得保留的设计。
          </ItemDescription>
        </div>
        <FindingList
          heading="优先修改"
          items={result.priority_revisions}
          emptyMessage="没有足够依据提出优先修改意见。"
        />
        <FindingList
          heading="值得保留"
          items={result.strengths}
          emptyMessage="没有足够依据确认值得保留的设计。"
        />
      </section>

      <section className="flex flex-col gap-4" aria-label="故事概览">
        <div className="grid gap-4 sm:grid-cols-3">
          <Metric label={unitLabel} value={String(result.scenes.length)} />
          <Metric label="人物" value={String(result.characters.length)} />
          <Metric label="语言" value={languageLabel(result.language)} />
        </div>
        <ItemGroup className="grid gap-4">
          <Detail label="一句话故事">{result.logline}</Detail>
          <Detail label="故事梗概">{result.synopsis}</Detail>
        </ItemGroup>
      </section>

      <Tabs defaultValue="structure" className="gap-6">
        <TabsList
          className="w-full justify-start overflow-x-auto"
          variant="line"
        >
          <ResultTab value="structure">结构</ResultTab>
          <ResultTab value="characters">人物</ResultTab>
          <ResultTab value="dialogue">对白</ResultTab>
          <ResultTab value="scenes">{unitLabel}</ResultTab>
          {reportMarkdown && <ResultTab value="report">完整报告</ResultTab>}
        </TabsList>
        <TabsContent value="structure" className="flex flex-col gap-6">
          <ItemGroup>
            <Detail label="节奏概览">{result.structure.pacing_summary}</Detail>
          </ItemGroup>
          <FindingList
            heading="幕结构"
            items={result.structure.acts}
            emptyMessage="未识别幕结构。"
          />
          <FindingList
            heading="关键转折"
            items={result.structure.turning_points}
            emptyMessage="未识别关键转折。"
          />
        </TabsContent>
        <TabsContent value="characters">
          {result.characters.length ? (
            <ul className="flex flex-col gap-6">
              {result.characters.map((character) => (
                <li key={character.id} className="flex flex-col gap-4">
                  <ItemTitle className="line-clamp-none">
                    <h3>{character.name}</h3>
                  </ItemTitle>
                  <ItemGroup className="grid gap-4 sm:grid-cols-3">
                    <Detail label="目标">{character.goal}</Detail>
                    <Detail label="冲突">{character.conflict}</Detail>
                    <Detail label="人物弧">{character.arc}</Detail>
                  </ItemGroup>
                </li>
              ))}
            </ul>
          ) : (
            <ItemDescription className="line-clamp-none">
              本次结果没有独立人物条目。
            </ItemDescription>
          )}
        </TabsContent>
        <TabsContent value="dialogue" className="flex flex-col gap-6">
          <FindingList
            heading="对白发现"
            items={result.dialogue_findings}
            emptyMessage="没有足够依据提出对白审稿意见。"
          />
        </TabsContent>
        <TabsContent value="scenes">
          <SceneReviewList scenes={result.scenes} unitLabel={unitLabel} />
        </TabsContent>
        {reportMarkdown && (
          <TabsContent value="report">
            <AnalysisReportPreview markdown={reportMarkdown} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
