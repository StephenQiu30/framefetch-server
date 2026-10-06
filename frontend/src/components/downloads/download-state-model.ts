import { localizedErrorMessage } from '@/lib/error-messages';

export enum DownloadStatusCode {
  Queued = 'queued',
  Running = 'running',
  RetryWait = 'retry_wait',
  Succeeded = 'succeeded',
  Failed = 'failed',
  Cancelled = 'cancelled',
}

enum DownloadStageCode {
  Revalidating = 'revalidating',
  Downloading = 'downloading',
  Remuxing = 'remuxing',
  Verifying = 'verifying',
  Uploading = 'uploading',
}

enum DownloadErrorCode {
  FormatUnavailable = 'format_unavailable',
  MediaValidationFailed = 'media_validation_failed',
  LoginRequired = 'login_required',
}

type DownloadStatusPresentation = {
  label: string;
  historyLabel: string;
  variant: 'secondary' | 'default' | 'destructive';
  active: boolean;
  heading: (job: API.DownloadResponse) => string;
  description: (job: API.DownloadResponse) => string;
  executionTitle: (job: API.DownloadResponse) => string;
  stage: (job: API.DownloadResponse) => string | null;
};

const downloadStatusPresentation = {
  [DownloadStatusCode.Queued]: {
    label: '等待处理',
    historyLabel: '排队中',
    variant: 'secondary',
    active: true,
    heading: () => '下载即将开始',
    description: () => '任务已经进入队列，开始后会实时更新进度。',
    executionTitle: () => '任务由隔离的媒体 Runner 执行',
    stage: () => null,
  },
  [DownloadStatusCode.Running]: {
    label: '正在下载',
    historyLabel: '下载中',
    variant: 'secondary',
    active: true,
    heading: (job) => `正在准备${archiveLabel(job)}文件`,
    description: () => '正在完成媒体下载、封装与文件校验。',
    executionTitle: () => '任务由隔离的媒体 Runner 执行',
    stage: (job) => (job.stage ? downloadStageLabels[job.stage] : '等待调度'),
  },
  [DownloadStatusCode.RetryWait]: {
    label: '等待重试',
    historyLabel: '等待重试',
    variant: 'secondary',
    active: true,
    heading: () => '等待再次尝试',
    description: () => '系统会在等待结束后自动继续当前任务。',
    executionTitle: () => '任务由隔离的媒体 Runner 执行',
    stage: (job) => (job.stage ? downloadStageLabels[job.stage] : '等待调度'),
  },
  [DownloadStatusCode.Succeeded]: {
    label: '服务端已完成',
    historyLabel: '已完成',
    variant: 'default',
    active: false,
    heading: (job) =>
      job.file_available
        ? `${archiveLabel(job)}文件已就绪`
        : `${archiveLabel(job)}文件已清理`,
    description: (job) => {
      if (!job.file_available) return '下载记录仍然保留，可以重新创建任务。';
      return job.media_kind === 'image_gallery' ||
        job.media_kind === 'video_collection'
        ? `${archiveLabel(job)}文件已在服务器完成校验，可获取 ZIP 保存到设备。保存结果请查看浏览器下载记录；如被组织策略屏蔽，请联系策略管理者。`
        : '视频文件已在服务器完成校验，可获取文件保存到设备。保存结果请查看浏览器下载记录；如被组织策略屏蔽，请联系策略管理者。';
    },
    executionTitle: (job) =>
      job.file_available ? '文件完整性验证通过' : '下载记录已保留',
    stage: () => '已完成',
  },
  [DownloadStatusCode.Failed]: {
    label: '下载失败',
    historyLabel: '失败',
    variant: 'destructive',
    active: false,
    heading: (job) => failureTitle(job.error_code),
    description: (job) => failedStatusDescription(job.error_code),
    executionTitle: () => '等待恢复操作',
    stage: (job) => failureStage(job.error_code),
  },
  [DownloadStatusCode.Cancelled]: {
    label: '任务已取消',
    historyLabel: '已取消',
    variant: 'secondary',
    active: false,
    heading: () => '下载已取消',
    description: () => '任务已经停止，随时可以重新创建下载。',
    executionTitle: () => '任务记录已保留',
    stage: () => '已取消',
  },
} satisfies Record<API.DownloadStatus, DownloadStatusPresentation>;

export const statusLabels = {
  [DownloadStatusCode.Queued]:
    downloadStatusPresentation[DownloadStatusCode.Queued].label,
  [DownloadStatusCode.Running]:
    downloadStatusPresentation[DownloadStatusCode.Running].label,
  [DownloadStatusCode.RetryWait]:
    downloadStatusPresentation[DownloadStatusCode.RetryWait].label,
  [DownloadStatusCode.Succeeded]:
    downloadStatusPresentation[DownloadStatusCode.Succeeded].label,
  [DownloadStatusCode.Failed]:
    downloadStatusPresentation[DownloadStatusCode.Failed].label,
  [DownloadStatusCode.Cancelled]:
    downloadStatusPresentation[DownloadStatusCode.Cancelled].label,
} satisfies Record<API.DownloadStatus, string>;

export const downloadStatusLabels = {
  [DownloadStatusCode.Queued]:
    downloadStatusPresentation[DownloadStatusCode.Queued].historyLabel,
  [DownloadStatusCode.Running]:
    downloadStatusPresentation[DownloadStatusCode.Running].historyLabel,
  [DownloadStatusCode.RetryWait]:
    downloadStatusPresentation[DownloadStatusCode.RetryWait].historyLabel,
  [DownloadStatusCode.Succeeded]:
    downloadStatusPresentation[DownloadStatusCode.Succeeded].historyLabel,
  [DownloadStatusCode.Failed]:
    downloadStatusPresentation[DownloadStatusCode.Failed].historyLabel,
  [DownloadStatusCode.Cancelled]:
    downloadStatusPresentation[DownloadStatusCode.Cancelled].historyLabel,
} satisfies Record<API.DownloadStatus, string>;

export const downloadStageLabels: Record<API.DownloadStage, string> = {
  [DownloadStageCode.Revalidating]: '重新验证',
  [DownloadStageCode.Downloading]: '下载媒体',
  [DownloadStageCode.Remuxing]: '封装媒体',
  [DownloadStageCode.Verifying]: '校验文件',
  [DownloadStageCode.Uploading]: '保存制品',
};

const failureDetails: Record<string, string> = {
  'artifact is unavailable': '下载文件暂时不可用，请重新获取下载源。',
  'artifact path is unsafe': '下载文件路径校验失败，请重新获取下载源。',
  'artifact size is invalid': '下载文件大小校验失败，请重新获取下载源。',
  'artifact digest is invalid': '下载文件摘要校验失败，请重新获取下载源。',
  'artifact digest does not match': '下载文件内容校验失败，请重新获取下载源。',
  'artifact media metadata is invalid':
    '生成的视频流与所选规格不一致，请重新下载。',
  'artifact container is unsupported':
    '视频封装格式暂不支持，请重新获取下载源。',
};

const failureTitles: Partial<Record<API.DownloadErrorCode, string>> = {
  [DownloadErrorCode.LoginRequired]: '需要登录',
  [DownloadErrorCode.MediaValidationFailed]: '文件校验未通过',
  [DownloadErrorCode.FormatUnavailable]: '当前格式不可用',
};

const failureStages: Partial<Record<API.DownloadErrorCode, string>> = {
  [DownloadErrorCode.LoginRequired]: '登录要求未满足',
  [DownloadErrorCode.MediaValidationFailed]: '文件校验失败',
  [DownloadErrorCode.FormatUnavailable]: '下载源检查失败',
};

const retryActionLabels: Partial<Record<API.DownloadErrorCode, string>> = {
  [DownloadErrorCode.LoginRequired]: '重新下载',
  [DownloadErrorCode.MediaValidationFailed]: '重新获取并下载',
  [DownloadErrorCode.FormatUnavailable]: '重新获取并下载',
};

const failedStatusDescriptions: Partial<Record<API.DownloadErrorCode, string>> =
  {
    [DownloadErrorCode.LoginRequired]:
      '该内容需要登录，请确认部署主机已登录对应平台。',
    [DownloadErrorCode.MediaValidationFailed]:
      '生成文件未通过完整性校验，系统会重新下载并再次验证。',
  };

export function isActiveDownloadStatus(status: API.DownloadStatus): boolean {
  return downloadStatusPresentation[status].active;
}

export function isTerminalDownloadStatus(status: API.DownloadStatus): boolean {
  return !isActiveDownloadStatus(status);
}

export function downloadRecovery(
  job: Pick<
    API.DownloadResponse,
    'source_kind' | 'status' | 'file_available'
  > & {
    error_code?: API.DownloadErrorCode | null;
  },
): 'retry' | 'reimport' | 'reparse' | null {
  const terminal =
    job.status === DownloadStatusCode.Failed ||
    job.status === DownloadStatusCode.Cancelled ||
    (job.status === DownloadStatusCode.Succeeded && !job.file_available);
  if (!terminal) return null;
  if (
    job.source_kind === 'remote_provider' &&
    job.error_code === 'context_changed'
  )
    return 'reparse';
  return job.source_kind === 'remote_provider' ? 'retry' : 'reimport';
}

export function statusVariant(status: API.DownloadStatus) {
  return downloadStatusPresentation[status].variant;
}

export function statusHeading(job: API.DownloadResponse) {
  return downloadStatusPresentation[job.status].heading(job);
}

export function statusDescription(job: API.DownloadResponse) {
  if (downloadRecovery(job) === 'reimport')
    return '任务记录仍然保留。请返回首页重新选择本地文件导入。';
  return downloadStatusPresentation[job.status].description(job);
}

export function executionTitle(job: API.DownloadResponse) {
  return downloadStatusPresentation[job.status].executionTitle(job);
}

export function displayStage(job: API.DownloadResponse): string {
  return (
    downloadStatusPresentation[job.status].stage(job) ??
    (job.stage ? downloadStageLabels[job.stage] : '等待调度')
  );
}

export function failureTitle(code: API.DownloadResponse['error_code']): string {
  return code ? (failureTitles[code] ?? '下载未完成') : '下载未完成';
}

function failureStage(code: API.DownloadResponse['error_code']): string {
  if (!code) return '需要恢复';
  return (
    failureStages[code] ??
    (localizedErrorMessage(code) ? '执行失败' : '需要恢复')
  );
}

export function retryActionLabel(
  code: API.DownloadResponse['error_code'],
): string {
  if (!code) return '重新下载';
  return retryActionLabels[code] ?? '重新下载';
}

export function failureDescription(job: API.DownloadResponse): string {
  const detail = job.error_message?.trim();
  if (detail && detail !== job.error_code) {
    return (
      failureDetails[detail] ??
      localizedErrorMessage(job.error_code) ??
      '下载任务未能完成，请稍后重试。'
    );
  }
  return (
    localizedErrorMessage(job.error_code) ?? '下载任务未能完成，请稍后重试。'
  );
}

function failedStatusDescription(code: API.DownloadResponse['error_code']) {
  return (
    (code && failedStatusDescriptions[code]) ??
    '系统保留了失败记录，可以根据原因恢复下载。'
  );
}

function archiveLabel(job: API.DownloadResponse) {
  return job.media_kind === 'image_gallery'
    ? '图集'
    : job.media_kind === 'video_collection'
      ? '视频合集'
      : '视频';
}
