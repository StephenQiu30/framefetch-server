'use client';

import type { ReactNode } from 'react';
import { PageHeader } from '@/components/layout/page-header';
import { PageNavigation } from '@/components/layout/page-navigation';
import { SplitLayout } from '@/components/layout/split-layout';
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from '@/components/ui/field';
import { InputGroup } from '@/components/ui/input-group';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';

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
    <div className="inner-page" data-slot="auth-frame">
      <PageNavigation fallbackHref="/" />
      <SplitLayout columns="primary">
        <div className="flex min-w-0 flex-col gap-8">
          <PageHeader
            description={description}
            title={title}
            titleId={titleId}
          />
          <div className="w-full max-w-md">{children}</div>
        </div>
        <ItemGroup className="gap-4 self-start">
          <Item variant="muted">
            <ItemContent>
              <ItemTitle className="line-clamp-none">
                FrameFetch 万能视频下载器
              </ItemTitle>
              <ItemDescription className="line-clamp-none">
                下载公开、免费、非 DRM
                的视频，导入本地视频与剧本文档，并按需进行 AI 分析。
              </ItemDescription>
            </ItemContent>
          </Item>
          <Item>
            <ItemContent>
              <ItemTitle className="line-clamp-none">
                在自己的部署中使用
              </ItemTitle>
              <ItemDescription className="line-clamp-none">
                账户用于管理当前实例的下载、文档与分析。实际下载能力以链接检查和最终文件为准，请仅处理有权使用的内容。
              </ItemDescription>
            </ItemContent>
          </Item>
        </ItemGroup>
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
