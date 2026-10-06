'use client';

import { DownloadSimple, UploadSimple } from '@phosphor-icons/react';
import FormatPicker from '@/components/intake/format-picker';
import { PageHeader } from '@/components/layout/page-header';
import { SplitLayout } from '@/components/layout/split-layout';
import MediaCover from '@/components/media/media-cover';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from '@/components/ui/item';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { formatDuration } from '@/lib/format';
import { audioCodecLabel } from '@/lib/media-format';

type InspectionWorkspaceProps = {
  busy: boolean;
  inspection: API.InspectionResponse;
  onChange: (id: string) => void;
  onCreate: () => void;
  onUseUpload: () => void;
  selectedId: string;
};

export default function InspectionWorkspace({
  busy,
  inspection,
  onChange,
  onCreate,
  onUseUpload,
  selectedId,
}: InspectionWorkspaceProps) {
  const downloadable = inspection.access_decision === 'downloadable';
  const selected = downloadable
    ? inspection.formats.find((item) => item.id === selectedId)
    : undefined;
  const gallery = inspection.media_kind === 'image_gallery';
  const collection = inspection.media_kind === 'video_collection';
  const platform =
    inspection.execution_context?.provider_key === 'wechat_channels'
      ? '微信视频号'
      : inspection.extractor_key;
  const best = downloadable
    ? inspection.formats.reduce<API.SemanticPlanResponse | null>(
        (best, item) =>
          item.plan && (!best || item.plan.height > best.height)
            ? item.plan
            : best,
        null,
      )
    : null;

  return (
    <div data-slot="inspection-result">
      <SplitLayout columns="primary" data-slot="inspection-layout">
        <section aria-label="媒体信息" className="flex flex-col gap-6">
          <div data-slot="media-result-frame">
            <MediaCover
              alt={`${inspection.title} 媒体封面`}
              fallback={{
                detail: inspectionDetailLabel(
                  inspection,
                  selected?.plan ?? undefined,
                ),
                eyebrow: platform,
                title: inspection.title,
              }}
              priority
              src={inspection.thumbnail_url}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="secondary">{platform}</Badge>
            <FieldDescription>{scopeLabel(inspection)}</FieldDescription>
          </div>
          <PageHeader title={inspection.title} />
          <dl
            aria-label="媒体规格"
            className="grid grid-cols-2 gap-4 sm:grid-cols-4"
          >
            {inspection.duration_seconds > 0 ? (
              <Metadata
                label="时长"
                value={formatDuration(inspection.duration_seconds)}
              />
            ) : null}
            {best ? (
              <Metadata label="最高画质" value={`${best.height}P`} />
            ) : null}
            <Metadata
              label="可选格式"
              value={`${downloadable ? inspection.formats.length : 0} 种`}
            />
            <Metadata
              label="来源"
              value={sourceOriginLabel(inspection.source_origin)}
            />
            {gallery ? (
              <Metadata
                label="媒体"
                value={`图文作品 · ${inspection.asset_count} 张原图`}
              />
            ) : collection ? (
              <Metadata
                label="媒体"
                value={`视频合集 · ${inspection.asset_count} 个视频`}
              />
            ) : null}
          </dl>
          {downloadable && inspection.user_action ? (
            <Alert className="mt-4">
              <AlertDescription>{inspection.user_action}</AlertDescription>
            </Alert>
          ) : null}
        </section>
        <section
          aria-label="下载设置"
          className="flex min-h-0 flex-col gap-6 lg:contain-size"
        >
          <Item
            variant="muted"
            className="min-h-0 flex-1 flex-nowrap items-stretch"
          >
            <ItemContent className="min-h-0 gap-4">
              <ItemTitle>
                <h2>
                  {downloadable
                    ? gallery || collection
                      ? '下载内容'
                      : '画质预设'
                    : decisionTitle(inspection)}
                </h2>
              </ItemTitle>
              {downloadable ? (
                <FormatPicker
                  formats={inspection.formats}
                  mediaKind={inspection.media_kind}
                  onChange={onChange}
                  selectedId={selectedId}
                />
              ) : (
                <ItemDescription aria-live="polite" className="line-clamp-none">
                  {inspection.user_action ?? '当前来源不能创建下载任务。'}
                </ItemDescription>
              )}
            </ItemContent>
          </Item>
          <div
            className="mt-auto flex flex-col gap-4"
            data-slot="inspection-actions"
          >
            {selected?.plan ? (
              <>
                <FieldGroup className="grid sm:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="inspection-container">
                      保存格式
                    </FieldLabel>
                    <Select disabled value={selected.plan.container_preference}>
                      <SelectTrigger
                        id="inspection-container"
                        className="w-full"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem
                            value={selected.plan.container_preference}
                          >
                            {selected.plan.container_preference.toUpperCase()}
                          </SelectItem>
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="inspection-format">
                      下载规格
                    </FieldLabel>
                    <Input
                      id="inspection-format"
                      readOnly
                      value={selected.display_name}
                    />
                  </Field>
                </FieldGroup>
                <dl className="grid grid-cols-2 gap-4">
                  <Metadata
                    label="兼容策略"
                    value={compatibilityLabel(
                      selected.plan.compatibility_profile,
                    )}
                  />
                  <Metadata
                    label="视频编码"
                    value={selected.plan.video_codec_family.toUpperCase()}
                  />
                  <Metadata
                    label="音频编码"
                    value={audioCodecLabel(selected.plan.audio_codec_family)}
                  />
                </dl>
                <FieldDescription>
                  保存格式由所选画质方案决定。下载完成后校验文件完整性。
                </FieldDescription>
              </>
            ) : (gallery || collection) && selected ? (
              <dl className="grid grid-cols-2 gap-4">
                <Metadata
                  label="媒体类型"
                  value={collection ? '视频合集' : '官方图文'}
                />
                <Metadata
                  label="内容数量"
                  value={`${inspection.asset_count} ${
                    collection ? '个视频' : '张原图'
                  }`}
                />
                <Metadata label="导出格式" value="ZIP" />
                <Metadata
                  label="下载方式"
                  value={collection ? '视频打包' : '原图打包'}
                />
              </dl>
            ) : null}
            {inspection.access_decision === 'export_required' ? (
              <Button className="w-full" onClick={onUseUpload}>
                <UploadSimple data-icon="inline-start" />
                上传自有 MP4
              </Button>
            ) : downloadable ? (
              <Button
                className="w-full"
                disabled={!selectedId || busy}
                onClick={onCreate}
              >
                <DownloadSimple data-icon="inline-start" />
                {busy ? '正在创建任务…' : '开始下载'}
              </Button>
            ) : null}
          </div>
        </section>
      </SplitLayout>
    </div>
  );
}

function decisionTitle(inspection: API.InspectionResponse) {
  const titles: Record<string, string> = {
    content_preview_only: '仅提供试看内容',
    content_supporter_only: '充电专属内容',
    content_paid_only: '付费内容暂不支持下载',
    content_export_required: '尚未提供文件导出授权',
    content_access_metadata_invalid: '内容权益信息无法确认',
  };
  const title = titles[inspection.restriction_reason ?? ''];
  if (title) return title;
  const decision = inspection.access_decision;
  if (decision === 'playback_only') return '仅支持官方播放';
  if (decision === 'export_required') return '需要导入自有文件';
  if (decision === 'blocked') return '当前不可下载';
  return '当前来源不可下载';
}

function Metadata({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt>
        <FieldDescription>{label}</FieldDescription>
      </dt>
      <dd>
        <ItemTitle className="line-clamp-none [overflow-wrap:anywhere]">
          {value}
        </ItemTitle>
      </dd>
    </div>
  );
}

function inspectionDetailLabel(
  inspection: API.InspectionResponse,
  selected: API.InspectionResponse['formats'][number]['plan'] | undefined,
) {
  if (inspection.media_kind === 'image_gallery') {
    return `${inspection.asset_count} 张原图 · ZIP`;
  }
  if (inspection.media_kind === 'video_collection') {
    return `${inspection.asset_count} 个视频 · ZIP`;
  }
  if (selected) {
    return `${selected.width}×${selected.height}`;
  }
  return '封面未提供';
}

function scopeLabel(inspection: API.InspectionResponse) {
  const scope =
    inspection.rights_basis === 'public_access'
      ? '公开内容'
      : inspection.rights_basis === 'official_asset_grant'
        ? '官方分享文件'
        : inspection.rights_basis === 'owner_authorized_export'
          ? '已授权导出'
          : inspection.rights_basis === 'user_provided'
            ? '用户提供的文件'
            : '内容范围尚未确认';
  return inspection.execution_context
    ? `${scope} · ${inspection.execution_context.identity_used ? '使用 Chrome 身份' : '未使用平台身份'}`
    : scope;
}

function compatibilityLabel(value: string) {
  if (value === 'quality') return '画质优先';
  if (value === 'smallest') return '体积优先';
  return '均衡';
}

function sourceOriginLabel(origin: API.SourceOrigin) {
  return {
    public_url: '公开视频链接',
    discovered_item: '来源中的媒体',
    official_asset: '官方文件',
    verified_import: '已验证导入',
  }[origin];
}
