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
  inspection_failed: '暂时无法读取视频信息，请检查链接后重试。',
  inspection_timeout: '读取视频信息超时，请稍后重试。',
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
  provider_auth_required:
    '该链接明确需要平台账号权限，请使用部署方提供的受控授权路线或更换公开链接。',
  provider_catalog_conflict: '相同标识的平台配置已经存在。',
  provider_catalog_not_found: '平台配置不存在或已被删除。',
  provider_content_restricted:
    '平台未提供可直接下载的公开媒体，或内容需要额外权限；请上传你拥有或已获授权的文件。',
  provider_drm_protected: '该视频受 DRM 保护，当前无法下载。',
  provider_failure: 'AI 服务未能完成分析，请稍后重试。',
  provider_geo_restricted: '该视频在当前服务区域不可用。',
  provider_guest_context_required:
    '平台公开访问环境正在自动准备，请稍后重试，无需登录或提供 Cookie。',
  provider_link_unavailable: '未找到可下载的公开视频，请复制新的公开分享链接。',
  provider_media_unsupported: '该链接不包含受支持的可下载视频，请更换链接。',
  provider_rate_limited: '平台请求过于频繁，请稍后重试。',
  provider_session_expired:
    '平台登录状态已失效，请在本机 Chrome 中重新登录该平台后重试。',
  provider_session_not_ready:
    '暂时读不到本机 Chrome 的登录状态，本次任务会在等待期限内自动重试；请确认 Chrome 登录态服务正在运行。',
  provider_configuration_missing:
    '本机 Chrome 中没有该平台的登录状态，请先在 Chrome 登录后重新解析。',
  provider_access_policy_not_allowed:
    '该来源尚未接入可验证的平台会话，当前无法解析。',
  provider_temporarily_unavailable: '平台服务暂时不可用，请稍后重试。',
  provider_unsupported: '当前暂不支持该视频平台。',
  provider_verification_failed:
    '平台要求额外验证，当前访问路线暂不可用，请稍后重试或更换公开链接。',
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
  video_import_invalid: '视频未通过 MP4 安全校验，请更换有效文件。',
};

export function localizedErrorMessage(
  code: string | null | undefined,
): string | undefined {
  return code ? localizedErrorMessages[code] : undefined;
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
