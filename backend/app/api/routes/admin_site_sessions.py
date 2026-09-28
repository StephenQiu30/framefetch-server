"""Deployment site sessions: status, remote login in the session browser, revoke.

Request bodies here may carry what an administrator types into a login page,
so this router never records bodies and every response is ``no-store``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import get_current_admin, get_services, require_service
from app.api.responses import ApiResponseRoute
from app.core.errors import AppError
from app.integrations.site_session_admin import (
    SiteSessionAdmin,
    SiteSessionAdminError,
    jpeg_base64,
)
from app.schemas.site_sessions import (
    SiteSessionListResponse,
    SiteSessionLoginFrameResponse,
    SiteSessionLoginInputRequest,
    SiteSessionLoginResponse,
    SiteSessionLoginSavedResponse,
    SiteSessionResponse,
    StartSiteSessionLoginRequest,
)
from app.services.auth.models import CurrentUser

router = APIRouter(
    route_class=ApiResponseRoute, prefix="/admin/site-sessions", tags=["admin"]
)
Admin = Annotated[CurrentUser, Depends(get_current_admin)]

_ERRORS = {
    "site_session_invalid": (422, "不能为该站点登录：请填写公网站点或 https 链接。"),
    "site_session_login_busy": (409, "该站点已有登录进行中，或同时登录的站点过多。"),
    "site_session_login_incomplete": (409, "尚未检测到登录成功，请在画面中完成登录。"),
    "site_session_login_not_found": (404, "登录已结束或超时，请重新开始。"),
    "site_session_login_rejected": (
        409,
        "页面已登录，但没有得到可长期使用的登录 Cookie，请重新登录并勾选保持登录。",
    ),
    "site_session_not_found": (404, "该站点没有可撤销的会话。"),
    "site_session_unavailable": (503, "会话浏览器暂时不可用，请稍后重试。"),
}


def _admin_of(request: Request) -> SiteSessionAdmin:
    return require_service(get_services(request).site_session_admin, "site session")


def _error(exc: SiteSessionAdminError) -> AppError:
    status_code, detail = _ERRORS.get(exc.code, _ERRORS["site_session_unavailable"])
    code = exc.code if exc.code in _ERRORS else "site_session_unavailable"
    return AppError(status=status_code, code=code, title="Site session", detail=detail)


@router.get(
    "",
    operation_id="listAdminSiteSessions",
    response_model=SiteSessionListResponse,
    summary="列出全部已知平台与已登记站点的会话状态",
)
async def list_site_sessions(
    _admin: Admin, request: Request, response: Response
) -> SiteSessionListResponse:
    response.headers["Cache-Control"] = "no-store"
    views = await _admin_of(request).list()
    return SiteSessionListResponse(
        items=tuple(
            SiteSessionResponse(
                site=view.site,
                provider_key=view.provider_key,
                state=view.state,
                seed_revision=view.seed_revision,
                verified_at=view.verified_at,
                refreshed_at=view.refreshed_at,
                last_error_code=view.last_error_code,
                proves_login=view.proves_login,
            )
            for view in views
        )
    )


@router.post(
    "/logins",
    operation_id="startAdminSiteSessionLogin",
    response_model=SiteSessionLoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="在会话浏览器中打开站点登录页",
)
async def start_site_session_login(
    _admin: Admin,
    request: Request,
    response: Response,
    body: StartSiteSessionLoginRequest,
) -> SiteSessionLoginResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        login = await _admin_of(request).start(body.target)
    except SiteSessionAdminError as exc:
        raise _error(exc) from exc
    return SiteSessionLoginResponse(
        login_id=login.login_id,
        site=login.site,
        width=login.width,
        height=login.height,
    )


@router.get(
    "/logins/{login_id}/frame",
    operation_id="getAdminSiteSessionLoginFrame",
    response_model=SiteSessionLoginFrameResponse,
    summary="读取登录画面与是否已登录",
)
async def get_site_session_login_frame(
    _admin: Admin, request: Request, response: Response, login_id: str
) -> SiteSessionLoginFrameResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        frame = await _admin_of(request).frame(login_id)
    except SiteSessionAdminError as exc:
        raise _error(exc) from exc
    return SiteSessionLoginFrameResponse(
        image=jpeg_base64(frame), host=frame.host, logged_in=frame.logged_in
    )


@router.post(
    "/logins/{login_id}/input",
    operation_id="sendAdminSiteSessionLoginInput",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="把点击、拖动、滚轮与键盘输入转发到登录画面",
)
async def send_site_session_login_input(
    _admin: Admin,
    request: Request,
    login_id: str,
    body: SiteSessionLoginInputRequest,
) -> Response:
    try:
        await _admin_of(request).act(
            login_id,
            [item.model_dump(exclude_none=True) for item in body.actions],
        )
    except SiteSessionAdminError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/logins/{login_id}/finish",
    operation_id="finishAdminSiteSessionLogin",
    response_model=SiteSessionLoginSavedResponse,
    summary="保存已完成的登录为站点会话",
)
async def finish_site_session_login(
    _admin: Admin, request: Request, login_id: str
) -> SiteSessionLoginSavedResponse:
    try:
        site, revision = await _admin_of(request).finish(login_id)
    except SiteSessionAdminError as exc:
        raise _error(exc) from exc
    return SiteSessionLoginSavedResponse(site=site, seed_revision=revision)


@router.delete(
    "/logins/{login_id}",
    operation_id="cancelAdminSiteSessionLogin",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="放弃登录",
)
async def cancel_site_session_login(
    _admin: Admin, request: Request, login_id: str
) -> Response:
    try:
        await _admin_of(request).cancel(login_id)
    except SiteSessionAdminError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{site}",
    operation_id="revokeAdminSiteSession",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="撤销站点会话",
)
async def revoke_site_session(_admin: Admin, request: Request, site: str) -> Response:
    try:
        await _admin_of(request).revoke(site)
    except SiteSessionAdminError as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
