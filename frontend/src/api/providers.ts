// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 查询平台能力状态 返回不含凭据、出口地址和 Canary 目标的能力快照。 GET /api/providers */
export async function listProviders(options?: RequestOptions) {
  return request<API.ApiResponseProviderListResponse_>("/api/providers", {
    method: "GET",
    ...(options || {}),
  });
}
