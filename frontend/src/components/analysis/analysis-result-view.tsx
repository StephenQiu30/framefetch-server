'use client';

import { Images, Sparkle } from '@phosphor-icons/react';
import { cn } from 'cn';

import type { ReactNode } from 'react';

import AnalysisReportPreview from '@/components/analysis/analysis-report-preview';
import AnalysisSceneList from '@/components/analysis/analysis-scene-list';
import { PageEmptyNotice } from '@/components/layout/page-empty-notice';
import { Button } from '@/components/ui/button';
import { Item, ItemDescription, ItemTitle } from '@/components/ui/item';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { formatMilliseconds } from '@/lib/format';

const assetTypeLabels: Record<string, string> = {
  person: '人物',
  location: '地点',
  object: '物体',
  product: '产品',
  logo: '标志',
  on_screen_text: '画面文字',
};

export default function AnalysisResultView({
  defaultView = 'shots',
  onSelectTime,
  reportMarkdown,
  result,
}: {
  defaultView?: 'scenes' | 'shots';
  onSelectTime?: (milliseconds: number) => void;
  reportMarkdown?: string | null;
  result: API.VideoAnalysisResultResponse;
}) {
  return (
    <Tabs className="mt-10 gap-0" defaultValue={defaultView}>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 sm:gap-5">
        <Metric label="分镜数量" value={`${result.shot_count}`} />
        <Metric label="场景数量" value={`${result.scenes.length}`} />
        <Metric
          label="视频时长"
          value={formatMilliseconds(result.media.duration_ms)}
        />
        <Metric label="视觉资产" value={`${result.assets.length}`} />
      </div>
      <div className="mt-8 w-full">
        <ItemTitle className="line-clamp-none">
          <h3>视觉摘要</h3>
        </ItemTitle>
        <ItemDescription className="line-clamp-none mt-3">
          {result.summary.text}
        </ItemDescription>
      </div>
      <div className="mt-10 overflow-x-auto">
        <TabsList className="w-max" variant="line">
          <ResultTab value="scenes">场景</ResultTab>
          <ResultTab value="shots">分镜</ResultTab>
          <ResultTab value="highlights">高光</ResultTab>
          <ResultTab value="assets">资产</ResultTab>
          {reportMarkdown ? (
            <ResultTab value="report">报告预览</ResultTab>
          ) : null}
        </TabsList>
      </div>
      <TabsContent value="scenes">
        <AnalysisSceneList onSelectTime={onSelectTime} scenes={result.scenes} />
      </TabsContent>
      <TabsContent value="shots">
        <ol className={cn('gap-2')}>
          {result.shots.map((shot) => (
            <Item
              asChild
              className="grid gap-4 sm:grid-cols-[auto_minmax(0,1fr)]"
              key={shot.id}
            >
              <li>
                <TimeButton
                  milliseconds={shot.start_ms}
                  onSelect={onSelectTime}
                />
                <div>
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <strong>分镜 {shot.index}</strong>
                    <span>
                      {shot.shot_size} · {shot.camera_motion}
                    </span>
                  </div>
                  <ItemDescription className="line-clamp-none mt-2">
                    {shot.description}
                  </ItemDescription>
                  {shot.visual_tags.length ? (
                    <ItemDescription className="line-clamp-none mt-3">
                      {shot.visual_tags.join(' · ')}
                    </ItemDescription>
                  ) : null}
                </div>
              </li>
            </Item>
          ))}
        </ol>
      </TabsContent>
      <TabsContent value="highlights">
        {result.highlights.length ? (
          <ul className={cn('gap-2')}>
            {result.highlights.map((highlight) => (
              <Item asChild className="block" key={highlight.id}>
                <li>
                  <div className="flex items-start justify-between gap-4">
                    <strong>{highlight.title}</strong>
                    <span className="tabular-nums">评分 {highlight.score}</span>
                  </div>
                  <ItemDescription className="line-clamp-none mt-3">
                    {highlight.description}
                  </ItemDescription>
                  <ItemDescription className="line-clamp-none mt-3">
                    {highlight.reason}
                  </ItemDescription>
                  <TimeButton
                    milliseconds={highlight.start_ms}
                    onSelect={onSelectTime}
                  />
                </li>
              </Item>
            ))}
          </ul>
        ) : (
          <PageEmptyNotice
            compact
            description="未识别出独立视觉高光。"
            icon={<Sparkle aria-hidden />}
            title="暂无独立视觉高光"
          />
        )}
      </TabsContent>
      <TabsContent value="assets">
        {result.assets.length ? (
          <ul className={cn('gap-2')}>
            {result.assets.map((asset) => (
              <Item asChild className="block" key={asset.id}>
                <li>
                  <ItemDescription className="line-clamp-none">
                    {assetTypeLabels[asset.type] ?? asset.type}
                  </ItemDescription>
                  <strong className="mt-3 block">{asset.label}</strong>
                  <ItemDescription className="line-clamp-none mt-2">
                    {asset.description}
                  </ItemDescription>
                  <TimeButton
                    milliseconds={asset.first_seen_ms}
                    onSelect={onSelectTime}
                  />
                </li>
              </Item>
            ))}
          </ul>
        ) : (
          <PageEmptyNotice
            compact
            description="未识别出可复用的视觉资产。"
            icon={<Images aria-hidden />}
            title="暂无可复用的视觉资产"
          />
        )}
      </TabsContent>
      {reportMarkdown ? (
        <TabsContent value="report">
          <AnalysisReportPreview markdown={reportMarkdown} />
        </TabsContent>
      ) : null}
    </Tabs>
  );
}

function TimeButton({
  milliseconds,
  onSelect,
}: {
  milliseconds: number;
  onSelect?: (milliseconds: number) => void;
}) {
  return (
    <Button
      className="w-fit tabular-nums self-baseline justify-start"
      disabled={!onSelect}
      onClick={() => onSelect?.(milliseconds)}
      type="button"
      variant="link"
    >
      {formatMilliseconds(milliseconds)}
    </Button>
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

function ResultTab({
  children,
  value,
}: {
  children: ReactNode;
  value: string;
}) {
  return <TabsTrigger value={value}>{children}</TabsTrigger>;
}
