import { Warning } from '@phosphor-icons/react';
import { cn } from 'cn';

import { PageErrorNotice } from '@/components/layout/page-error-notice';
import {
  documentErrorLabel,
  documentFormatLabels,
  documentStatusLabels,
  formatDocumentDate,
  formatDocumentSize,
  languageLabel,
  qualityWarningLabel,
} from '@/components/screenplay/screenplay-document-format';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';

export function ScreenplayDocumentMetadata({
  document,
}: {
  document: API.DocumentDetailResponse;
}) {
  const fields: Array<readonly [string, string]> = [
    ['格式', documentFormatLabels[document.source_format]],
    ['语言', languageLabel(document.detected_language)],
    ['场景', countLabel(document.scene_count, '个')],
    ['字符', countLabel(document.character_count, '个')],
    ['文件大小', formatDocumentSize(document.declared_size_bytes)],
    ['导入状态', documentStatusLabels[document.status]],
    ['创建时间', formatDocumentDate(document.created_at)],
    ['存储策略', '持久保存'],
  ];
  const error = documentErrorLabel(document);
  const parseFields: Array<readonly [string, string]> = document.parse_summary
    ? [
        ['页数', optionalCountLabel(document.parse_summary.page_count)],
        ['文本段', countLabel(document.parse_summary.paragraph_count, '段')],
        ['标题', countLabel(document.parse_summary.heading_count, '个')],
        ['列表项', countLabel(document.parse_summary.list_item_count, '项')],
        ['表格', countLabel(document.parse_summary.table_count, '个')],
        [
          '对白块',
          countLabel(document.parse_summary.dialogue_block_count, '个'),
        ],
      ]
    : [];

  return (
    <div className="mt-8 sm:mt-10">
      <div className="flex items-baseline justify-between gap-4">
        <ItemTitle className="line-clamp-none">
          <h2 id="document-metadata-title">文档信息</h2>
        </ItemTitle>
        <span>导入摘要</span>
      </div>
      <MetadataGrid
        className="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 lg:grid-cols-8"
        fields={fields}
      />
      {parseFields.length ? (
        <div className="mt-7">
          <ItemTitle className="line-clamp-none">
            <h3>基础解析</h3>
          </ItemTitle>
          <MetadataGrid
            className="mt-4 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6"
            fields={parseFields}
          />
        </div>
      ) : null}
      {error ? (
        <PageErrorNotice
          className="mt-6"
          compact
          message={error}
          title="解析未完成"
        />
      ) : null}
      {document.quality_warnings.length ? (
        <Alert className="mt-6" variant="default">
          <Warning aria-hidden />
          <div className="min-w-0">
            <AlertTitle>需要人工核对</AlertTitle>
            <AlertDescription>
              <ul className="mt-1 flex flex-col gap-1 list-disc">
                {document.quality_warnings.map((warning) => (
                  <li key={warning}>{qualityWarningLabel(warning)}</li>
                ))}
              </ul>
            </AlertDescription>
          </div>
        </Alert>
      ) : null}
    </div>
  );
}

function MetadataGrid({
  className,
  fields,
}: {
  className?: string;
  fields: ReadonlyArray<readonly [string, string]>;
}) {
  return (
    <ItemGroup className={cn(className, 'items-stretch')}>
      {fields.map(([label, value]) => (
        <Item className="min-w-0 items-start" key={label} role="listitem">
          <ItemContent className="gap-1">
            <ItemTitle className="line-clamp-none">{label}</ItemTitle>
            <ItemDescription
              className="line-clamp-none truncate tabular-nums"
              title={value}
            >
              {value}
            </ItemDescription>
          </ItemContent>
        </Item>
      ))}
    </ItemGroup>
  );
}

function countLabel(value: number | null, suffix: string) {
  return value === null
    ? '等待解析'
    : `${value.toLocaleString('zh-CN')} ${suffix}`;
}

function optionalCountLabel(value: number | null | undefined) {
  return value == null ? '源格式不提供' : `${value.toLocaleString('zh-CN')} 页`;
}
