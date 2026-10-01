'use client';

import { DownloadSimple, UploadSimple } from '@phosphor-icons/react';

import FormatPicker from '@/components/intake/format-picker';
import MediaCover from '@/components/media/media-cover';
import { MediaResult } from '@/components/media/media-result';
import { Button } from '@/components/ui/button';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item';
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

  return (
    <div data-slot="inspection-result">
      <MediaResult
        headingLevel={2}
        title={inspection.title}
        media={
          <MediaCover
            alt={`${inspection.title} 媒体封面`}
            fallback={{
              detail: inspectionDetailLabel(
                inspection,
                selected?.plan ?? undefined,
              ),
              eyebrow: inspection.extractor_key,
              title: inspection.title,
            }}
            priority
            src={inspection.thumbnail_url}
          />
        }
        metadata={
          <ItemGroup
            aria-label="媒体信息"
            className="mt-2 flex-row flex-wrap items-start justify-start gap-x-3 gap-y-2 text-left tabular-nums"
          >
            <Meta label="平台" mono value={inspection.extractor_key} />
            {inspection.duration_seconds > 0 ? (
              <Meta
                label="时长"
                value={formatDuration(inspection.duration_seconds)}
              />
            ) : null}
            {gallery ? (
              <Meta
                label="媒体"
                value={`图文作品 · ${inspection.asset_count} 张原图`}
              />
            ) : collection ? (
              <Meta
                label="媒体"
                value={`视频合集 · ${inspection.asset_count} 个视频`}
              />
            ) : selected?.plan ? (
              <Meta
                label="当前清晰度"
                value={`${selected.plan.width}×${selected.plan.height}`}
              />
            ) : null}
          </ItemGroup>
        }
        panel={{
          title: downloadable
            ? gallery || collection
              ? '下载内容'
              : '画质预设'
            : decisionTitle(inspection),
          footer:
            inspection.access_decision === 'export_required' ? (
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
                {busy ? '正在创建任务…' : '创建下载任务'}
              </Button>
            ) : undefined,
        }}
        actions={
          <>
            {downloadable ? (
              <FormatPicker
                formats={inspection.formats}
                mediaKind={inspection.media_kind}
                onChange={onChange}
                selectedId={selectedId}
              />
            ) : (
              <div aria-live="polite" className="py-6">
                <p className="text-sm leading-6 text-muted-foreground">
                  {inspection.user_action ?? '当前来源不能创建下载任务。'}
                </p>
              </div>
            )}
            {selected?.plan ? (
              <ItemGroup className="mt-7 grid grid-cols-2 gap-x-5 gap-y-4">
                <SelectionMeta
                  label="容器"
                  value={selected.plan.container_preference.toUpperCase()}
                />
                <SelectionMeta
                  label="兼容策略"
                  value={compatibilityLabel(
                    selected.plan.compatibility_profile,
                  )}
                />
                <SelectionMeta
                  label="视频编码"
                  value={selected.plan.video_codec_family.toUpperCase()}
                />
                <SelectionMeta
                  label="音频编码"
                  value={audioCodecLabel(selected.plan.audio_codec_family)}
                />
              </ItemGroup>
            ) : (gallery || collection) && selected ? (
              <ItemGroup className="mt-7 grid grid-cols-2 gap-x-5 gap-y-4">
                <SelectionMeta
                  label="媒体类型"
                  value={collection ? '视频合集' : '官方图文'}
                />
                <SelectionMeta
                  label="内容数量"
                  value={`${inspection.asset_count} ${
                    collection ? '个视频' : '张原图'
                  }`}
                />
                <SelectionMeta label="导出格式" value="ZIP" />
                <SelectionMeta
                  label="下载方式"
                  value={collection ? '视频打包' : '原图打包'}
                />
              </ItemGroup>
            ) : null}
          </>
        }
      />
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

function Meta({
  label,
  mono = false,
  value,
}: {
  label: string;
  mono?: boolean;
  value: string;
}) {
  return (
    <Item
      className="flex w-auto items-center gap-3 before:content-['·'] first:before:hidden"
      role="listitem"
    >
      <ItemContent className="flex-none gap-0">
        <ItemTitle className="sr-only">{label}</ItemTitle>
        <ItemDescription className={mono ? 'font-mono' : 'tabular-nums'}>
          {value}
        </ItemDescription>
      </ItemContent>
    </Item>
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

function SelectionMeta({ label, value }: { label: string; value: string }) {
  return (
    <Item className="items-start" role="listitem">
      <ItemContent className="gap-1">
        <ItemTitle>{label}</ItemTitle>
        <ItemDescription className="line-clamp-none">{value}</ItemDescription>
      </ItemContent>
    </Item>
  );
}

function compatibilityLabel(value: string) {
  if (value === 'quality') return '画质优先';
  if (value === 'smallest') return '体积优先';
  return '均衡';
}
