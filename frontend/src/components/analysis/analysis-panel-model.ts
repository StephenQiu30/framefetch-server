export enum AnalysisStatusCode {
  Queued = 'queued',
  Running = 'running',
  RetryWait = 'retry_wait',
  Succeeded = 'succeeded',
  Failed = 'failed',
  Cancelled = 'cancelled',
}

export enum AnalysisReportStatusCode {
  Validated = 'validated',
  Publishing = 'publishing',
  PublishFailed = 'publish_failed',
  Available = 'available',
  DeletePending = 'delete_pending',
  Deleted = 'deleted',
}

enum ScreenplayAnalysisErrorCode {
  ResourceLimit = 'analysis_resource_limit',
  OutputIncomplete = 'screenplay_output_incomplete',
  InputArtifactUnavailable = 'input_artifact_unavailable',
  InvalidModelOutput = 'invalid_model_output',
}

enum AnalysisStageCode {
  Preparing = 'preparing',
  Analyzing = 'analyzing',
  Validating = 'validating',
  Publishing = 'publishing',
}

type AnalysisStatusPresentation = {
  label: string;
  active: boolean;
  variant: 'default' | 'secondary' | 'destructive' | 'outline';
};

const analysisStatusPresentation = {
  [AnalysisStatusCode.Queued]: {
    label: '等待分析',
    active: true,
    variant: 'secondary',
  },
  [AnalysisStatusCode.Running]: {
    label: '正在分析',
    active: true,
    variant: 'secondary',
  },
  [AnalysisStatusCode.RetryWait]: {
    label: '等待重试',
    active: true,
    variant: 'secondary',
  },
  [AnalysisStatusCode.Succeeded]: {
    label: '分析已完成',
    active: false,
    variant: 'default',
  },
  [AnalysisStatusCode.Failed]: {
    label: '分析失败',
    active: false,
    variant: 'destructive',
  },
  [AnalysisStatusCode.Cancelled]: {
    label: '分析已取消',
    active: false,
    variant: 'outline',
  },
} satisfies Record<API.AnalysisStatus, AnalysisStatusPresentation>;

export const statusLabels = {
  [AnalysisStatusCode.Queued]:
    analysisStatusPresentation[AnalysisStatusCode.Queued].label,
  [AnalysisStatusCode.Running]:
    analysisStatusPresentation[AnalysisStatusCode.Running].label,
  [AnalysisStatusCode.RetryWait]:
    analysisStatusPresentation[AnalysisStatusCode.RetryWait].label,
  [AnalysisStatusCode.Succeeded]:
    analysisStatusPresentation[AnalysisStatusCode.Succeeded].label,
  [AnalysisStatusCode.Failed]:
    analysisStatusPresentation[AnalysisStatusCode.Failed].label,
  [AnalysisStatusCode.Cancelled]:
    analysisStatusPresentation[AnalysisStatusCode.Cancelled].label,
} satisfies Record<API.AnalysisStatus, string>;

export function isActiveAnalysisStatus(status: API.AnalysisStatus): boolean {
  return analysisStatusPresentation[status].active;
}

export function analysisStatusVariant(
  status: API.AnalysisStatus,
): AnalysisStatusPresentation['variant'] {
  return analysisStatusPresentation[status].variant;
}

export function isTerminalAnalysisStatus(status: API.AnalysisStatus): boolean {
  return !isActiveAnalysisStatus(status);
}

const analysisReportStatusLabels = {
  [AnalysisReportStatusCode.Validated]: '报告等待生成',
  [AnalysisReportStatusCode.Publishing]: '新报告文件生成中',
  [AnalysisReportStatusCode.PublishFailed]: '报告文件生成失败，等待恢复',
  [AnalysisReportStatusCode.Available]: '上一版本报告',
  [AnalysisReportStatusCode.DeletePending]: '报告文件正在清理',
  [AnalysisReportStatusCode.Deleted]: '报告文件已清理',
} satisfies Record<API.AnalysisReportStatus, string>;

export function analysisReportStatusLabel(
  status?: API.AnalysisReportStatus,
): string {
  return status
    ? (analysisReportStatusLabels[status] ?? '报告状态更新中')
    : '报告尚未生成';
}

export const stageLabels: Record<API.AnalysisStage, string> = {
  [AnalysisStageCode.Preparing]: '准备输入',
  drafting: '写作',
  reviewing: '审阅',
  revising: '修订',
  [AnalysisStageCode.Analyzing]: '执行 AI 分析',
  [AnalysisStageCode.Validating]: '校验结构化结果',
  [AnalysisStageCode.Publishing]: '生成报告文件',
};

const screenplayAnalysisErrorMessages: Partial<
  Record<API.AnalysisErrorCode, string>
> = {
  [ScreenplayAnalysisErrorCode.ResourceLimit]:
    '剧本任务达到当前执行器资源上限，未发布部分结果；请稍后重试，持续出现时联系管理员调整分析配置。',
  [ScreenplayAnalysisErrorCode.OutputIncomplete]:
    '剧本改写结果不完整，任务未发布任何部分正文，请重试。',
  [ScreenplayAnalysisErrorCode.InputArtifactUnavailable]:
    '规范化剧本文档已失效，请重新导入后再分析。',
  [ScreenplayAnalysisErrorCode.InvalidModelOutput]:
    'AI 返回的剧本结果未通过结构、证据或覆盖校验，未发布部分结果。',
};

export function screenplayAnalysisErrorMessage(
  code: API.AnalysisErrorCode | null | undefined,
): string | undefined {
  return code ? screenplayAnalysisErrorMessages[code] : undefined;
}
