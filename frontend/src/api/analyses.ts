// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 查询视频分析任务 查询分析进度及经过证据校验的结果。 GET /api/analyses/${param0} */
export async function getAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getAnalysisParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseAnalysisResponse_>(`/api/analyses/${param0}`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 删除视频分析与报告 隐藏分析任务并异步清理其私有报告对象。 DELETE /api/analyses/${param0} */
export async function deleteAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.deleteAnalysisParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<any>(`/api/analyses/${param0}`, {
    method: "DELETE",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 取消视频分析任务 请求取消尚未结束的视频分析任务。 POST /api/analyses/${param0}/cancel */
export async function cancelAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.cancelAnalysisParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseAnalysisResponse_>(
    `/api/analyses/${param0}/cancel`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 读取分析来源与历史摘要 GET /api/analyses/${param0}/history-record */
export async function getAnalysisHistoryRecord(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getAnalysisHistoryRecordParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseUnionVideoAnalysisHistoryRecordResponse_ScreenplayAnalysisHistoryRecordResponse_ContentCreationHistoryRecordResponse_>(
    `/api/analyses/${param0}/history-record`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 导出视频分析报告 将已完成的结构化分析结果导出为 DOCX 报告。 GET /api/analyses/${param0}/report.docx */
export async function exportAnalysisReport(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.exportAnalysisReportParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<Blob>(`/api/analyses/${param0}/report.docx`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 导出 Markdown 视频分析报告 导出与前端预览、DOCX 转换共用的唯一 Markdown 报告。 GET /api/analyses/${param0}/report.md */
export async function exportAnalysisMarkdown(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.exportAnalysisMarkdownParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<Blob>(`/api/analyses/${param0}/report.md`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** 重试原视频分析任务 为同一分析任务创建下一执行代次，不改变任务资源 ID。

Retry 是上一运行的无参数重放；带请求体的请求按校验错误拒绝。 POST /api/analyses/${param0}/retry */
export async function retryAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.retryAnalysisParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseAnalysisResponse_>(
    `/api/analyses/${param0}/retry`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 分页读取分析运行记录 GET /api/analyses/${param0}/runs */
export async function listAnalysisRuns(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listAnalysisRunsParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseAnalysisRunHistoryPageResponse_>(
    `/api/analyses/${param0}/runs`,
    {
      method: "GET",
      params: {
        // limit has a default value: 20
        limit: "20",
        ...queryParams,
      },
      ...(options || {}),
    }
  );
}

/** 列出输入兼容的分析 Skill 按输入类型返回可选 Skill 及用户可编辑的默认提示词。 GET /api/analysis-skills */
export async function listAnalysisSkills(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listAnalysisSkillsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseTupleAnalysisSkillResponse_____>(
    "/api/analysis-skills",
    {
      method: "GET",
      params: {
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** 从文字材料创作文章、帖子或说明文档 POST /api/content/analyses */
export async function createContentAnalysis(
  body: API.ContentAnalysisRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseAnalysisResponse_>("/api/content/analyses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** 保存人工修订稿，保留原版本 POST /api/content/analyses/${param0}/revisions */
export async function reviseContent(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.reviseContentParams,
  body: API.ContentRevisionRequest,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseAnalysisResponse_>(
    `/api/content/analyses/${param0}/revisions`,
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

/** 回看本次创作的原始材料 GET /api/content/analyses/${param0}/source */
export async function getContentSource(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getContentSourceParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseContentSourceSet_>(
    `/api/content/analyses/${param0}/source`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 回看已保存的正文版本 GET /api/content/analyses/${param0}/versions */
export async function listContentVersions(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listContentVersionsParams,
  options?: RequestOptions
) {
  const { analysis_id: param0, ...queryParams } = params;
  return request<API.ApiResponseTupleContentVersion_____>(
    `/api/content/analyses/${param0}/versions`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 创建剧本分析或改写任务 基于已规范化的剧本文档创建异步分析或改写任务。 POST /api/documents/${param0}/analyses */
export async function createDocumentAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.createDocumentAnalysisParams,
  body: API.AnalysisRequest,
  options?: RequestOptions
) {
  const { document_id: param0, ...queryParams } = params;
  return request<API.ApiResponseAnalysisResponse_>(
    `/api/documents/${param0}/analyses`,
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

/** 读取文档最近的剧本分析 恢复当前用户在该剧本文档上最近创建的分析与报告。 GET /api/documents/${param0}/analysis */
export async function getLatestDocumentAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getLatestDocumentAnalysisParams,
  options?: RequestOptions
) {
  const { document_id: param0, ...queryParams } = params;
  return request<API.ApiResponseUnionAnalysisResponse_NoneType_>(
    `/api/documents/${param0}/analysis`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** 创建视频分析任务 基于已完成的下载制品创建异步 AI 分析任务。 POST /api/downloads/${param0}/analyses */
export async function createAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.createAnalysisParams,
  body: API.AnalysisRequest,
  options?: RequestOptions
) {
  const { download_id: param0, ...queryParams } = params;
  return request<API.ApiResponseAnalysisResponse_>(
    `/api/downloads/${param0}/analyses`,
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

/** 读取下载任务最近的视频分析 恢复当前用户在该下载任务上最近创建的分析与报告。 GET /api/downloads/${param0}/analysis */
export async function getLatestDownloadAnalysis(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getLatestDownloadAnalysisParams,
  options?: RequestOptions
) {
  const { download_id: param0, ...queryParams } = params;
  return request<API.ApiResponseUnionAnalysisResponse_NoneType_>(
    `/api/downloads/${param0}/analysis`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}
