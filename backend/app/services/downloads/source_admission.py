"""Fail-closed routing for sources that must never reach the generic runner."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.services.downloads.rules.inspection import (
    AccessDecision,
    EntitlementState,
    ExecutionMode,
    IdentityState,
    ProtectionState,
    RightsBasis,
    SourceOrigin,
)
from app.services.provider_types import ProviderKey
from app.services.source_discoveries.url_admission import selected_article_source

_ARTICLE_PATH = re.compile(r"/s/[A-Za-z0-9_-]{6,256}")
_ARTICLE_QUERY_KEYS = frozenset({"__biz", "mid", "idx", "sn", "chksm", "scene"})
_CHANNELS_PATH = re.compile(r"/sph/[A-Za-z0-9_-]{4,256}/?")
_QQVIDEO_PAGE = re.compile(r"/x/page/([A-Za-z0-9_-]{4,64})\.html")
_QQVIDEO_COVER = re.compile(
    r"/x/cover/[A-Za-z0-9_-]{4,128}/([A-Za-z0-9_-]{4,64})\.html"
)


@dataclass(frozen=True, slots=True)
class RestrictedSourceAdmission:
    provider_key: str
    provider_media_id: str
    title: str
    source_origin: SourceOrigin
    execution_mode: ExecutionMode
    access_decision: AccessDecision
    entitlement_state: EntitlementState
    identity_state: IdentityState
    protection_state: ProtectionState
    rights_basis: RightsBasis | None
    restriction_reason: str
    user_action: str

    def metadata(self) -> dict[str, object]:
        return {
            "source_origin": self.source_origin.value,
            "execution_mode": self.execution_mode.value,
            "access_decision": self.access_decision.value,
            "entitlement_state": self.entitlement_state.value,
            "identity_state": self.identity_state.value,
            "protection_state": self.protection_state.value,
            "rights_basis": (
                None if self.rights_basis is None else self.rights_basis.value
            ),
            "restriction_reason": self.restriction_reason,
            "user_action": self.user_action,
        }


def classify_restricted_source(url: str) -> RestrictedSourceAdmission | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    if host == "mp.weixin.qq.com":
        try:
            selected_article_source(url)
        except ValueError:
            pass
        else:
            return None
        valid = _valid_article_url(
            parsed.path, parsed.query, parsed.port, parsed.fragment
        )
        return RestrictedSourceAdmission(
            provider_key=ProviderKey.WECHAT_OFFICIAL_ACCOUNT_ARTICLE,
            provider_media_id=_opaque_source_id(url),
            title="微信公众号文章",
            source_origin=SourceOrigin.PUBLIC_URL,
            execution_mode=ExecutionMode.ARTICLE_NATIVE,
            access_decision=(
                AccessDecision.BLOCKED if valid else AccessDecision.UNSUPPORTED
            ),
            entitlement_state=EntitlementState.UNKNOWN,
            identity_state=(IdentityState.VERIFIED if valid else IdentityState.UNKNOWN),
            protection_state=ProtectionState.UNKNOWN,
            rights_basis=None,
            restriction_reason=(
                "article_discovery_required" if valid else "unsupported_article_url"
            ),
            user_action=(
                "请先发现并选择文章中的具体视频。"
                if valid
                else "仅支持公开微信公众号文章链接。"
            ),
        )
    if host == "weixin.qq.com":
        valid = (
            parsed.port in (None, 443)
            and bool(_CHANNELS_PATH.fullmatch(parsed.path))
            and not parsed.query
            and not parsed.fragment
        )
        if valid:
            return None
        return RestrictedSourceAdmission(
            provider_key=ProviderKey.WECHAT_CHANNELS,
            provider_media_id=_opaque_source_id(url),
            title="微信视频号内容",
            source_origin=SourceOrigin.PUBLIC_URL,
            execution_mode=ExecutionMode.VERIFIED_IMPORT,
            access_decision=AccessDecision.UNSUPPORTED,
            entitlement_state=EntitlementState.UNKNOWN,
            identity_state=IdentityState.UNKNOWN,
            protection_state=ProtectionState.UNKNOWN,
            rights_basis=None,
            restriction_reason="unsupported_wechat_channels_url",
            user_action="仅支持公开的微信视频号 /sph/ 单视频分享链接。",
        )
    if host == "v.qq.com":
        media_id = (
            _qqvideo_media_id(parsed.path) if parsed.port in (None, 443) else None
        )
        if media_id is not None:
            return None
        return RestrictedSourceAdmission(
            provider_key=ProviderKey.QQVIDEO,
            provider_media_id=media_id or _opaque_source_id(url),
            title="腾讯视频内容",
            source_origin=SourceOrigin.PUBLIC_URL,
            execution_mode=ExecutionMode.PROVIDER_RUNNER,
            access_decision=AccessDecision.UNSUPPORTED,
            entitlement_state=EntitlementState.UNKNOWN,
            identity_state=IdentityState.UNKNOWN,
            protection_state=ProtectionState.UNKNOWN,
            rights_basis=None,
            restriction_reason="unsupported_qqvideo_url",
            user_action="仅支持腾讯视频单视频页面；加密内容请导入已有文件。",
        )
    return None


def _valid_article_url(path: str, query: str, port: int | None, fragment: str) -> bool:
    if port not in (None, 443) or fragment:
        return False
    if _ARTICLE_PATH.fullmatch(path):
        return not query
    if path != "/s" or not query:
        return False
    try:
        parsed_query = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    return (
        {"__biz", "mid", "idx", "sn"} <= set(parsed_query)
        and set(parsed_query) <= _ARTICLE_QUERY_KEYS
        and all(
            len(values) == 1 and values[0].strip() for values in parsed_query.values()
        )
    )


def _qqvideo_media_id(path: str) -> str | None:
    for pattern in (_QQVIDEO_PAGE, _QQVIDEO_COVER):
        matched = pattern.fullmatch(path)
        if matched is not None:
            return matched.group(1)
    return None


def _opaque_source_id(url: str) -> str:
    return f"source-{hashlib.sha256(url.encode()).hexdigest()[:24]}"
