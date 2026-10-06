'use client';

import { CheckCircleIcon, LinkIcon } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { PageHeader } from '@/components/layout/page-header';
import { SplitLayout } from '@/components/layout/split-layout';
import MediaCover from '@/components/media/media-cover';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from '@/components/ui/field';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from '@/components/ui/item';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';

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
          data-slot="auth-preview-panel"
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
            <div aria-hidden inert className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <InputGroup>
                  <InputGroupAddon>
                    <LinkIcon />
                  </InputGroupAddon>
                  <InputGroupInput
                    readOnly
                    tabIndex={-1}
                    value="https://www.bilibili.com/video/…"
                  />
                </InputGroup>
                <Button tabIndex={-1}>解析链接</Button>
              </div>
              <Item variant="outline">
                <ItemMedia className="w-36">
                  <MediaCover
                    alt=""
                    className="w-full"
                    compact
                    fallback={{
                      detail: '12:48',
                      eyebrow: '哔哩哔哩',
                      title: '城市夜景延时摄影合集',
                    }}
                  />
                </ItemMedia>
                <ItemContent className="gap-2">
                  <ItemTitle>城市夜景延时摄影合集</ItemTitle>
                  <ItemDescription>哔哩哔哩 · 公开内容</ItemDescription>
                  <RadioGroup disabled value="1080">
                    {[
                      ['1080', '1080p · MP4'],
                      ['2160', '2160p · WebM'],
                    ].map(([value, label]) => (
                      <div className="flex items-center gap-2" key={value}>
                        <RadioGroupItem value={value} />
                        <span className="text-sm">{label}</span>
                      </div>
                    ))}
                  </RadioGroup>
                </ItemContent>
              </Item>
              <Item variant="outline">
                <ItemMedia variant="icon">
                  <CheckCircleIcon />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>下载完成，文件已校验</ItemTitle>
                </ItemContent>
                <Badge variant="secondary">可在线播放</Badge>
              </Item>
            </div>
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
