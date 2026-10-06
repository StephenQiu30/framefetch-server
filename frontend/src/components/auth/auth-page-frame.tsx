'use client';

import type { ReactNode } from 'react';
import { PageHeader } from '@/components/layout/page-header';
import { SplitLayout } from '@/components/layout/split-layout';
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from '@/components/ui/field';
import { InputGroup } from '@/components/ui/input-group';
import { Item, ItemContent } from '@/components/ui/item';

type AuthPageFrameProps = {
  children: ReactNode;
  description: string;
  title: string;
  titleId: string;
};

export function AuthPageFrame({
  children,
  description,
  title,
  titleId,
}: AuthPageFrameProps) {
  return (
    <div
      className="inner-page flex flex-1 flex-col justify-center"
      data-slot="auth-frame"
    >
      <SplitLayout>
        <div className="flex items-center justify-center">
          <div className="flex w-full max-w-[380px] flex-col gap-8">
            <PageHeader
              description={description}
              title={title}
              titleId={titleId}
            />
            <div>{children}</div>
          </div>
        </div>
        <Item
          variant="muted"
          className="hidden flex-col justify-center lg:flex"
          data-slot="auth-intro-panel"
        >
          <ItemContent className="w-full max-w-md flex-none gap-8">
            <div className="flex flex-col gap-3">
              <p className="text-sm font-medium text-muted-foreground">
                FrameFetch 万能视频下载器
              </p>
              <p className="text-balance text-3xl font-medium tracking-tight">
                粘贴链接，带走任意公开视频。
              </p>
              <p className="text-sm leading-6 text-muted-foreground">
                自动列出可用画质，下载完成后校验文件，并可直接在线播放。
              </p>
            </div>
            <ul className="flex flex-col gap-4">
              <li className="flex flex-col gap-1">
                <span className="font-medium">下载公开视频</span>
                <span className="text-sm leading-6 text-muted-foreground">
                  选择画质，完成后校验文件完整性。
                </span>
              </li>
              <li className="flex flex-col gap-1">
                <span className="font-medium">在线播放</span>
                <span className="text-sm leading-6 text-muted-foreground">
                  下载完成的视频可直接在任务页播放。
                </span>
              </li>
              <li className="flex flex-col gap-1">
                <span className="font-medium">AI 拉片分析</span>
                <span className="text-sm leading-6 text-muted-foreground">
                  生成分镜、场景与报告，可导出 Markdown 或 DOCX。
                </span>
              </li>
            </ul>
          </ItemContent>
        </Item>
      </SplitLayout>
    </div>
  );
}

type AuthFieldProps = {
  children: ReactNode;
  description?: string;
  error?: string;
  idPrefix: string;
  label: string;
  name: string;
};

export function AuthField({
  children,
  description,
  error,
  idPrefix,
  label,
  name,
}: AuthFieldProps) {
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={`${idPrefix}-${name}`}>{label}</FieldLabel>
      <InputGroup>{children}</InputGroup>
      {description ? (
        <FieldDescription id={`${name}-description`}>
          {description}
        </FieldDescription>
      ) : null}
      <FieldError id={`${name}-error`}>{error}</FieldError>
    </Field>
  );
}
