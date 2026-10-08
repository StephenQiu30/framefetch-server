// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 读取工作区文档 返回文档原文与 SHA-256；公开只读。 GET /api/workspace/document */
export async function getWorkspaceDocument(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getWorkspaceDocumentParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseWorkspaceDocumentResponse_>(
    "/api/workspace/document",
    {
      method: "GET",
      params: {
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** 保存工作区文档 管理员覆盖已有文档；base_sha256 与当前原文不一致时返回 409，不新建或删除文件。 PUT /api/workspace/document */
export async function updateWorkspaceDocument(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.updateWorkspaceDocumentParams,
  body: API.UpdateWorkspaceDocumentRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseWorkspaceDocumentResponse_>(
    "/api/workspace/document",
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      params: {
        ...params,
      },
      data: body,
      ...(options || {}),
    }
  );
}

/** 列出工作区文档 返回 workspace/content 下全部 Markdown 文档；公开只读。 GET /api/workspace/documents */
export async function listWorkspaceDocuments(options?: RequestOptions) {
  return request<API.ApiResponseWorkspaceDocumentListResponse_>(
    "/api/workspace/documents",
    {
      method: "GET",
      ...(options || {}),
    }
  );
}
