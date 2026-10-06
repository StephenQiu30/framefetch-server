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
    <div className="flex flex-col gap-6">
      <PageHeader
        size="lg"
        description="粘贴视频页或分享链接，帧取列出可用画质，下载完成后自动校验文件完整性。"
        title="下载任意公开视频"
      />

      <Tabs
        className="w-full gap-4"
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
            链接下载
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
