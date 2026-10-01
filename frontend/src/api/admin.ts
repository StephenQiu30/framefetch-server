// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 查询 AI 分析 Provider GET /api/admin/ai-providers */
export async function listAiProviderProfiles(options?: RequestOptions) {
  return request<API.ApiResponseAiProviderProfileListResponse_>(
    "/api/admin/ai-providers",
    {
      method: "GET",
      ...(options || {}),
    }
  );
}

/** 新增 AI 分析 Provider POST /api/admin/ai-providers */
export async function createAiProviderProfile(
  body: API.CreateAiProviderProfileRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseAiProviderProfileResponse_>(
    "/api/admin/ai-providers",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      data: body,
      ...(options || {}),
    }
  );
}

/** 删除 AI 分析 Provider DELETE /api/admin/ai-providers/${param0} */
export async function deleteAiProviderProfile(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.deleteAiProviderProfileParams,
  options?: RequestOptions
) {
  const { provider_key: param0, ...queryParams } = params;
  return request<any>(`/api/admin/ai-providers/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 更新 AI 分析 Provider PATCH /api/admin/ai-providers/${param0} */
export async function updateAiProviderProfile(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.updateAiProviderProfileParams,
  body: API.UpdateAiProviderProfileRequest,
  options?: RequestOptions
) {
  const { provider_key: param0, ...queryParams } = params;
  return request<API.ApiResponseAiProviderProfileResponse_>(
    `/api/admin/ai-providers/${param0}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** 启用 AI 分析 Provider POST /api/admin/ai-providers/${param0}/activate */
export async function activateAiProviderProfile(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.activateAiProviderProfileParams,
  options?: RequestOptions
) {
  const { provider_key: param0, ...queryParams } = params;
  return request<API.ApiResponseAiProviderProfileResponse_>(
    `/api/admin/ai-providers/${param0}/activate`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 查询 OpenRouter 公开模型能力 GET /api/admin/ai-providers/models/openrouter */
export async function listOpenRouterModels(options?: RequestOptions) {
  return request<API.ApiResponseAiModelListResponse_>(
    "/api/admin/ai-providers/models/openrouter",
    {
      method: "GET",
      ...(options || {}),
    }
  );
}

/** 查询 AI 分析执行统计 按每次 analysis_run 的 created_at UTC 自然日统计其当前状态。

手动重试与重新分析各计一次执行；包含所属任务已软删除但数据库仍保留的
执行记录。统计不代表供应商模型请求次数，不推算 token、费用或 Provider
延迟。平均耗时只纳入有有效开始、结束时间的终态执行，包含执行内重试和
报告发布；没有有效样本时返回 null。 GET /api/admin/analyses/analytics */
export async function getAnalysisAnalytics(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getAnalysisAnalyticsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseAnalysisAnalyticsResponse_>(
    "/api/admin/analyses/analytics",
    {
      method: "GET",
      params: {
        // days has a default value: 30
        days: "30",
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** 查询下载分析 按 UTC 自然日查询管理员可见的全局下载聚合。 GET /api/admin/downloads/analytics */
export async function getDownloadAnalytics(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getDownloadAnalyticsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseDownloadAnalyticsResponse_>(
    "/api/admin/downloads/analytics",
    {
      method: "GET",
      params: {
        // days has a default value: 30
        days: "30",
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** 分页查询持久文件 GET /api/admin/files */
export async function listStoredFiles(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listStoredFilesParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseStoredFileListResponse_>("/api/admin/files", {
    method: "GET",
    params: {
      // page has a default value: 1
      page: "1",
      // page_size has a default value: 20
      page_size: "20",
      ...params,
    },
    ...(options || {}),
  });
}

/** 删除指定持久文件 DELETE /api/admin/files/${param0}/${param1} */
export async function deleteStoredFile(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.deleteStoredFileParams,
  options?: RequestOptions
) {
  const { category: param0, file_id: param1, ...queryParams } = params;
  return request<any>(`/api/admin/files/${param0}/${param1}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 手动清理指定天数前的文件 POST /api/admin/files/cleanup */
export async function cleanupStoredFiles(
  body: API.StorageCleanupRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseStorageCleanupResponse_>(
    "/api/admin/files/cleanup",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      data: body,
      ...(options || {}),
    }
  );
}

/** 查询全系统操作日志 GET /api/admin/operation-logs */
export async function listOperationLogs(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listOperationLogsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseOperationLogPageResponse_>(
    "/api/admin/operation-logs",
    {
      method: "GET",
      params: {
        // page has a default value: 1
        page: "1",
        // page_size has a default value: 10
        page_size: "10",

        ...params,
      },
      ...(options || {}),
    }
  );
}

/** 读取媒体 Runner 实际安装的引擎候选清单 GET /api/admin/provider-runtime/engine-catalog */
export async function getAdminEngineCatalog(options?: RequestOptions) {
  return request<API.ApiResponseEngineCatalogResponse_>(
    "/api/admin/provider-runtime/engine-catalog",
    {
      method: "GET",
      ...(options || {}),
    }
  );
}

/** 查询平台目录 GET /api/admin/providers */
export async function listProviderCatalogEntries(options?: RequestOptions) {
  return request<API.ApiResponseProviderCatalogListResponse_>(
    "/api/admin/providers",
    {
      method: "GET",
      ...(options || {}),
    }
  );
}

/** 新增平台目录条目 POST /api/admin/providers */
export async function createProviderCatalogEntry(
  body: API.CreateProviderCatalogEntryRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseProviderCatalogEntryResponse_>(
    "/api/admin/providers",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      data: body,
      ...(options || {}),
    }
  );
}

/** 删除平台目录条目 DELETE /api/admin/providers/${param0} */
export async function deleteProviderCatalogEntry(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.deleteProviderCatalogEntryParams,
  options?: RequestOptions
) {
  const { provider_key: param0, ...queryParams } = params;
  return request<any>(`/api/admin/providers/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 更新平台目录条目 PATCH /api/admin/providers/${param0} */
export async function updateProviderCatalogEntry(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.updateProviderCatalogEntryParams,
  body: API.UpdateProviderCatalogEntryRequest,
  options?: RequestOptions
) {
  const { provider_key: param0, ...queryParams } = params;
  return request<API.ApiResponseProviderCatalogEntryResponse_>(
    `/api/admin/providers/${param0}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** 查询用户列表 GET /api/admin/users */
export async function listUsers(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listUsersParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseManagedUserListResponse_>("/api/admin/users", {
    method: "GET",
    params: {
      // page has a default value: 1
      page: "1",
      // page_size has a default value: 20
      page_size: "20",

      ...params,
    },
    ...(options || {}),
  });
}

/** 删除用户 DELETE /api/admin/users/${param0} */
export async function deleteUser(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.deleteUserParams,
  options?: RequestOptions
) {
  const { user_id: param0, ...queryParams } = params;
  return request<any>(`/api/admin/users/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 更新用户角色与账号状态 PATCH /api/admin/users/${param0} */
export async function updateUserAccess(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.updateUserAccessParams,
  body: API.UpdateUserAccessRequest,
  options?: RequestOptions
) {
  const { user_id: param0, ...queryParams } = params;
  return request<API.ApiResponseManagedUserResponse_>(
    `/api/admin/users/${param0}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}
