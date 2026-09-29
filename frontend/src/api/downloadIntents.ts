// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 按幂等键找回当前用户已提交的解析意图 GET /api/download-intents */
export async function findDownloadIntent(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.findDownloadIntentParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseIntentResponse_>("/api/download-intents", {
    method: "GET",
    params: {
      ...params,
    },
    ...(options || {}),
  });
}

/** 提交持久解析意图 POST /api/download-intents */
export async function createDownloadIntent(
  body: API.IntentRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseIntentResponse_>("/api/download-intents", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** 查询当前用户的解析意图 GET /api/download-intents/${param0} */
export async function getDownloadIntent(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getDownloadIntentParams,
  options?: RequestOptions
) {
  const { intent_id: param0, ...queryParams } = params;
  return request<API.ApiResponseIntentResponse_>(
    `/api/download-intents/${param0}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 取消当前用户的解析意图 POST /api/download-intents/${param0}/cancel */
export async function cancelDownloadIntent(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.cancelDownloadIntentParams,
  options?: RequestOptions
) {
  const { intent_id: param0, ...queryParams } = params;
  return request<API.ApiResponseIntentResponse_>(
    `/api/download-intents/${param0}/cancel`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 打开当前任务的平台专用登录浏览器 POST /api/download-intents/${param0}/login */
export async function openDownloadIntentLogin(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.openDownloadIntentLoginParams,
  body: API.IntentResumeRequest,
  options?: RequestOptions
) {
  const { intent_id: param0, ...queryParams } = params;
  return request<any>(`/api/download-intents/${param0}/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...queryParams },
    data: body,
    ...(options || {}),
  });
}

/** 在原意图与剩余预算内更新过期解析结果 POST /api/download-intents/${param0}/refresh */
export async function refreshDownloadIntent(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.refreshDownloadIntentParams,
  options?: RequestOptions
) {
  const { intent_id: param0, ...queryParams } = params;
  return request<API.ApiResponseIntentResponse_>(
    `/api/download-intents/${param0}/refresh`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 完成登录后继续原解析任务并重新验证来源 POST /api/download-intents/${param0}/resume */
export async function resumeDownloadIntent(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.resumeDownloadIntentParams,
  body: API.IntentResumeRequest,
  options?: RequestOptions
) {
  const { intent_id: param0, ...queryParams } = params;
  return request<API.ApiResponseIntentResponse_>(
    `/api/download-intents/${param0}/resume`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      params: { ...queryParams },
      data: body,
      ...(options || {}),
    }
  );
}

/** 分页查询当前用户的解析记录 GET /api/download-intents/history */
export async function listDownloadIntents(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listDownloadIntentsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseIntentHistoryResponse_>(
    "/api/download-intents/history",
    {
      method: "GET",
      params: {
        // limit has a default value: 20
        limit: "20",
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** 分页查询链接、视频 AI、剧本基础解析与剧本 AI 记录 GET /api/download-intents/history/records */
export async function listHistoryRecords(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listHistoryRecordsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseHistoryRecordPageResponse_>(
    "/api/download-intents/history/records",
    {
      method: "GET",
      params: {
        // limit has a default value: 20
        limit: "20",
        ...params,
      },
      ...(options || {}),
    }
  );
}
