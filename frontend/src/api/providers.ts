// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 查询平台能力状态 返回 Registry 声明的能力与身份要求。 GET /api/providers */
export async function listProviders(options?: RequestOptions) {
  return request<API.ApiResponseProviderListResponse_>("/api/providers", {
    method: "GET",
    ...(options || {}),
  });
}
