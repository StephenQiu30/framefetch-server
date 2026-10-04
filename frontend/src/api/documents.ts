// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 查询文档列表 GET /api/documents */
export async function listDocuments(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listDocumentsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseDocumentPageResponse_>("/api/documents", {
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

/** 创建文档导入 POST /api/documents */
export async function createDocumentImport(
  body: API.DocumentImportRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseDocumentImportResponse_>("/api/documents", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** 查询文档导入 GET /api/documents/${param0} */
export async function getDocumentImport(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getDocumentImportParams,
  options?: RequestOptions
) {
  const { document_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDocumentDetailResponse_>(
    `/api/documents/${param0}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 删除文档及其制品 DELETE /api/documents/${param0} */
export async function deleteDocument(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.deleteDocumentParams,
  options?: RequestOptions
) {
  const { document_id: param0, ...queryParams } = params;
  return request<any>(`/api/documents/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 取消文档导入 POST /api/documents/${param0}/cancel */
export async function cancelDocumentImport(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.cancelDocumentImportParams,
  options?: RequestOptions
) {
  const { document_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDocumentImportResponse_>(
    `/api/documents/${param0}/cancel`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 完成文档上传并触发验证 POST /api/documents/${param0}/complete */
export async function completeDocumentImport(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.completeDocumentImportParams,
  body: API.CompleteDocumentImportRequest,
  options?: RequestOptions
) {
  const { document_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDocumentImportResponse_>(
    `/api/documents/${param0}/complete`,
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

/** 创建或刷新文档上传会话 POST /api/documents/${param0}/upload-sessions */
export async function createDocumentUploadSession(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.createDocumentUploadSessionParams,
  options?: RequestOptions
) {
  const { document_id: param0, ...queryParams } = params;
  return request<API.ApiResponseDocumentUploadSessionResponse_>(
    `/api/documents/${param0}/upload-sessions`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}
