export const reportedDouyinShareMessage =
  '9.25 04/21 :1pm F@U.yt Bgb:/ ୨୧⊹ ࣪ 幸福是一步步变成小蛋糕( 𓏼˙ ᴥ ˙𓏼 )🍰 # lolilta# 小甜裙# 变装( yc@7仔 )# lolilta # 奶芙泡泡原创Lolita  https://v.douyin.com/Tq0eYJRMYRk/ 复制此链接，打开Dou音搜索，直接观看视频！';

export const inspection: API.InspectionResponse = {
  id: '11111111-1111-4111-8111-111111111111',
  extractor_key: 'Controlled',
  provider_media_id: 'video-1',
  title: 'Owned video',
  duration_seconds: 30,
  media_kind: 'video',
  asset_count: 0,
  thumbnail_url: 'data:image/jpeg;base64,Y292ZXI=',
  expires_at: '2099-08-06T11:00:00Z',
  source_origin: 'public_url',
  execution_mode: 'provider_runner',
  access_decision: 'downloadable',
  entitlement_state: 'public_free',
  identity_state: 'verified',
  protection_state: 'clear',
  rights_basis: 'public_access',
  restriction_reason: null,
  user_action: null,
  formats: [
    {
      id: '22222222-2222-4222-8222-222222222222',
      display_name: '1080p MP4',
      plan: {
        height: 1080,
        width: 1920,
        fps_bucket: 'fps_30',
        dynamic_range: 'sdr',
        video_codec_family: 'h264',
        audio_codec_family: 'aac',
        audio_language: 'zh-cn',
        container_preference: 'mp4',
        compatibility_profile: 'smallest',
      },
    },
  ],
};

export const galleryInspection: API.InspectionResponse = {
  ...inspection,
  provider_media_id: 'note-1',
  title: '官方图文作品',
  duration_seconds: 0,
  media_kind: 'image_gallery',
  asset_count: 3,
  formats: [
    {
      id: 'image-gallery-zip',
      display_name: '下载 3 张原图（ZIP）',
      plan: null,
    },
  ],
};

export const videoCollectionInspection: API.InspectionResponse = {
  ...inspection,
  provider_media_id: 'collection-1',
  title: '视频合集',
  duration_seconds: 0,
  media_kind: 'video_collection',
  asset_count: 2,
  formats: [
    {
      id: 'video-collection-zip',
      display_name: '下载 2 个视频（ZIP）',
      plan: null,
    },
  ],
};

export const sourceDiscovery: API.SourceDiscoveryResponse = {
  id: '44444444-4444-4444-8444-444444444444',
  provider_key: 'wechat_official_account_article',
  title: '含多个视频的公众号文章',
  status: 'ready',
  expires_at: '2026-08-06T11:00:00Z',
  items: [
    {
      item_ref: '55555555-5555-4555-8555-555555555555',
      kind: 'wechat_channels',
      title: '视频号片段',
      duration_ms: null,
      decision_hint: 'export_required',
      status: 'ready',
    },
    {
      item_ref: '66666666-6666-4666-8666-666666666666',
      kind: 'tencent_video',
      title: '腾讯视频片段',
      duration_ms: null,
      decision_hint: 'unsupported',
      status: 'ready',
    },
  ],
};

export function job(
  status: API.DownloadResponse['status'] = 'queued',
): API.DownloadResponse {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    inspection_id: inspection.id,
    format_id: inspection.formats[0].id,
    source_kind: 'remote_provider',
    source_label: inspection.extractor_key,
    status,
    stage: status === 'running' ? 'downloading' : null,
    progress: status === 'succeeded' ? 100 : status === 'running' ? 35 : 0,
    attempt: status === 'queued' ? 0 : 1,
    version: status === 'queued' ? 0 : status === 'running' ? 1 : 2,
    error_code: status === 'failed' ? 'download_timeout' : null,
    error_message: null,
    created_at: '2026-08-06T10:00:00Z',
    updated_at: '2026-08-06T10:00:10Z',
    finished_at: status === 'succeeded' ? '2026-08-06T10:00:10Z' : null,
    file_available: status === 'succeeded',
    title: inspection.title,
    extractor_key: inspection.extractor_key,
    duration_seconds: inspection.duration_seconds,
    media_kind: inspection.media_kind,
    asset_count: inspection.asset_count,
    thumbnail_url: inspection.thumbnail_url,
    format: inspection.formats[0].plan,
  };
}

export function galleryJob(
  status: API.DownloadResponse['status'] = 'queued',
): API.DownloadResponse {
  return {
    ...job(status),
    title: galleryInspection.title,
    duration_seconds: 0,
    media_kind: 'image_gallery',
    asset_count: galleryInspection.asset_count,
    format: null,
  };
}

export function videoCollectionJob(
  status: API.DownloadResponse['status'] = 'queued',
): API.DownloadResponse {
  return {
    ...job(status),
    title: videoCollectionInspection.title,
    duration_seconds: 0,
    media_kind: 'video_collection',
    asset_count: videoCollectionInspection.asset_count,
    format: null,
  };
}
