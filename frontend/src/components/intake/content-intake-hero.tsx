'use client';

import { Eraser, FileText, FileVideo, LinkSimple } from '@phosphor-icons/react';
import type { ReactNode } from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export type IntakeMode = 'link' | 'video' | 'screenplay' | 'watermark';

export function ContentIntakeHero({
  disabled,
  linkForm,
  mode,
  onModeChange,
  screenplayForm,
  videoForm,
  watermarkForm,
}: {
  disabled: boolean;
  linkForm: ReactNode;
  mode: IntakeMode;
  onModeChange: (mode: IntakeMode) => void;
  screenplayForm: ReactNode;
  videoForm: ReactNode;
  watermarkForm: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        size="lg"
        description={
          mode === 'watermark'
            ? '上传本地视频，自动去水印，原片始终保留。'
            : '粘贴视频页或分享链接，选择画质后下载，自动校验并处理水印。'
        }
        title={mode === 'watermark' ? '视频去水印' : '下载任意公开视频'}
      />

      <Tabs
        className="w-full gap-4"
        onValueChange={(value) => onModeChange(value as IntakeMode)}
        value={mode}
      >
        <TabsList
          aria-label="选择内容来源"
          className="h-auto max-w-full flex-wrap"
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
          <TabsTrigger
            className="min-w-0"
            disabled={disabled}
            value="watermark"
          >
            <Eraser aria-hidden />
            视频去水印
          </TabsTrigger>
        </TabsList>
        <TabsContent value="link">{linkForm}</TabsContent>
        <TabsContent value="watermark">{watermarkForm}</TabsContent>
        <TabsContent value="video">{videoForm}</TabsContent>
        <TabsContent value="screenplay">{screenplayForm}</TabsContent>
      </Tabs>
    </div>
  );
}
