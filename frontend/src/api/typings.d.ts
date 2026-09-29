declare namespace API {
  type AccessDecision =
    | "downloadable"
    | "playback_only"
    | "export_required"
    | "blocked"
    | "unsupported";

  type activateAiProviderProfileParams = {
    provider_key: string;
  };

  type AiModelListResponse = {
    /** Items */
    items: AiModelResponse[];
  };

  type AiModelResponse = {
    /** Id */
    id: string;
    /** Name */
    name: string;
    /** Context Length */
    context_length: number;
    /** Input Modalities */
    input_modalities: string[];
    /** Output Modalities */
    output_modalities: string[];
    /** Supported Parameters */
    supported_parameters: string[];
  };

  type AiProviderAuthMode = "host_login" | "api_key";

  type AiProviderEngine =
    | "codex"
    | "claude"
    | "deepseek"
    | "openrouter"
    | "openai";

  type AiProviderProfileListResponse = {
    /** Items */
    items: AiProviderProfileResponse[];
    /** Agent Available */
    agent_available: boolean;
  };

  type AiProviderProfileResponse = {
    /** Key */
    key: string;
    /** Display Name */
    display_name: string;
    engine: AiProviderEngine;
    auth_mode: AiProviderAuthMode;
    /** Base Url */
    base_url: string | null;
    /** Model */
    model: string;
    /** Credential Configured */
    credential_configured: boolean;
    /** Is Active */
    is_active: boolean;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
  };

  type AnalysisErrorCode =
    | "cancelled"
    | "analysis_cli_unavailable"
    | "analysis_cli_unsupported"
    | "analysis_cli_not_authenticated"
    | "analysis_sandbox_unavailable"
    | "analysis_media_invalid"
    | "analysis_provider_rate_limited"
    | "analysis_provider_usage_limited"
    | "analysis_cli_timeout"
    | "analysis_cli_failed"
    | "invalid_model_output"
    | "analysis_resource_limit"
    | "input_artifact_unavailable"
    | "analysis_input_expired"
    | "screenplay_output_incomplete"
    | "analysis_report_unavailable"
    | "internal_error"
    | "worker_lost";

  type AnalysisInputKind = "video" | "screenplay";

  type AnalysisMediaResponse = {
    /** Duration Ms */
    duration_ms: number;
    /** Container */
    container: string;
    /** Size Bytes */
    size_bytes: number;
  };

  type AnalysisReportArtifactResponse = {
    /** Format */
    format: string;
    /** Media Type */
    media_type: string;
    /** Size Bytes */
    size_bytes: number;
    /** Sha256 */
    sha256: string;
  };

  type AnalysisReportResponse = {
    /** Id */
    id: string;
    status: AnalysisReportStatus;
    /** Renderer Version */
    renderer_version: string;
    /** Content Sha256 */
    content_sha256: string;
    /** Published At */
    published_at: string | null;
    /** Artifacts */
    artifacts: AnalysisReportArtifactResponse[];
  };

  type AnalysisReportStatus =
    | "validated"
    | "publishing"
    | "available"
    | "publish_failed"
    | "delete_pending"
    | "deleted";

  type AnalysisRequest = {
    /** Skill Id 分析 Skill 的稳定标识，由分析 Skill 清单接口提供。 */
    skill_id: string;
    /** Output Language 分析结果使用的 BCP 47 语言标签。 */
    output_language: string;
    /** Custom Prompt 用户可编辑的分析要求，仅影响观察重点和表达，不能覆盖工具、安全边界或结果结构。 */
    custom_prompt?: string | null;
  };

  type AnalysisResponse = {
    /** Id */
    id: string;
    /** Run Id */
    run_id: string;
    /** Run No */
    run_no: number;
    /** Run Trigger */
    run_trigger: string;
    /** Version */
    version: number;
    /** Skill Id */
    skill_id: string;
    /** Output Language */
    output_language: string;
    input_kind: AnalysisInputKind;
    result_contract: AnalysisResultContract;
    status: AnalysisStatus;
    stage: AnalysisStage | null;
    /** Progress */
    progress: number;
    /** Attempt */
    attempt: number;
    error_code: AnalysisErrorCode | null;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Finished At */
    finished_at: string | null;
    /** Result */
    result:
      | VideoAnalysisResultResponse
      | VideoArticleResultResponse
      | ScreenplayAnalysisResultResponse
      | ScreenplayRewriteResultResponse
      | null;
    /** Report Markdown */
    report_markdown: string | null;
    /** Current Report Id */
    current_report_id: string | null;
    report: AnalysisReportResponse | null;
  };

  type AnalysisResultContract =
    | "video-visual-analysis"
    | "video-article"
    | "screenplay-analysis"
    | "screenplay-rewrite";

  type AnalysisRunHistoryPageResponse = {
    /** Items */
    items: AnalysisRunHistoryResponse[];
    /** Next Before Run No */
    next_before_run_no: number | null;
  };

  type AnalysisRunHistoryResponse = {
    /** Id */
    id: string;
    /** Run No */
    run_no: number;
    /** Trigger */
    trigger: string;
    status: AnalysisStatus;
    /** Created At */
    created_at: string;
    /** Started At */
    started_at: string | null;
    /** Finished At */
    finished_at: string | null;
    error_code: AnalysisErrorCode | null;
  };

  type AnalysisSkillResponse = {
    /** Id */
    id: string;
    /** Display Name */
    display_name: string;
    /** Description */
    description: string;
    /** Default Prompt */
    default_prompt: string;
    /** Input Kinds */
    input_kinds: AnalysisInputKind[];
    result_contract: AnalysisResultContract;
  };

  type AnalysisStage = "preparing" | "analyzing" | "validating" | "publishing";

  type AnalysisStatus =
    | "queued"
    | "running"
    | "retry_wait"
    | "succeeded"
    | "failed"
    | "cancelled";

  type ApiResponseAiModelListResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: AiModelListResponse;
  };

  type ApiResponseAiProviderProfileListResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: AiProviderProfileListResponse;
  };

  type ApiResponseAiProviderProfileResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: AiProviderProfileResponse;
  };

  type ApiResponseAnalysisResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: AnalysisResponse;
  };

  type ApiResponseAnalysisRunHistoryPageResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: AnalysisRunHistoryPageResponse;
  };

  type ApiResponseDocumentDetailResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DocumentDetailResponse;
  };

  type ApiResponseDocumentImportResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DocumentImportResponse;
  };

  type ApiResponseDocumentPageResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DocumentPageResponse;
  };

  type ApiResponseDocumentUploadSessionResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DocumentUploadSessionResponse;
  };

  type ApiResponseDownloadAnalyticsResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DownloadAnalyticsResponse;
  };

  type ApiResponseDownloadHistoryResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DownloadHistoryResponse;
  };

  type ApiResponseDownloadResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DownloadResponse;
  };

  type ApiResponseDownloadUrlResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: DownloadUrlResponse;
  };

  type ApiResponseEngineCatalogResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: EngineCatalogResponse;
  };

  type ApiResponseHistoryRecordPageResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: HistoryRecordPageResponse;
  };

  type ApiResponseInspectionResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: InspectionResponse;
  };

  type ApiResponseIntentHistoryResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: IntentHistoryResponse;
  };

  type ApiResponseIntentResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: IntentResponse;
  };

  type ApiResponseManagedUserListResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: ManagedUserListResponse;
  };

  type ApiResponseManagedUserResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: ManagedUserResponse;
  };

  type ApiResponseMediaImportResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: MediaImportResponse;
  };

  type ApiResponseMediaUploadSessionResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: MediaUploadSessionResponse;
  };

  type ApiResponseOperationLogPageResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: OperationLogPageResponse;
  };

  type ApiResponseProviderCatalogEntryResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: ProviderCatalogEntryResponse;
  };

  type ApiResponseProviderCatalogListResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: ProviderCatalogListResponse;
  };

  type ApiResponseProviderListResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: ProviderListResponse;
  };

  type ApiResponseProviderRuntimeListResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: ProviderRuntimeListResponse;
  };

  type ApiResponseRegistrationCodeResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: RegistrationCodeResponse;
  };

  type ApiResponseRegistrationCodeVerificationResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: RegistrationCodeVerificationResponse;
  };

  type ApiResponseSourceDiscoveryResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: SourceDiscoveryResponse;
  };

  type ApiResponseStorageCleanupResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: StorageCleanupResponse;
  };

  type ApiResponseStoredFileListResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: StoredFileListResponse;
  };

  type ApiResponseTupleAnalysisSkillResponse_____ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** Data 成功时为业务数据，错误时为 null。 */
    data: AnalysisSkillResponse[];
  };

  type ApiResponseUnionAnalysisResponse_NoneType_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: AnalysisResponse | null;
  };

  type ApiResponseUnionVideoAnalysisHistoryRecordResponse_ScreenplayAnalysisHistoryRecordResponse_ =
    {
      /** 稳定的业务结果码。 */
      code: ErrorCode;
      /** Message 安全的结果说明。 */
      message: string;
      /** Data 成功时为业务数据，错误时为 null。 */
      data:
        | VideoAnalysisHistoryRecordResponse
        | ScreenplayAnalysisHistoryRecordResponse;
    };

  type ApiResponseUserResponse_ = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** 成功时为业务数据，错误时为 null。 */
    data: UserResponse;
  };

  type AudioCodecFamily = "none" | "aac" | "opus" | "vorbis" | "other";

  type cancelAnalysisParams = {
    analysis_id: string;
  };

  type cancelDocumentImportParams = {
    document_id: string;
  };

  type cancelDownloadIntentParams = {
    intent_id: string;
  };

  type cancelDownloadParams = {
    job_id: string;
  };

  type CompatibilityProfile = "balanced" | "quality" | "smallest";

  type completeDocumentImportParams = {
    document_id: string;
  };

  type CompleteDocumentImportRequest = {
    /** Parts */
    parts: CompletedPartRequest[];
  };

  type CompletedPartRequest = {
    /** Part Number */
    part_number: number;
    /** Etag */
    etag: string;
  };

  type completeMediaImportParams = {
    resource_id: string;
  };

  type CompleteMediaImportRequest = {
    /** Parts */
    parts: CompletedPartRequest[];
  };

  type ContainerPreference = "mp4" | "webm" | "source";

  type CreateAiProviderProfileRequest = {
    /** Key */
    key: string;
    /** Display Name */
    display_name: string;
    engine: AiProviderEngine;
    auth_mode: AiProviderAuthMode;
    /** Base Url */
    base_url?: string | null;
    /** Model */
    model: string;
    /** Api Key */
    api_key?: string | null;
  };

  type createAnalysisParams = {
    download_id: string;
  };

  type createDocumentAnalysisParams = {
    document_id: string;
  };

  type createDocumentUploadSessionParams = {
    document_id: string;
  };

  type createMediaUploadSessionParams = {
    resource_id: string;
  };

  type CreateProviderCatalogEntryRequest = {
    /** Key */
    key: string;
    /** Display Name */
    display_name: string;
    /** Sort Order */
    sort_order: number;
    /** Is Visible */
    is_visible?: boolean;
  };

  type DeclaredOrigin = "user_file" | "wechat_channels";

  type deleteAiProviderProfileParams = {
    provider_key: string;
  };

  type deleteAnalysisParams = {
    analysis_id: string;
  };

  type deleteDocumentParams = {
    document_id: string;
  };

  type deleteDownloadParams = {
    job_id: string;
  };

  type deleteProviderCatalogEntryParams = {
    provider_key: string;
  };

  type deleteStoredFileParams = {
    category: "video" | "screenplay" | "analysis_report";
    file_id: string;
  };

  type deleteUserParams = {
    user_id: string;
  };

  type DiscoveredItemInspectionSource = {
    /** Kind */
    kind: "discovered_item";
    /** Discovery Id */
    discovery_id: string;
    /** Item Ref */
    item_ref: string;
  };

  type DiscoveryDecisionHint = "candidate" | "export_required" | "unsupported";

  type DiscoveryItemKind =
    | "official_account_native"
    | "tencent_video"
    | "wechat_channels"
    | "unknown";

  type DiscoveryItemStatus = "ready" | "identity_unverified";

  type DiscoveryStatus = "ready" | "empty";

  type DocumentDetailResponse = {
    /** Id */
    id: string;
    /** Title */
    title: string;
    /** Original Filename */
    original_filename: string;
    source_format: DocumentSourceFormat;
    /** Declared Size Bytes */
    declared_size_bytes: number;
    status: ImportStatus;
    /** Attempt */
    attempt: number;
    error_code: ImportErrorCode | null;
    /** Version */
    version: number;
    /** Detected Language */
    detected_language: string | null;
    /** Scene Count */
    scene_count: number | null;
    /** Character Count */
    character_count: number | null;
    /** Quality Warnings */
    quality_warnings: string[];
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Finished At */
    finished_at: string | null;
    /** Preview */
    preview: string | null;
    /** Preview Truncated */
    preview_truncated: boolean;
    parse_summary: DocumentParseSummaryResponse | null;
  };

  type DocumentImportRequest = {
    /** File Name */
    file_name: string;
    source_format: DocumentSourceFormat;
    /** Declared Size Bytes */
    declared_size_bytes: number;
    /** Declared Sha256 */
    declared_sha256: string;
    /** Rights Accepted */
    rights_accepted: boolean;
  };

  type DocumentImportResponse = {
    /** Id */
    id: string;
    source_format: DocumentSourceFormat;
    /** Original Filename */
    original_filename: string;
    /** Declared Size Bytes */
    declared_size_bytes: number;
    status: ImportStatus;
    /** Attempt */
    attempt: number;
    error_code: ImportErrorCode | null;
    /** Version */
    version: number;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Finished At */
    finished_at: string | null;
  };

  type DocumentPageResponse = {
    /** Items */
    items: DocumentResponse[];
    /** Page */
    page: number;
    /** Page Size */
    page_size: number;
    /** Total */
    total: number;
  };

  type DocumentParseHistoryRecordResponse = {
    /** Updated At */
    updated_at: string;
    status_group: HistoryStatusGroup;
    source_availability: HistoryAvailability;
    result_availability: HistoryAvailability;
    /** Record Type */
    record_type: "document_parse";
    /** Id */
    id: string;
    /** Document Id */
    document_id: string;
    /** Title */
    title: string;
    status: ImportStatus;
    /** Source Format */
    source_format: string;
    /** Created At */
    created_at: string;
    /** Version */
    version: number;
    /** Error Code */
    error_code: string | null;
  };

  type DocumentParseSummaryResponse = {
    /** Page Count */
    page_count: number | null;
    /** Paragraph Count */
    paragraph_count: number;
    /** Heading Count */
    heading_count: number;
    /** List Item Count */
    list_item_count: number;
    /** Table Count */
    table_count: number;
    /** Dialogue Block Count */
    dialogue_block_count: number;
  };

  type DocumentResponse = {
    /** Id */
    id: string;
    /** Title */
    title: string;
    /** Original Filename */
    original_filename: string;
    source_format: DocumentSourceFormat;
    /** Declared Size Bytes */
    declared_size_bytes: number;
    status: ImportStatus;
    /** Attempt */
    attempt: number;
    error_code: ImportErrorCode | null;
    /** Version */
    version: number;
    /** Detected Language */
    detected_language: string | null;
    /** Scene Count */
    scene_count: number | null;
    /** Character Count */
    character_count: number | null;
    /** Quality Warnings */
    quality_warnings: string[];
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Finished At */
    finished_at: string | null;
  };

  type DocumentSourceFormat = "docx" | "pdf" | "txt" | "markdown" | "fountain";

  type DocumentUploadSessionResponse = {
    /** Resource Id */
    resource_id: string;
    /** Attempt */
    attempt: number;
    /** Part Size Bytes */
    part_size_bytes: number;
    /** Part Count */
    part_count: number;
    /** Max Concurrency */
    max_concurrency: number;
    /** Expires At */
    expires_at: string;
    /** Parts */
    parts: UploadPartResponse[];
  };

  type DownloadAnalyticsDailyResponse = {
    /** Date */
    date: string;
    /** Total */
    total: number;
    /** Succeeded */
    succeeded: number;
    /** Failed */
    failed: number;
    /** Cancelled */
    cancelled: number;
  };

  type DownloadAnalyticsResponse = {
    /** Period Days */
    period_days: number;
    /** Start */
    start: string;
    /** End */
    end: string;
    summary: DownloadAnalyticsSummaryResponse;
    /** Daily */
    daily: DownloadAnalyticsDailyResponse[];
    /** Sources */
    sources: DownloadAnalyticsSourceResponse[];
  };

  type DownloadAnalyticsSourceResponse = {
    /** Source Key */
    source_key: string;
    /** Source Name */
    source_name: string;
    /** Total */
    total: number;
    /** Succeeded */
    succeeded: number;
    /** Failed */
    failed: number;
    /** Cancelled */
    cancelled: number;
    /** Active */
    active: number;
    /** Unique Users */
    unique_users: number;
    /** Downloaded Bytes */
    downloaded_bytes: number;
    /** Success Rate */
    success_rate: number;
  };

  type DownloadAnalyticsSummaryResponse = {
    /** Total */
    total: number;
    /** Succeeded */
    succeeded: number;
    /** Failed */
    failed: number;
    /** Cancelled */
    cancelled: number;
    /** Active */
    active: number;
    /** Unique Users */
    unique_users: number;
    /** Downloaded Bytes */
    downloaded_bytes: number;
    /** Average Duration Seconds */
    average_duration_seconds: number;
    /** Success Rate */
    success_rate: number;
  };

  type DownloadErrorCode =
    | "cancelled"
    | "download_timeout"
    | "format_unavailable"
    | "inspection_timeout"
    | "internal_error"
    | "media_validation_failed"
    | "output_limit_exceeded"
    | "provider_access_policy_not_allowed"
    | "provider_auth_required"
    | "provider_content_restricted"
    | "provider_drm_protected"
    | "provider_geo_restricted"
    | "provider_guest_context_required"
    | "provider_link_unavailable"
    | "provider_media_unsupported"
    | "provider_rate_limited"
    | "provider_session_expired"
    | "provider_session_not_ready"
    | "provider_temporarily_unavailable"
    | "provider_unsupported"
    | "provider_verification_failed"
    | "storage_unavailable"
    | "temp_space_exhausted"
    | "transcode_required"
    | "unsupported_source"
    | "worker_lost";

  type downloadFileParams = {
    job_id: string;
    preview?: boolean;
  };

  type DownloadHistoryItemResponse = {
    /** Id */
    id: string;
    /** Title */
    title: string;
    /** Thumbnail Url */
    thumbnail_url: string | null;
    /** Format Name */
    format_name: string;
    status: DownloadStatus;
    /** Progress */
    progress: number;
    error_code: DownloadErrorCode | null;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Finished At */
    finished_at: string | null;
    /** File Available */
    file_available: boolean;
    source_kind: DownloadSourceKind;
    /** Source Label */
    source_label: string;
  };

  type DownloadHistoryResponse = {
    /** Items */
    items: DownloadHistoryItemResponse[];
    /** Page */
    page: number;
    /** Page Size */
    page_size: number;
    /** Total */
    total: number;
    summary: DownloadHistorySummaryResponse;
  };

  type DownloadHistorySummaryResponse = {
    /** Total */
    total: number;
    /** Succeeded */
    succeeded: number;
    /** Active */
    active: number;
    /** Failed */
    failed: number;
  };

  type DownloadRequest = {
    /** Inspection Id 仍在有效期内的媒体解析资源 ID。 */
    inspection_id: string;
    /** Format Id 解析结果中选择的语义下载格式 ID。 */
    format_id: string;
  };

  type DownloadResponse = {
    /** Id */
    id: string;
    /** Inspection Id */
    inspection_id: string | null;
    /** Format Id */
    format_id: string | null;
    source_kind: DownloadSourceKind;
    /** Source Label */
    source_label: string;
    status: DownloadStatus;
    stage: DownloadStage | null;
    /** Progress */
    progress: number;
    /** Attempt */
    attempt: number;
    /** Version */
    version: number;
    error_code: DownloadErrorCode | null;
    /** Error Message */
    error_message: string | null;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Finished At */
    finished_at: string | null;
    /** File Available */
    file_available: boolean;
    /** Title */
    title: string | null;
    /** Extractor Key */
    extractor_key: string | null;
    /** Duration Seconds */
    duration_seconds: number | null;
    media_kind: MediaKind;
    /** Asset Count */
    asset_count: number;
    /** Thumbnail Url */
    thumbnail_url: string | null;
    format: SemanticPlanResponse | null;
  };

  type DownloadSourceKind = "remote_provider" | "browser_import";

  type DownloadStage =
    | "revalidating"
    | "downloading"
    | "remuxing"
    | "verifying"
    | "uploading";

  type DownloadStatus =
    | "queued"
    | "running"
    | "retry_wait"
    | "succeeded"
    | "failed"
    | "cancelled";

  type DownloadUrlResponse = {
    /** Url */
    url: string;
    /** Expires At */
    expires_at: string;
    /** Filename */
    filename: string;
  };

  type DynamicRange = "sdr" | "hdr";

  type EmailPasswordRequest = {
    /** Email */
    email: string;
    /** Password */
    password: string;
  };

  type EngineCandidateResponse = {
    /** Key */
    key: string;
    /** Name */
    name: string;
    /** Upstream Working */
    upstream_working: boolean;
  };

  type EngineCatalogResponse = {
    /** Scope */
    scope?: "anonymous_runner";
    /** Engine Version */
    engine_version: string;
    /** Engine Commit */
    engine_commit?: string | null;
    /** Expected Engine Commit */
    expected_engine_commit: string;
    /** Pin Matches */
    pin_matches: boolean;
    /** Bundled Plugins Sha256 */
    bundled_plugins_sha256: string;
    /** Pot Provider Version */
    pot_provider_version?: string | null;
    /** Manifest Id */
    manifest_id: string;
    /** Candidates */
    candidates: EngineCandidateResponse[];
  };

  type EntitlementState =
    | "public_free"
    | "official_download_grant"
    | "restricted"
    | "unknown";

  type ErrorCode =
    | "active_ai_provider_delete"
    | "active_task_quota_exceeded"
    | "admin_bootstrap_required"
    | "ai_model_catalog_unavailable"
    | "ai_provider_conflict"
    | "ai_provider_not_found"
    | "analysis_already_active"
    | "analysis_artifact_unavailable"
    | "analysis_budget_exceeded"
    | "analysis_report_not_ready"
    | "analysis_report_unavailable"
    | "analysis_retry_limited"
    | "analysis_skill_outdated"
    | "analysis_unavailable"
    | "article_access_restricted"
    | "article_discovery_failed"
    | "artifact_not_ready"
    | "daily_byte_quota_exceeded"
    | "daily_task_quota_exceeded"
    | "download_not_ready"
    | "duration_limit_exceeded"
    | "email_already_registered"
    | "email_send_failed"
    | "email_unavailable"
    | "forbidden"
    | "format_unavailable"
    | "http_error"
    | "idempotency_conflict"
    | "import_disabled"
    | "import_size_mismatch"
    | "import_storage_unavailable"
    | "inspection_failed"
    | "inspection_timeout"
    | "internal_error"
    | "invalid_ai_provider_profile"
    | "invalid_credentials"
    | "invalid_model_output"
    | "invalid_provider_catalog_entry"
    | "invalid_request"
    | "invalid_state"
    | "invalid_url"
    | "invalid_username"
    | "invalid_verification_code"
    | "last_admin_change"
    | "job_conflict"
    | "method_not_allowed"
    | "metrics_unavailable"
    | "not_found"
    | "ok"
    | "provider_access_policy_not_allowed"
    | "provider_auth_required"
    | "provider_catalog_conflict"
    | "provider_catalog_not_found"
    | "provider_configuration_missing"
    | "provider_guest_context_required"
    | "provider_content_restricted"
    | "provider_drm_protected"
    | "provider_failure"
    | "provider_geo_restricted"
    | "provider_link_unavailable"
    | "provider_media_unsupported"
    | "provider_rate_limited"
    | "provider_session_expired"
    | "provider_session_not_ready"
    | "provider_temporarily_unavailable"
    | "provider_unsupported"
    | "provider_verification_failed"
    | "rate_limited"
    | "rate_limiter_unavailable"
    | "refresh_in_progress"
    | "request_timeout"
    | "request_too_large"
    | "reserved_ai_provider_mutation"
    | "resource_expired"
    | "self_admin_change"
    | "service_unavailable"
    | "storage_quota_exceeded"
    | "storage_file_in_use"
    | "storage_unavailable"
    | "unauthenticated"
    | "upload_incomplete"
    | "upload_session_expired"
    | "user_not_found"
    | "username_already_registered"
    | "verification_rate_limited";

  type ErrorResponse = {
    /** 稳定的业务结果码。 */
    code: ErrorCode;
    /** Message 安全的结果说明。 */
    message: string;
    /** Data */
    data: null;
  };

  type EvidenceSummaryResponse = {
    /** Text */
    text: string;
    /** Evidence Shot Ids */
    evidence_shot_ids: string[];
  };

  type ExecutionMode =
    | "provider_runner"
    | "article_native"
    | "official_connector"
    | "verified_import";

  type exportAnalysisMarkdownParams = {
    analysis_id: string;
  };

  type exportAnalysisReportParams = {
    analysis_id: string;
  };

  type findDownloadIntentParams = {
    idempotency_key: string;
  };

  type FormatResponse = {
    /** Id */
    id: string;
    /** Display Name */
    display_name: string;
    plan: SemanticPlanResponse | null;
  };

  type FpsBucket = "fps_30" | "fps_60" | "above_60";

  type getAnalysisHistoryRecordParams = {
    analysis_id: string;
  };

  type getAnalysisParams = {
    analysis_id: string;
  };

  type getDocumentImportParams = {
    document_id: string;
  };

  type getDownloadAnalyticsParams = {
    days?: number;
  };

  type getDownloadHistoryParams = {
    page?: number;
    page_size?: number;
    status?: DownloadStatus | null;
    search?: string | null;
  };

  type getDownloadIntentParams = {
    intent_id: string;
  };

  type getDownloadParams = {
    job_id: string;
  };

  type getDownloadThumbnailParams = {
    job_id: string;
  };

  type getInspectionParams = {
    inspection_id: string;
  };

  type getInspectionThumbnailParams = {
    inspection_id: string;
  };

  type getLatestDocumentAnalysisParams = {
    document_id: string;
  };

  type getLatestDownloadAnalysisParams = {
    download_id: string;
  };

  type getMediaImportParams = {
    resource_id: string;
  };

  type getSourceDiscoveryParams = {
    discovery_id: string;
  };

  type HighlightResponse = {
    /** Id */
    id: string;
    /** Title */
    title: string;
    /** Description */
    description: string;
    /** Score */
    score: number;
    /** Reason */
    reason: string;
    /** Start Ms */
    start_ms: number;
    /** End Ms */
    end_ms: number;
    /** Evidence Shot Ids */
    evidence_shot_ids: string[];
  };

  type HistoryAvailability =
    | "available"
    | "unavailable"
    | "unknown"
    | "not_applicable";

  type HistoryRecordCursorResponse = {
    /** Created At */
    created_at: string;
    record_type: HistoryRecordKind;
    /** Id */
    id: string;
  };

  type HistoryRecordKind =
    | "parse"
    | "video_analysis"
    | "document_parse"
    | "screenplay_analysis";

  type HistoryRecordPageResponse = {
    /** Items */
    items: (
      | ParseHistoryRecordResponse
      | VideoAnalysisHistoryRecordResponse
      | ScreenplayAnalysisHistoryRecordResponse
      | DocumentParseHistoryRecordResponse
    )[];
    next_cursor: HistoryRecordCursorResponse | null;
  };

  type HistoryStatusGroup =
    | "processing"
    | "action_required"
    | "completed"
    | "failed"
    | "cancelled"
    | "expired";

  type IdentityState = "verified" | "ambiguous" | "unknown";

  type ImportErrorCode =
    | "import_storage_unavailable"
    | "upload_session_expired"
    | "upload_incomplete"
    | "import_size_mismatch"
    | "import_sha256_mismatch"
    | "video_import_invalid"
    | "document_format_unsupported"
    | "document_encrypted"
    | "document_archive_unsafe"
    | "document_text_unavailable"
    | "document_structure_invalid";

  type ImportSourceFormat =
    | "mp4"
    | "docx"
    | "pdf"
    | "txt"
    | "markdown"
    | "fountain";

  type ImportStatus =
    | "uploading"
    | "verifying"
    | "ready"
    | "failed"
    | "cancelled"
    | "expired";

  type InspectionRequest = {
    /** Source */
    source: PublicUrlInspectionSource | DiscoveredItemInspectionSource;
  };

  type InspectionResponse = {
    /** Id */
    id: string;
    /** Extractor Key */
    extractor_key: string;
    /** Provider Media Id */
    provider_media_id: string;
    /** Title */
    title: string;
    /** Duration Seconds */
    duration_seconds: number;
    media_kind: MediaKind;
    /** Asset Count */
    asset_count: number;
    /** Thumbnail Url */
    thumbnail_url: string | null;
    /** Expires At */
    expires_at: string;
    /** Formats */
    formats: FormatResponse[];
    source_origin: SourceOrigin;
    execution_mode: ExecutionMode;
    access_decision: AccessDecision;
    entitlement_state: EntitlementState;
    identity_state: IdentityState;
    protection_state: ProtectionState;
    rights_basis: RightsBasis | null;
    /** Restriction Reason */
    restriction_reason: string | null;
    /** User Action */
    user_action: string | null;
    access_policy_id: ProviderAccessPolicy | null;
  };

  type IntentHistoryItemResponse = {
    /** Id */
    id: string;
    /** Version */
    version: number;
    status: IntentStatus;
    /** Reason Code */
    reason_code: string | null;
    /** Next Action */
    next_action?: "none";
    /** Retry At */
    retry_at: string | null;
    /** Deadline */
    deadline: string;
    /** Inspection Id */
    inspection_id: string | null;
    /** Job Id */
    job_id: string | null;
    /** Created At */
    created_at: string;
    /** Title */
    title: string | null;
  };

  type IntentHistoryResponse = {
    /** Items */
    items: IntentHistoryItemResponse[];
    /** Next Cursor */
    next_cursor: string | null;
  };

  type IntentRequest = {
    /** Input 公开媒体地址或包含唯一媒体地址的分享文案。 */
    input: string;
  };

  type IntentResponse = {
    /** Id */
    id: string;
    /** Version */
    version: number;
    status: IntentStatus;
    /** Reason Code */
    reason_code: string | null;
    /** Next Action */
    next_action?: "none";
    /** Retry At */
    retry_at: string | null;
    /** Deadline */
    deadline: string;
    /** Inspection Id */
    inspection_id: string | null;
    /** Job Id */
    job_id: string | null;
  };

  type IntentStatus =
    | "queued"
    | "preparing"
    | "resolving"
    | "retry_wait"
    | "action_required"
    | "ready"
    | "handed_off"
    | "cancelled"
    | "expired"
    | "failed";

  type issueDownloadUrlParams = {
    job_id: string;
    preview?: boolean;
  };

  type listAnalysisRunsParams = {
    analysis_id: string;
    before_run_no?: number | null;
    limit?: number;
  };

  type listAnalysisSkillsParams = {
    input_kind: AnalysisInputKind;
  };

  type listDocumentsParams = {
    page?: number;
    page_size?: number;
  };

  type listDownloadIntentsParams = {
    before?: string | null;
    limit?: number;
  };

  type listHistoryRecordsParams = {
    before_created_at?: string | null;
    record_type?: HistoryRecordKind[] | null;
    status_group?: HistoryStatusGroup | null;
    created_from?: string | null;
    created_to?: string | null;
    q?: string | null;
    skill_id?: string | null;
    result_contract?: AnalysisResultContract | null;
    document_id?: string | null;
    download_id?: string | null;
    before_record_type?: HistoryRecordKind | null;
    before_id?: string | null;
    limit?: number;
  };

  type listOperationLogsParams = {
    page?: number;
    page_size?: number;
    q?: string | null;
    outcome?: "started" | "succeeded" | "failed" | null;
    created_from?: string | null;
    created_to?: string | null;
    admin_only?: boolean;
    source?: "request" | "task" | null;
  };

  type listStoredFilesParams = {
    page?: number;
    page_size?: number;
  };

  type listUsersParams = {
    page?: number;
    page_size?: number;
    search?: string | null;
    role?: UserRole | null;
    is_active?: boolean | null;
  };

  type LivenessResponse = {
    status: LivenessStatus;
  };

  type LivenessStatus = "ok";

  type ManagedUserListResponse = {
    /** Items */
    items: ManagedUserResponse[];
    /** Page */
    page: number;
    /** Page Size */
    page_size: number;
    /** Total */
    total: number;
  };

  type ManagedUserResponse = {
    /** Id */
    id: string;
    /** Username */
    username: string;
    /** Email */
    email: string;
    role: UserRole;
    /** Is Active */
    is_active: boolean;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    quota: UserQuotaSettings;
  };

  type MediaImportRequest = {
    /** File Name */
    file_name: string;
    /** Declared Size Bytes */
    declared_size_bytes: number;
    /** Declared Sha256 */
    declared_sha256: string;
    /** Rights Accepted */
    rights_accepted: boolean;
    declared_origin?: DeclaredOrigin;
  };

  type MediaImportResponse = {
    /** Id */
    id: string;
    /** Download Id */
    download_id: string;
    source_format: ImportSourceFormat;
    /** Display Name */
    display_name: string;
    /** Declared Size Bytes */
    declared_size_bytes: number;
    status: ImportStatus;
    /** Attempt */
    attempt: number;
    error_code: ImportErrorCode | null;
    /** Version */
    version: number;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Finished At */
    finished_at: string | null;
    declared_origin: DeclaredOrigin;
  };

  type MediaKind = "video" | "image_gallery" | "video_collection";

  type MediaUploadSessionResponse = {
    /** Resource Id */
    resource_id: string;
    /** Attempt */
    attempt: number;
    /** Part Size Bytes */
    part_size_bytes: number;
    /** Part Count */
    part_count: number;
    /** Max Concurrency */
    max_concurrency: number;
    /** Expires At */
    expires_at: string;
    /** Parts */
    parts: UploadPartResponse[];
  };

  type NativeLogoutRequest = {
    /** Refresh Token */
    refresh_token: string;
  };

  type NativeRefreshRequest = {
    /** Refresh Token */
    refresh_token: string;
  };

  type NativeSessionResponse = {
    user: UserResponse;
    /** Access Token */
    access_token: string;
    /** Refresh Token */
    refresh_token: string;
    /** Token Type */
    token_type: "Bearer";
    /** Access Expires At */
    access_expires_at: string;
    /** Refresh Expires At */
    refresh_expires_at: string;
  };

  type OperationLogPageResponse = {
    /** Items */
    items: OperationLogResponse[];
    /** Page */
    page: number;
    /** Page Size */
    page_size: number;
    /** Total */
    total: number;
  };

  type OperationLogResponse = {
    /** Id */
    id: string;
    /** Created At */
    created_at: string;
    /** Finished At */
    finished_at: string | null;
    /** Actor Id */
    actor_id: string | null;
    /** Actor Name */
    actor_name: string | null;
    /** Operation */
    operation: string;
    /** Description */
    description: string;
    /** Method */
    method: string;
    /** Route */
    route: string;
    /** Resource Id */
    resource_id: string | null;
    /** Resource Key */
    resource_key: string | null;
    /** Outcome */
    outcome: "started" | "succeeded" | "failed";
    /** Source */
    source: "request" | "task";
    /** Task State */
    task_state: string | null;
    /** Status Code */
    status_code: number | null;
    /** Error Code */
    error_code: string | null;
  };

  type ParseHistoryRecordResponse = {
    /** Updated At */
    updated_at: string;
    status_group: HistoryStatusGroup;
    source_availability: HistoryAvailability;
    result_availability: HistoryAvailability;
    /** Id */
    id: string;
    /** Version */
    version: number;
    status: IntentStatus;
    /** Reason Code */
    reason_code: string | null;
    /** Next Action */
    next_action?: "none";
    /** Retry At */
    retry_at: string | null;
    /** Deadline */
    deadline: string;
    /** Inspection Id */
    inspection_id: string | null;
    /** Job Id */
    job_id: string | null;
    /** Created At */
    created_at: string;
    /** Title */
    title: string | null;
    /** Record Type */
    record_type: "parse";
  };

  type ProblemDetails = {
    /** Type 稳定的服务错误类型 URI。 */
    type: string;
    /** Title 面向调用方的简短错误标题。 */
    title: string;
    /** Status HTTP 状态码。 */
    status: number;
    /** Detail 不包含敏感信息的错误说明。 */
    detail: string;
    /** Code 供客户端分支处理的稳定错误码。 */
    code: string;
    /** Instance 产生错误的请求路径。 */
    instance: string;
  };

  type ProductionAdviceResponse = {
    /** Summary */
    summary: string;
    /** Priority Shot Ids */
    priority_shot_ids: string[];
    /** Recommended Extensions */
    recommended_extensions: string[];
  };

  type ProtectionState = "clear" | "encrypted" | "drm" | "unknown";

  type ProviderAccessMode = "anonymous" | "guest" | "operator_managed";

  type ProviderAccessPolicy =
    | "public"
    | "public_session"
    | "operator_public"
    | "personal_entitled";

  type ProviderAccessPolicyResponse = {
    id: ProviderAccessPolicy;
    /** Configured */
    configured: boolean;
  };

  type ProviderAccessState =
    | "public_probe"
    | "public_ready"
    | "authorization_required"
    | "operator_probe"
    | "operator_ready"
    | "degraded"
    | "blocked"
    | "disabled"
    | "unsupported";

  type ProviderCapability =
    | "single_video"
    | "short_video"
    | "clip_or_vod"
    | "audio_video_split"
    | "subtitles"
    | "image_or_carousel"
    | "live"
    | "playlist";

  type ProviderCatalogEntryResponse = {
    /** Key */
    key: string;
    /** Display Name */
    display_name: string;
    /** Sort Order */
    sort_order: number;
    /** Is Visible */
    is_visible: boolean;
    /** System Registered */
    system_registered: boolean;
    system_status: ProviderSupportStatus;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
  };

  type ProviderCatalogListResponse = {
    /** Items */
    items: ProviderCatalogEntryResponse[];
  };

  type ProviderEvidenceState = "missing" | "stale" | "fresh";

  type ProviderListResponse = {
    /** Items */
    items: ProviderStatusResponse[];
  };

  type ProviderRuntimeListResponse = {
    /** Items */
    items: ProviderRuntimeResponse[];
    /** Snapshot Max Age Seconds */
    snapshot_max_age_seconds?: number;
  };

  type ProviderRuntimeResponse = {
    /** Login State */
    login_state: "not_required" | "signed_in" | "unavailable";
    /** Session Site */
    session_site?: string | null;
    /** Provider Key */
    provider_key: string;
    access_policy_id: ProviderAccessPolicy | null;
    /** Route Configured */
    route_configured: boolean;
    /** Context Available */
    context_available: boolean;
    /** Profile Version */
    profile_version: string | null;
    /** Engine Commit */
    engine_commit: string | null;
    /** Source State */
    source_state:
      | "not_required"
      | "revision_observed"
      | "not_observed"
      | "unknown";
    evidence_state: ProviderEvidenceState;
    /** Last Media Verified At */
    last_media_verified_at: string | null;
    /** User Action */
    user_action: string | null;
    /** Route Retry At */
    route_retry_at?: string | null;
  };

  type ProviderStatusResponse = {
    /** Key */
    key: string;
    /** Display Name */
    display_name: string;
    /** Registered */
    registered: boolean;
    /** Extractor Exists */
    extractor_exists: boolean;
    /** Capabilities */
    capabilities: ProviderCapability[];
    /** Access Modes */
    access_modes: ProviderAccessMode[];
    access_state: ProviderAccessState;
    status: ProviderSupportStatus;
    /** Last Checked At */
    last_checked_at: string | null;
    /** Last Check Succeeded */
    last_check_succeeded: boolean | null;
    /** Download Supported */
    download_supported: boolean;
    /** Download Available */
    download_available: boolean;
    /** Last Media Verified At */
    last_media_verified_at: string | null;
    /** Last Verified At */
    last_verified_at: string | null;
    /** User Action */
    user_action: string | null;
    /** Access Policies */
    access_policies: ProviderAccessPolicyResponse[];
    default_access_policy_id: ProviderAccessPolicy | null;
    evidence_state: ProviderEvidenceState;
    /** Hosts */
    hosts: string[];
    /** Host Suffixes */
    host_suffixes: string[];
    /** Route Retry At */
    route_retry_at?: string | null;
  };

  type ProviderSupportStatus =
    | "unknown"
    | "verified"
    | "degraded"
    | "access_required"
    | "rate_limited"
    | "blocked"
    | "disabled"
    | "unsupported";

  type PublicUrlInspectionSource = {
    /** Kind */
    kind: "public_url";
    /** Url 用户有权处理的公开、非 DRM HTTP(S) 媒体地址。 */
    url: string;
    /** 显式选择平台允许的访问策略；省略时使用平台固定默认策略，不按端点存在性切换。 */
    access_policy_id?: ProviderAccessPolicy | null;
  };

  type ReadinessResponse = {
    status: ReadinessStatus;
    /** Service */
    service: "api";
  };

  type ReadinessStatus = "ok" | "unavailable";

  type refreshDownloadIntentParams = {
    intent_id: string;
  };

  type RegisterRequest = {
    /** Email */
    email: string;
    /** Password */
    password: string;
    /** Verification Code */
    verification_code: string;
    /** Username 唯一用户名，支持字母、数字、中文以及 _-. 字符。 */
    username: string;
  };

  type RegistrationCodeRequest = {
    /** Email */
    email: string;
  };

  type RegistrationCodeResponse = {
    /** Email Sent */
    email_sent?: boolean;
    /** Expires In Seconds */
    expires_in_seconds?: number;
    /** Retry After Seconds */
    retry_after_seconds?: number;
  };

  type RegistrationCodeVerificationRequest = {
    /** Email */
    email: string;
    /** Verification Code */
    verification_code: string;
  };

  type RegistrationCodeVerificationResponse = {
    /** Verified */
    verified?: boolean;
  };

  type retryAnalysisParams = {
    analysis_id: string;
  };

  type retryDownloadParams = {
    job_id: string;
  };

  type RightsBasis =
    | "public_access"
    | "owner_authorized_export"
    | "official_asset_grant"
    | "user_provided";

  type ScreenplayAnalysisHistoryRecordResponse = {
    /** Updated At */
    updated_at: string;
    status_group: HistoryStatusGroup;
    source_availability: HistoryAvailability;
    result_availability: HistoryAvailability;
    /** Record Type */
    record_type: "screenplay_analysis";
    /** Document Id */
    document_id: string | null;
    /** Artifact Id */
    artifact_id: string | null;
    /** Output Language */
    output_language: string;
    result_contract: AnalysisResultContract;
    /** Current Run No */
    current_run_no: number;
    /** Cancel Requested At */
    cancel_requested_at: string | null;
    /** Version */
    version: number;
    /** Allowed Actions */
    allowed_actions: ("view" | "retry" | "cancel" | "delete")[];
    /** Action Unavailable Reason */
    action_unavailable_reason: string | null;
    /** Id */
    id: string;
    /** Download Id */
    download_id: string | null;
    /** Title */
    title: string;
    /** Skill Id */
    skill_id: string;
    /** Created At */
    created_at: string;
    status: AnalysisStatus;
    /** Progress */
    progress: number;
    stage: AnalysisStage | null;
    error_code: AnalysisErrorCode | null;
  };

  type ScreenplayAnalysisResultResponse = {
    /** Kind */
    kind: "screenplay_analysis";
    /** Language */
    language: string;
    /** Title */
    title: string;
    /** Logline */
    logline: string;
    /** Synopsis */
    synopsis: string;
    structure: ScreenplayStructureResponse;
    /** Characters */
    characters: ScreenplayCharacterResponse[];
    /** Scenes */
    scenes: ScreenplaySceneResponse[];
    /** Dialogue Findings */
    dialogue_findings: ScreenplayFindingResponse[];
    /** Strengths */
    strengths: ScreenplayFindingResponse[];
    /** Priority Revisions */
    priority_revisions: ScreenplayFindingResponse[];
  };

  type ScreenplayCharacterResponse = {
    /** Id */
    id: string;
    /** Name */
    name: string;
    /** Goal */
    goal: string;
    /** Conflict */
    conflict: string;
    /** Arc */
    arc: string;
  };

  type ScreenplayFindingResponse = {
    /** Id */
    id: string;
    /** Title */
    title: string;
    /** Description */
    description: string;
  };

  type ScreenplayGlossaryTermResponse = {
    /** Source */
    source: string;
    /** Target */
    target: string;
    /** Category */
    category: string;
  };

  type ScreenplayRewriteResultResponse = {
    /** Kind */
    kind: "screenplay_rewrite";
    /** Source Language */
    source_language: string;
    /** Target Language */
    target_language: string;
    /** Source Scene Count */
    source_scene_count: number;
    /** Output Scene Count */
    output_scene_count: number;
    /** Glossary */
    glossary: ScreenplayGlossaryTermResponse[];
    /** Change Summary */
    change_summary: string[];
  };

  type ScreenplaySceneResponse = {
    /** Id */
    id: string;
    /** Source Scene Id */
    source_scene_id: string;
    /** Purpose */
    purpose: string;
    /** Conflict */
    conflict: string;
    /** Turn */
    turn: string;
    /** Pacing */
    pacing: string;
    /** Findings */
    findings: string[];
  };

  type ScreenplayStructureResponse = {
    /** Acts */
    acts: ScreenplayFindingResponse[];
    /** Turning Points */
    turning_points: ScreenplayFindingResponse[];
    /** Pacing Summary */
    pacing_summary: string;
  };

  type SemanticPlanResponse = {
    /** Height */
    height: number;
    /** Width */
    width: number;
    fps_bucket: FpsBucket;
    dynamic_range: DynamicRange;
    video_codec_family: VideoCodecFamily;
    audio_codec_family: AudioCodecFamily;
    /** Audio Language */
    audio_language: string | null;
    container_preference: ContainerPreference;
    compatibility_profile: CompatibilityProfile;
  };

  type ShotResponse = {
    /** Id */
    id: string;
    /** Index */
    index: number;
    /** Start Ms */
    start_ms: number;
    /** End Ms */
    end_ms: number;
    /** Representative Frame Ms */
    representative_frame_ms: number;
    /** Description */
    description: string;
    /** Transition In */
    transition_in: string;
    /** Shot Size */
    shot_size: string;
    /** Camera Motion */
    camera_motion: string;
    /** Narrative Function */
    narrative_function: string;
    /** Highlight Score */
    highlight_score: number;
    /** Visual Tags */
    visual_tags: string[];
    /** Asset Ids */
    asset_ids: string[];
  };

  type SourceDiscoveryItemResponse = {
    /** Item Ref */
    item_ref: string;
    kind: DiscoveryItemKind;
    /** Title */
    title: string;
    /** Duration Ms */
    duration_ms: number | null;
    decision_hint: DiscoveryDecisionHint;
    status: DiscoveryItemStatus;
  };

  type SourceDiscoveryRequest = {
    /** Kind */
    kind: "wechat_official_account_article";
    /** Url */
    url: string;
  };

  type SourceDiscoveryResponse = {
    /** Id */
    id: string;
    /** Provider Key */
    provider_key: string;
    /** Title */
    title: string;
    status: DiscoveryStatus;
    /** Expires At */
    expires_at: string;
    /** Items */
    items: SourceDiscoveryItemResponse[];
  };

  type SourceOrigin =
    | "public_url"
    | "discovered_item"
    | "official_asset"
    | "verified_import";

  type StorageCleanupRequest = {
    /** Older Than Days */
    older_than_days?: number;
  };

  type StorageCleanupResponse = {
    /** Older Than Days */
    older_than_days: number;
    /** Removed Resources */
    removed_resources: number;
    /** Removed Objects */
    removed_objects: number;
    /** Freed Bytes */
    freed_bytes: number;
    /** Failed Resources */
    failed_resources: number;
  };

  type StoredFileCategory = "video" | "screenplay" | "analysis_report";

  type StoredFileListResponse = {
    /** Items */
    items: StoredFileResponse[];
    /** Page */
    page: number;
    /** Page Size */
    page_size: number;
    /** Total */
    total: number;
  };

  type StoredFileResponse = {
    /** Id */
    id: string;
    category: StoredFileCategory;
    /** Name */
    name: string;
    /** Object Count */
    object_count: number;
    /** Size Bytes */
    size_bytes: number;
    /** Created At */
    created_at: string;
  };

  type updateAiProviderProfileParams = {
    provider_key: string;
  };

  type UpdateAiProviderProfileRequest = {
    /** Display Name */
    display_name?: string | null;
    engine?: AiProviderEngine | null;
    auth_mode?: AiProviderAuthMode | null;
    /** Base Url */
    base_url?: string | null;
    /** Model */
    model?: string | null;
    /** Api Key */
    api_key?: string | null;
  };

  type UpdateProfileRequest = {
    /** Username */
    username: string;
  };

  type updateProviderCatalogEntryParams = {
    provider_key: string;
  };

  type UpdateProviderCatalogEntryRequest = {
    /** Display Name */
    display_name?: string | null;
    /** Sort Order */
    sort_order?: number | null;
    /** Is Visible */
    is_visible?: boolean | null;
  };

  type updateUserAccessParams = {
    user_id: string;
  };

  type UpdateUserAccessRequest = {
    role?: UserRole | null;
    /** Is Active */
    is_active?: boolean | null;
    quota?: UserQuotaSettings | null;
  };

  type UploadPartResponse = {
    /** Part Number */
    part_number: number;
    /** Url */
    url: string;
  };

  type UserQuotaSettings = {
    /** Exempt */
    exempt?: boolean;
    /** Max Active Per Owner */
    max_active_per_owner?: number | null;
    /** Daily Tasks */
    daily_tasks?: number | null;
    /** Daily Bytes */
    daily_bytes?: number | null;
    /** Storage Bytes */
    storage_bytes?: number | null;
    /** Daily Analysis Attempts */
    daily_analysis_attempts?: number | null;
  };

  type UserResponse = {
    /** Id */
    id: string;
    /** Username */
    username: string;
    /** Email */
    email: string;
    role: UserRole;
    /** Created At */
    created_at: string;
    /** Updated At */
    updated_at: string;
    /** Avatar Version */
    avatar_version?: string | null;
  };

  type UserRole = "admin" | "user";

  type VideoAnalysisHistoryRecordResponse = {
    /** Updated At */
    updated_at: string;
    status_group: HistoryStatusGroup;
    source_availability: HistoryAvailability;
    result_availability: HistoryAvailability;
    /** Record Type */
    record_type: "video_analysis";
    /** Document Id */
    document_id: string | null;
    /** Artifact Id */
    artifact_id: string | null;
    /** Output Language */
    output_language: string;
    result_contract: AnalysisResultContract;
    /** Current Run No */
    current_run_no: number;
    /** Cancel Requested At */
    cancel_requested_at: string | null;
    /** Version */
    version: number;
    /** Allowed Actions */
    allowed_actions: ("view" | "retry" | "cancel" | "delete")[];
    /** Action Unavailable Reason */
    action_unavailable_reason: string | null;
    /** Id */
    id: string;
    /** Download Id */
    download_id: string | null;
    /** Title */
    title: string;
    /** Skill Id */
    skill_id: string;
    /** Created At */
    created_at: string;
    status: AnalysisStatus;
    /** Progress */
    progress: number;
    stage: AnalysisStage | null;
    error_code: AnalysisErrorCode | null;
  };

  type VideoAnalysisResultResponse = {
    /** Kind */
    kind: "video_visual_analysis";
    /** Language */
    language: string;
    /** Title */
    title: string;
    summary: EvidenceSummaryResponse;
    media: AnalysisMediaResponse;
    /** Shot Count */
    shot_count: number;
    /** Shots */
    shots: ShotResponse[];
    /** Scenes */
    scenes: VideoSceneResponse[];
    /** Highlights */
    highlights: HighlightResponse[];
    /** Assets */
    assets: VisualAssetResponse[];
    production_advice: ProductionAdviceResponse;
  };

  type VideoArticleEvidenceResponse = {
    /** Start Ms */
    start_ms: number;
    /** End Ms */
    end_ms: number;
    /** Note */
    note: string;
  };

  type VideoArticleResultResponse = {
    /** Kind */
    kind: "video_article";
    /** Language */
    language: string;
    /** Title */
    title: string;
    /** Lead */
    lead: string;
    /** Sections */
    sections: VideoArticleSectionResponse[];
    /** Key Points */
    key_points: string[];
    /** Closing */
    closing: string;
    /** Limitations */
    limitations: string[];
    media: AnalysisMediaResponse;
  };

  type VideoArticleSectionResponse = {
    /** Id */
    id: string;
    /** Title */
    title: string;
    /** Body */
    body: string;
    /** Evidence */
    evidence: VideoArticleEvidenceResponse[];
  };

  type VideoCodecFamily = "h264" | "hevc" | "vp9" | "av1" | "other";

  type VideoSceneResponse = {
    /** Id */
    id: string;
    /** Index */
    index: number;
    /** Title */
    title: string;
    /** Start Ms */
    start_ms: number;
    /** End Ms */
    end_ms: number;
    /** Location */
    location: string;
    /** Description */
    description: string;
    /** Narrative Function */
    narrative_function: string;
    /** Visual Rules */
    visual_rules: string[];
    /** Continuity Risks */
    continuity_risks: string[];
    /** Evidence Shot Ids */
    evidence_shot_ids: string[];
  };

  type VisualAssetResponse = {
    /** Id */
    id: string;
    /** Type */
    type: string;
    /** Label */
    label: string;
    /** Description */
    description: string;
    /** First Seen Ms */
    first_seen_ms: number;
    /** Evidence Shot Ids */
    evidence_shot_ids: string[];
  };
}
