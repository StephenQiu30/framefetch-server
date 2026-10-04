// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** List Creation Materials GET /api/creation/materials */
export async function listCreationMaterials(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listCreationMaterialsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseTupleCreationMaterialResponse_____>(
    "/api/creation/materials",
    {
      method: "GET",
      params: {
        // limit has a default value: 50
        limit: "50",
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** Create Creation Material POST /api/creation/materials */
export async function createCreationMaterial(
  body: API.CreationMaterialCreateRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseCreationMaterialResponse_>(
    "/api/creation/materials",
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

/** Get Creation Material GET /api/creation/materials/${param0} */
export async function getCreationMaterial(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getCreationMaterialParams,
  options?: RequestOptions
) {
  const { material_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationMaterialResponse_>(
    `/api/creation/materials/${param0}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Confirm Creation Material POST /api/creation/materials/${param0}/confirm */
export async function confirmCreationMaterial(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.confirmCreationMaterialParams,
  body: API.CreationConfirmRequest,
  options?: RequestOptions
) {
  const { material_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationMaterialResponse_>(
    `/api/creation/materials/${param0}/confirm`,
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

/** Get Creation Material Image GET /api/creation/materials/${param0}/image */
export async function getCreationMaterialImage(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getCreationMaterialImageParams,
  options?: RequestOptions
) {
  const { material_id: param0, ...queryParams } = params;
  return request<Blob>(`/api/creation/materials/${param0}/image`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** List Creation Material Revisions GET /api/creation/materials/${param0}/revisions */
export async function listCreationMaterialRevisions(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listCreationMaterialRevisionsParams,
  options?: RequestOptions
) {
  const { material_id: param0, ...queryParams } = params;
  return request<API.ApiResponseTupleCreationRevisionResponse_____>(
    `/api/creation/materials/${param0}/revisions`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Save Creation Material Revision POST /api/creation/materials/${param0}/revisions */
export async function saveCreationMaterialRevision(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.saveCreationMaterialRevisionParams,
  body: API.CreationRevisionSaveRequest,
  options?: RequestOptions
) {
  const { material_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationMaterialResponse_>(
    `/api/creation/materials/${param0}/revisions`,
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

/** Get Creation Document Source GET /api/creation/materials/${param0}/source */
export async function getCreationDocumentSource(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getCreationDocumentSourceParams,
  options?: RequestOptions
) {
  const { material_id: param0, ...queryParams } = params;
  return request<Blob>(`/api/creation/materials/${param0}/source`, {
    method: "GET",
    params: { ...queryParams },
    ...(options || {}),
  });
}

/** List Creation Projects GET /api/creation/projects */
export async function listCreationProjects(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listCreationProjectsParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseTupleCreationProjectResponse_____>(
    "/api/creation/projects",
    {
      method: "GET",
      params: {
        // limit has a default value: 50
        limit: "50",
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** Create Creation Project POST /api/creation/projects */
export async function createCreationProject(
  body: API.CreationProjectCreateRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseCreationProjectResponse_>(
    "/api/creation/projects",
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

/** List Creation Skills GET /api/creation/skills */
export async function listCreationSkills(options?: RequestOptions) {
  return request<API.ApiResponseTupleCreationSkillResponse_____>(
    "/api/creation/skills",
    {
      method: "GET",
      ...(options || {}),
    }
  );
}

/** List Creation Tasks GET /api/creation/tasks */
export async function listCreationTasks(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listCreationTasksParams,
  options?: RequestOptions
) {
  return request<API.ApiResponseTupleCreationTaskResponse_____>(
    "/api/creation/tasks",
    {
      method: "GET",
      params: {
        // limit has a default value: 50
        limit: "50",
        ...params,
      },
      ...(options || {}),
    }
  );
}

/** Create Creation Task POST /api/creation/tasks */
export async function createCreationTask(
  body: API.CreationTaskCreateRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseCreationTaskResponse_>("/api/creation/tasks", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** Get Creation Task GET /api/creation/tasks/${param0} */
export async function getCreationTask(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.getCreationTaskParams,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationTaskResponse_>(
    `/api/creation/tasks/${param0}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Retry Creation Task POST /api/creation/tasks/${param0}/attempts */
export async function retryCreationTask(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.retryCreationTaskParams,
  body: API.CreationRetryRequest,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationTaskResponse_>(
    `/api/creation/tasks/${param0}/attempts`,
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

/** Cancel Creation Task POST /api/creation/tasks/${param0}/cancel */
export async function cancelCreationTask(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.cancelCreationTaskParams,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationTaskResponse_>(
    `/api/creation/tasks/${param0}/cancel`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Confirm Creation Task POST /api/creation/tasks/${param0}/confirm */
export async function confirmCreationTask(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.confirmCreationTaskParams,
  body: API.CreationConfirmRequest,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationTaskResponse_>(
    `/api/creation/tasks/${param0}/confirm`,
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

/** List Creation Task Revisions GET /api/creation/tasks/${param0}/revisions */
export async function listCreationTaskRevisions(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.listCreationTaskRevisionsParams,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<API.ApiResponseTupleCreationRevisionResponse_____>(
    `/api/creation/tasks/${param0}/revisions`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Save Creation Task Revision POST /api/creation/tasks/${param0}/revisions */
export async function saveCreationTaskRevision(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.saveCreationTaskRevisionParams,
  body: API.CreationRevisionSaveRequest,
  options?: RequestOptions
) {
  const { task_id: param0, ...queryParams } = params;
  return request<API.ApiResponseCreationTaskResponse_>(
    `/api/creation/tasks/${param0}/revisions`,
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

/** Export Creation Revision GET /api/creation/tasks/${param0}/revisions/${param1}/export/${param2} */
export async function exportCreationRevision(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.exportCreationRevisionParams,
  options?: RequestOptions
) {
  const {
    task_id: param0,
    revision_id: param1,
    format: param2,
    ...queryParams
  } = params;
  return request<Blob>(
    `/api/creation/tasks/${param0}/revisions/${param1}/export/${param2}`,
    {
      method: "GET",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}
