'use client';

import { FileText, FileVideo, LinkSimple } from '@phosphor-icons/react';
import type { ReactNode } from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export type IntakeMode = 'link' | 'video' | 'screenplay';

export function ContentIntakeHero({
  disabled,
  linkForm,
  mode,
  onModeChange,
  screenplayForm,
  videoForm,
}: {
  disabled: boolean;
  linkForm: ReactNode;
  mode: IntakeMode;
  onModeChange: (mode: IntakeMode) => void;
  screenplayForm: ReactNode;
  videoForm: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-10 sm:gap-12">
      <PageHeader
        size="lg"
        description="解析公开视频、图片与合集链接，或上传本地视频与剧本文档。"
        title="把素材，带回本地。"
      />

      <Tabs
        className="w-full gap-6"
        onValueChange={(value) => onModeChange(value as IntakeMode)}
        value={mode}
      >
        <TabsList
          aria-label="选择内容来源"
          className="max-w-full"
          variant="default"
        >
          <TabsTrigger className="min-w-0" disabled={disabled} value="link">
            <LinkSimple aria-hidden />
            链接解析
          </TabsTrigger>
          <TabsTrigger className="min-w-0" disabled={disabled} value="video">
            <FileVideo aria-hidden />
            本地视频
          </TabsTrigger>
          <TabsTrigger
            className="min-w-0"
            disabled={disabled}
            value="screenplay"
          >
            <FileText aria-hidden />
            剧本文档
          </TabsTrigger>
        </TabsList>
        <TabsContent value="link">{linkForm}</TabsContent>
        <TabsContent value="video">{videoForm}</TabsContent>
        <TabsContent value="screenplay">{screenplayForm}</TabsContent>
      </Tabs>
    </div>
  );
}
