"""Swagger UI and OpenAPI metadata for the public service contract."""

from typing import Any

from app.schemas.response import ErrorResponse

API_DESCRIPTION = """
统一的视频下载与 AI 分析服务接口。

- 媒体解析、下载和分析均为异步任务，请通过对应查询接口获取进度。
- 创建媒体解析、下载或分析任务时必须提供 `Idempotency-Key` 请求头。
- 本地视频通过短期 multipart 会话直传隔离区，服务端只接受 MP4 并重新验证。
- 业务接口需要先通过邮箱和密码注册或登录，会话由安全 Cookie 维护。
- 仅允许处理用户有权访问的公开、非 DRM HTTP(S) 媒体。
""".strip()

OPENAPI_TAGS: list[dict[str, Any]] = [
    {
        "name": "auth",
        "description": ("邮箱注册、登录、JWT 刷新、注销与当前用户会话。"),
    },
    {
        "name": "users",
        "description": "当前登录用户的公开账户资料。",
    },
    {
        "name": "admin",
        "description": ("管理员用户管理、全局下载分析与持久文件清理。"),
    },
    {
        "name": "system",
        "description": "进程存活与运行依赖就绪状态。",
    },
    {
        "name": "inspections",
        "description": "校验媒体地址并解析可用的语义下载格式。",
    },
    {
        "name": "download-intents",
        "description": "持久接收、查询和取消公开媒体解析意图。",
    },
    {
        "name": "source-discoveries",
        "description": ("有界发现微信公众号文章中的视频并要求用户显式选择。"),
    },
    {
        "name": "downloads",
        "description": "创建、查询、取消下载任务并签发制品地址。",
    },
    {
        "name": "media-imports",
        "description": ("创建本地 MP4、签发隔离上传会话并触发可信验证。"),
    },
    {
        "name": "providers",
        "description": "查询平台能力、访问模式和最近验证状态。",
    },
    {
        "name": "analyses",
        "description": (
            "在原视频与文档入口调用分析 Skill，并读取、取消、重试和导出报告。"
        ),
    },
    {
        "name": "workspace",
        "description": "读取工作区文档；管理员按读取时的版本保存修改。",
    },
]

SWAGGER_UI_PARAMETERS: dict[str, Any] = {
    "displayRequestDuration": True,
    "filter": True,
    "operationsSorter": "method",
    "tagsSorter": "alpha",
}

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "未登录或会话已经失效"},
    403: {"model": ErrorResponse, "description": "当前用户没有操作权限"},
    404: {
        "model": ErrorResponse,
        "description": "资源不存在、已清理或临时解析状态已过期",
    },
    409: {"model": ErrorResponse, "description": "资源状态或幂等键冲突"},
    429: {"model": ErrorResponse, "description": "请求频率超过限制"},
    422: {"model": ErrorResponse, "description": "请求参数或业务输入无效"},
    500: {"model": ErrorResponse, "description": "服务内部错误"},
    502: {"model": ErrorResponse, "description": "上游媒体或模型服务失败"},
    503: {"model": ErrorResponse, "description": "运行依赖暂时不可用"},
    504: {"model": ErrorResponse, "description": "上游操作超时"},
}
