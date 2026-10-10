// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 创建下载任务 根据解析结果和语义格式创建异步下载任务。 POST /api/downloads */
export async function createDownload(
  body: API.DownloadRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseDownloadResponse_>("/api/downloads", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** 查询下载任务 查询当前登录用户拥有的下载任务。 GET /api/downloads/${param0} */
export async function getDownload(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getDownloadParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDownloadResponse_>(`/api/downloads/${param0}`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 删除下载任务及其私有文件 删除当前用户的任务、下载制品、本地上传源文件与私有封面。 DELETE /api/downloads/${param0} */
export async function deleteDownload(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.deleteDownloadParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<any>(`/api/downloads/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 取消下载任务 请求取消尚未结束的下载任务。 POST /api/downloads/${param0}/cancel */
export async function cancelDownload(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.cancelDownloadParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDownloadResponse_>(
    `/api/downloads/${param0}/cancel`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 签发文件下载地址 为已完成的下载任务签发短时制品地址。 POST /api/downloads/${param0}/download-url */
export async function issueDownloadUrl(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.issueDownloadUrlParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDownloadUrlResponse_>(
    `/api/downloads/${param0}/download-url`,
    {
      method: "POST",
      params: {
        ...queryParams,
      },
      ...(options || {}),
    }
  );
}

/** 读取已完成的视频文件 Stream an owned artifact through the authenticated application origin. GET /api/downloads/${param0}/file */
export async function downloadFile(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.downloadFileParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<any>(`/api/downloads/${param0}/file`, {
    method: "GET",
    params: {
      ...queryParams,
    },
    ...(options || {}),
  });
}

/** 重试下载任务 从失败或已取消的任务创建一条新的下载任务。 POST /api/downloads/${param0}/retry */
export async function retryDownload(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.retryDownloadParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDownloadResponse_>(
    `/api/downloads/${param0}/retry`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 读取下载任务封面 读取当前用户本地导入视频生成的私有首帧封面。 GET /api/downloads/${param0}/thumbnail */
export async function getDownloadThumbnail(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getDownloadThumbnailParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<Blob>(`/api/downloads/${param0}/thumbnail`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** List Tasks GET /api/downloads/${param0}/watermarks */
export async function listWatermarkTasks(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listWatermarkTasksParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<API.ApiResponseWatermarkListResponse_>(
    `/api/downloads/${param0}/watermarks`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Create Task POST /api/downloads/${param0}/watermarks */
export async function createWatermarkTask(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.createWatermarkTaskParams,
  options?: RequestOptions
) {
  const { job_id: param0, ...queryParams } = params;
  return request<API.ApiResponseWatermarkTaskResponse_>(
    `/api/downloads/${param0}/watermarks`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 查询下载历史 查询当前登录用户的下载历史。 GET /api/downloads/history */
export async function getDownloadHistory(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getDownloadHistoryParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseDownloadHistoryResponse_>(
    "/api/downloads/history",
    {
      method: "GET",
      params: {
        // page has a default value: 1
        page: "1",
        // page_size has a default value: 20
        page_size: "20",

        ...params,
      },
      ...(options || {}),
    }
  );
}

/** Cancel Task DELETE /api/watermarks/${param0} */
export async function cancelWatermarkTask(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.cancelWatermarkTaskParams,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<any>(`/api/watermarks/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** Get File GET /api/watermarks/${param0}/file */
export async function getWatermarkFile(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getWatermarkFileParams,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<any>(`/api/watermarks/${param0}/file`, {
    method: "GET",
    params: {
      ...queryParams,
    },
    ...(options || {}),
  });
}
