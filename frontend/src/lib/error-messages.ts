const localizedErrorMessages: Record<string, string> = {
  active_task_quota_exceeded:
    '同时进行的任务已达上限，请等待完成或取消任务后再试。',
  daily_task_quota_exceeded: '最近 24 小时的任务额度已用完，请稍后再试。',
  daily_byte_quota_exceeded: '最近 24 小时的文件处理额度已用完，请稍后再试。',
  analysis_budget_exceeded: '最近 24 小时的分析额度已用完，请稍后再试。',
  storage_quota_exceeded:
    '存储空间不足，请删除不再需要的文件，或等待任务完成后再试。',
  storage_file_in_use: '文件正在被分析使用，请等待分析完成后再删除。',
  analysis_already_active: '当前已有分析任务正在执行，请等待完成后再试。',
  analysis_artifact_unavailable: '原视频文件已失效，请重新下载后再分析。',
  analysis_cli_failed: 'AI 分析执行失败，请稍后重试。',
  analysis_cli_not_authenticated: 'AI 分析服务未登录，请完成登录后重试。',
  analysis_cli_timeout: 'AI 分析超时，请稍后重试。',
  analysis_cli_unavailable: 'AI 分析工具暂时不可用，请检查服务后重试。',
  analysis_cli_unsupported: '当前 AI 分析工具版本不受支持，请更新后重试。',
  analysis_media_invalid: '视频文件无法用于分析，请重新下载后重试。',
  analysis_provider_rate_limited: 'AI 服务请求过于频繁，请稍后重试。',
  analysis_provider_usage_limited: 'AI 服务额度不足，请恢复可用额度后重试。',
  analysis_report_not_ready: '分析报告仍在生成，请稍后再试。',
  analysis_report_unavailable: '分析报告暂时不可用，请重新分析后再试。',
  analysis_resource_limit: '视频超出分析资源限制，请使用更短或更小的视频。',
  analysis_retry_limited: '分析重试过于频繁，请稍后再试。',
  analysis_skill_outdated:
    '该任务保存的 Skill 已更新，请使用最新 Skill 新建分析任务。',
  analysis_sandbox_unavailable:
    'AI 安全执行环境配置异常，请联系管理员检查分析工作目录。',
  analysis_unavailable: 'AI 分析服务暂时不可用，请稍后重试。',
  artifact_not_ready: '视频文件仍在处理中，请等待下载完成后再分析。',
  cancelled: '任务已取消。',
  download_not_ready: '文件仍在处理中，请等待任务完成后再下载。',
  download_timeout: '视频下载超时，请稍后重试。',
  duration_limit_exceeded: '该平台支持下载，但当前内容超出单次处理的安全边界。',
  email_already_registered: '该邮箱已注册，请直接登录或使用其他邮箱。',
  forbidden: '当前账号没有执行此操作的权限。',
  format_unavailable:
    '平台当前没有提供所选规格，请重新解析链接后选择可用规格。',
  idempotency_conflict: '请求内容已经发生变化，请重新操作。',
  input_artifact_unavailable: '原视频文件已失效，请重新下载后再分析。',
  import_disabled: '当前部署未开放本地视频上传。',
  import_sha256_mismatch: '上传文件的校验值不一致，请重新选择原文件上传。',
  import_size_mismatch: '上传文件大小与选择时不一致，请重新选择文件。',
  import_storage_unavailable: '文件存储暂时不可用，请稍后继续上传。',
  internal_error: '服务处理失败，请稍后重试。',
  invalid_verification_code:
    '验证码错误、已过期或已使用，请检查邮箱和验证码，或重新获取。',
  verification_rate_limited: '请等待 60 秒后再获取验证码。',
  email_unavailable: '注册邮件暂不可用，请稍后重试或联系支持。',
  email_send_failed: '邮件发送未能确认，请稍后重新获取验证码。',
  invalid_credentials: '邮箱或密码错误，请重新输入。',
  invalid_model_output: 'AI 返回结果未通过校验，请重新分析。',
  invalid_provider_catalog_entry: '平台配置内容不符合要求，请检查后重试。',
  invalid_request: '提交内容不符合要求，请检查各字段后重试。',
  invalid_state: '当前任务状态不支持此操作，请刷新页面后重试。',
  invalid_url: '视频链接无效或不受支持，请检查后重试。',
  invalid_username: '用户名格式不符合要求，请重新输入。',
  last_admin_change: '请先保留另一位启用的管理员，再修改当前身份。',
  media_validation_failed: '生成文件未通过完整性校验，请重新下载后再试。',
  metrics_unavailable: '运行指标暂时不可用，请稍后重试。',
  not_found: '任务或相关资源不存在，请返回下载记录确认。',
  output_limit_exceeded: '下载文件超过大小限制，请选择更小的规格。',
  network_blocked: '当前出口无法连接媒体平台，请检查网络后重试。',
  challenge: '平台要求验证，当前无法继续读取媒体。',
  login_required: '该内容需要登录，请确认部署主机已登录对应平台。',
  identity_unavailable:
    '平台登录材料暂不可用，请检查部署主机的登录状态后重新解析。',
  context_changed: '媒体执行上下文已变化，请重新解析链接并确认下载规格。',
  content_unavailable: '内容已删除或当前不可用，请更换链接。',
  content_protected: '该内容受加密保护，无法下载；可导入已取得的文件。',
  extractor_broken: '平台页面结构已变化，当前无法读取媒体。',
  transient: '连接媒体平台时发生临时故障，请稍后重试。',
  invalid_input: '媒体链接无效或不受支持，请检查后重试。',
  runtime_unavailable: '解析执行环境暂不可用，请检查服务后重试。',
  provider_catalog_conflict: '相同标识的平台配置已经存在。',
  provider_catalog_not_found: '平台配置不存在或已被删除。',
  provider_failure: 'AI 服务未能完成分析，请稍后重试。',
  rate_limited: '操作过于频繁，请稍后再试。',
  rate_limiter_unavailable: '请求限制服务暂时不可用，请稍后重试。',
  request_timeout: '请求处理超时，请稍后重试。',
  request_too_large: '提交内容超过大小限制，请缩小后重试。',
  reserved_ai_provider_mutation:
    '本机 Codex 是系统兜底线路，只能修改显示名称和模型。',
  resource_expired: '原始媒体解析信息已失效，请重新解析链接。',
  self_admin_change: '管理员不能停用或删除自己的账户。',
  service_unavailable: '服务暂时不可用，请稍后重试。',
  storage_unavailable: '文件存储服务暂时不可用，请稍后重试。',
  temp_space_exhausted: '下载临时空间不足，请清理空间后重试。',
  transcode_required: '该视频需要转码，当前下载规格不受支持。',
  unauthenticated: '登录状态已失效，请重新登录。',
  unsupported_source: '视频来源已变化或不受支持，请重新解析链接。',
  upload_incomplete: '视频分片尚未完整上传，请检查网络后重试。',
  upload_session_expired: '上传会话已过期，请重新上传。',
  user_not_found: '用户不存在或已被删除。',
  username_already_registered: '该用户名已被使用，请更换后重试。',
  worker_lost: '任务执行服务连接中断，请确认服务正常后重试。',
  analysis_needs_material: '需要补充材料，请查看审阅意见后重新创作。',
  analysis_configuration_changed:
    '本次任务的模型或执行配置已变化，请重新创建任务。',
  analysis_outcome_unknown:
    '分析执行中断，无法确认模型调用是否已完成。为避免重复计费未自动重试，请确认后手动重新分析。',
  video_import_invalid: '视频未通过 MP4 安全校验，请更换有效文件。',
};

const localizedFailureCauses: Record<string, string> = {
  'extractor_broken:parse_response_invalid':
    '平台解析响应未通过校验，请稍后重新解析。',
  'transient:parse_request_failed': '平台解析请求失败，请检查网络后重新解析。',
  'identity_unavailable:extension_disconnected':
    '平台身份插件未连接，请确认部署主机的 Chrome 和帧取身份插件已启动。',
  'identity_unavailable:extension_timeout':
    '平台身份获取或解析请求超时，请检查部署主机的 Chrome 和网络后重新解析。',
  'context_changed:identity_account_conflict':
    '元宝账号在解析期间发生变化，请确认账号后重新解析。',
  'login_required:credential_missing':
    '缺少平台登录状态，请在部署主机的 Chrome 完成对应平台登录后重新解析。',
  'identity_unavailable:identity_cookie_rules_unverified':
    '该平台的身份规则尚未接通，当前无法解析；可导入已有本地视频。',
  'runtime_unavailable:browser_not_implemented':
    '该平台的解析尚未接通，当前无法解析；可导入已有本地视频。',
  'runtime_unavailable:browser_parser_missing':
    '该平台的解析尚未接通，当前无法解析；可导入已有本地视频。',
};

export function localizedErrorMessage(
  code: string | null | undefined,
  causeCode?: unknown,
): string | undefined {
  if (!code) return undefined;
  const cause =
    typeof causeCode === 'string'
      ? localizedFailureCauses[`${code}:${causeCode}`]
      : undefined;
  return cause ?? localizedErrorMessages[code];
}

export function statusErrorMessage(status: number): string {
  const message = statusErrorMessages[status];
  if (message) return message;
  if (status >= 500) return '服务处理失败，请稍后重试。';
  return '请求未能完成，请检查后重试。';
}

const statusErrorMessages: Record<number, string> = {
  0: '网络连接失败，请检查网络后重试。',
  400: '请求内容有误，请检查后重试。',
  401: '登录状态已失效，请重新登录。',
  403: '当前账号没有执行此操作的权限。',
  404: '请求的内容不存在或已失效。',
  409: '当前状态已发生变化，请刷新后重试。',
  413: '提交内容超过大小限制，请缩小后重试。',
  422: '提交内容不符合要求，请检查后重试。',
  429: '操作过于频繁，请稍后再试。',
  500: '服务处理失败，请稍后重试。',
  502: '上游服务暂时不可用，请稍后重试。',
  503: '服务暂时不可用，请稍后重试。',
  504: '请求处理超时，请稍后重试。',
};
