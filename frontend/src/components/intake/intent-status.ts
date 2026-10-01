import { localizedErrorMessage } from '@/lib/error-messages';

export enum IntentStatusCode {
  Queued = 'queued',
  Resolving = 'resolving',
  Cancelling = 'cancelling',
  Ready = 'ready',
  HandedOff = 'handed_off',
  Cancelled = 'cancelled',
  Expired = 'expired',
  Failed = 'failed',
}

type IntentStatusPresentation = {
  title: string;
  description: (intent: API.IntentResponse) => string;
  historyActionLabel: string;
  variant: 'default' | 'secondary' | 'destructive' | 'outline';
  active: boolean;
  terminal: boolean;
};

const intentStatusPresentation = {
  [IntentStatusCode.Queued]: {
    title: '等待解析',
    description: activeDescription,
    historyActionLabel: '查看进度',
    variant: 'secondary',
    active: true,
    terminal: false,
  },
  [IntentStatusCode.Resolving]: {
    title: '正在读取媒体信息',
    description: activeDescription,
    historyActionLabel: '查看进度',
    variant: 'secondary',
    active: true,
    terminal: false,
  },
  [IntentStatusCode.Cancelling]: {
    title: '正在取消解析',
    description: () => '正在确认后台解析已停止，请稍候。',
    historyActionLabel: '查看进度',
    variant: 'secondary',
    active: true,
    terminal: false,
  },
  [IntentStatusCode.Ready]: {
    title: '解析完成',
    description: (intent) =>
      intent.inspection_id
        ? '解析结果已就绪，可进入结果页选择下载规格。'
        : '解析结果引用暂不可用，请刷新解析记录后重试。',
    historyActionLabel: '查看结果',
    variant: 'default',
    active: false,
    terminal: true,
  },
  [IntentStatusCode.HandedOff]: {
    title: '下载任务已创建',
    description: (intent) =>
      intent.job_id
        ? '解析已完成，下载任务的最新状态显示在下方。'
        : '下载任务引用暂不可用，请刷新解析记录后重试。',
    historyActionLabel: '查看下载',
    variant: 'default',
    active: false,
    terminal: true,
  },
  [IntentStatusCode.Cancelled]: {
    title: '解析已取消',
    description: () => '本次解析已取消。',
    historyActionLabel: '查看详情',
    variant: 'outline',
    active: false,
    terminal: true,
  },
  [IntentStatusCode.Expired]: {
    title: '本次解析已超时',
    description: () => '本次解析已超时。',
    historyActionLabel: '查看详情',
    variant: 'outline',
    active: false,
    terminal: true,
  },
  [IntentStatusCode.Failed]: {
    title: '本次解析未完成',
    description: () => '本次解析未完成。',
    historyActionLabel: '查看详情',
    variant: 'destructive',
    active: false,
    terminal: true,
  },
} satisfies Record<API.IntentStatus, IntentStatusPresentation>;

function activeDescription(_intent: API.IntentResponse): string {
  return '任务仍在后台处理。关闭此窗口不会中断解析。';
}

export function intentTitle(status?: API.IntentStatus): string {
  return status ? intentStatusPresentation[status].title : '正在确认解析任务';
}

export function intentDescription(intent: API.IntentResponse): string {
  if (isActiveIntentStatus(intent.status))
    return intentStatusPresentation[intent.status].description(intent);
  if (intent.failure?.code) {
    const reason = localizedErrorMessage(intent.failure.code);
    if (reason) return reason;
  }
  if (intent.reason_code) {
    const reason = localizedErrorMessage(intent.reason_code);
    if (reason) return reason;
  }
  return intentStatusPresentation[intent.status].description(intent);
}

export function intentHistoryActionLabel(status: API.IntentStatus): string {
  return intentStatusPresentation[status].historyActionLabel;
}

export function intentStatusVariant(
  status: API.IntentStatus,
): IntentStatusPresentation['variant'] {
  return intentStatusPresentation[status].variant;
}

export function isActiveIntentStatus(status: API.IntentStatus): boolean {
  return intentStatusPresentation[status].active;
}

export function isTerminalIntentStatus(status: API.IntentStatus): boolean {
  return intentStatusPresentation[status].terminal;
}
