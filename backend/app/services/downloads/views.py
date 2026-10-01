from __future__ import annotations

from enum import StrEnum

from app.services.downloads.download_models import (
    ArtifactSnapshot,
    DownloadPresentationSnapshot,
    DownloadView,
    JobSnapshot,
)
from app.services.downloads.errors import ApplicationError, ApplicationErrorCode
from app.services.downloads.inspection_models import (
    FormatView,
    InspectionSnapshot,
    InspectionView,
)
from app.services.downloads.plans import plan_from_documents, public_plan
from app.services.downloads.rules.enums import (
    DownloadErrorCode,
    DownloadSourceKind,
    DownloadStage,
    DownloadStatus,
    MediaKind,
)
from app.services.downloads.rules.formats import download_plan_priority
from app.services.downloads.rules.inspection import (
    AccessDecision,
    EntitlementState,
    ExecutionMode,
    IdentityState,
    ProtectionState,
    RightsBasis,
    SourceOrigin,
)
from app.services.downloads.thumbnail import (
    safe_thumbnail_data_url,
    thumbnail_resource_url,
)
from app.services.downloads.validation import media_kind_from_metadata
from app.services.provider_types import ExecutionContext, ProviderKey


def inspection_view(snapshot: InspectionSnapshot) -> InspectionView:
    media_kind = media_kind_from_metadata(snapshot.metadata)
    try:
        formats = tuple(
            FormatView(
                id=item.id,
                display_name=item.display_name,
                plan=(
                    None
                    if media_kind
                    in {
                        MediaKind.IMAGE_GALLERY,
                        MediaKind.VIDEO_COLLECTION,
                    }
                    else public_plan(
                        plan_from_documents(item.semantic_plan, item.provider_hints)
                    )
                ),
            )
            for item in snapshot.formats
        )
    except (TypeError, ValueError) as exc:
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from exc
    # Persistence order (including random format IDs) never chooses a default.
    formats = tuple(
        sorted(
            formats,
            key=lambda item: (
                () if item.plan is None else download_plan_priority(item.plan)
            ),
        )
    )
    thumbnail_available = snapshot.thumbnail_available or (
        safe_thumbnail_data_url(snapshot.metadata.get("thumbnail_url")) is not None
    )
    return InspectionView(
        execution_context=_execution_context(snapshot.metadata),
        id=snapshot.id,
        extractor_key=snapshot.extractor_key,
        provider_media_id=snapshot.provider_media_id,
        title=snapshot.title,
        duration_seconds=snapshot.duration_seconds,
        expires_at=snapshot.expires_at,
        formats=formats,
        thumbnail_url=(
            thumbnail_resource_url(snapshot.id) if thumbnail_available else None
        ),
        source_origin=_enum_metadata(
            snapshot.metadata, "source_origin", SourceOrigin, SourceOrigin.PUBLIC_URL
        ),
        execution_mode=_enum_metadata(
            snapshot.metadata,
            "execution_mode",
            ExecutionMode,
            ExecutionMode.PROVIDER_RUNNER,
        ),
        access_decision=_enum_metadata(
            snapshot.metadata,
            "access_decision",
            AccessDecision,
            AccessDecision.DOWNLOADABLE,
        ),
        entitlement_state=_enum_metadata(
            snapshot.metadata,
            "entitlement_state",
            EntitlementState,
            EntitlementState.PUBLIC_FREE,
        ),
        identity_state=_enum_metadata(
            snapshot.metadata,
            "identity_state",
            IdentityState,
            IdentityState.VERIFIED,
        ),
        protection_state=_enum_metadata(
            snapshot.metadata,
            "protection_state",
            ProtectionState,
            ProtectionState.CLEAR,
        ),
        rights_basis=_optional_enum_metadata(
            snapshot.metadata, "rights_basis", RightsBasis, RightsBasis.PUBLIC_ACCESS
        ),
        restriction_reason=_optional_text(snapshot.metadata, "restriction_reason"),
        user_action=_optional_text(snapshot.metadata, "user_action"),
        media_kind=media_kind,
        asset_count=_asset_count(snapshot.metadata),
    )


def _enum_metadata[EnumT: StrEnum](
    metadata: dict[str, object],
    key: str,
    enum_type: type[EnumT],
    default: EnumT,
) -> EnumT:
    value = metadata.get(key)
    if value is not None and not isinstance(value, str):
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR)
    try:
        return default if value is None else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from exc


def _optional_enum_metadata[EnumT: StrEnum](
    metadata: dict[str, object],
    key: str,
    enum_type: type[EnumT],
    default: EnumT | None,
) -> EnumT | None:
    if key not in metadata:
        return default
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR)
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from exc


def _optional_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR)
    return value


def download_view(
    snapshot: JobSnapshot,
    artifact: ArtifactSnapshot | None = None,
    presentation: DownloadPresentationSnapshot | None = None,
) -> DownloadView:
    try:
        status = DownloadStatus(snapshot.status)
        source_kind = DownloadSourceKind(snapshot.source_kind)
        stage = DownloadStage(snapshot.stage) if snapshot.stage is not None else None
    except ValueError as exc:
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from exc
    try:
        error = (
            DownloadErrorCode(snapshot.error_code)
            if snapshot.error_code is not None
            else None
        )
    except ValueError:
        error = DownloadErrorCode.INTERNAL_ERROR
    format_plan = None
    media_kind = media_kind_from_metadata(snapshot.semantic_plan)
    if (
        source_kind is DownloadSourceKind.REMOTE_PROVIDER
        and media_kind is MediaKind.VIDEO
    ):
        try:
            format_plan = public_plan(plan_from_documents(snapshot.semantic_plan, {}))
        except (TypeError, ValueError) as exc:
            raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from exc
    return DownloadView(
        execution_context=snapshot.execution_context,
        id=snapshot.id,
        inspection_id=snapshot.inspection_id,
        format_id=snapshot.format_id,
        status=status,
        stage=stage,
        progress=snapshot.progress,
        attempt=snapshot.attempt,
        error_code=error,
        error_message=snapshot.error_message,
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
        finished_at=snapshot.finished_at,
        file_available=artifact is not None,
        version=snapshot.version,
        title=None if presentation is None else presentation.title,
        extractor_key=None if presentation is None else presentation.extractor_key,
        duration_seconds=(
            None if presentation is None else presentation.duration_seconds
        ),
        thumbnail_url=(
            thumbnail_resource_url(snapshot.inspection_id)
            if presentation is not None
            and presentation.thumbnail_available
            and snapshot.inspection_id is not None
            else None
        ),
        format_plan=format_plan,
        source_kind=source_kind,
        source_label=(
            (
                "用户提供的视频号来源文件"
                if snapshot.semantic_plan.get("declared_origin")
                == ProviderKey.WECHAT_CHANNELS
                else "本地视频上传"
            )
            if source_kind is DownloadSourceKind.BROWSER_IMPORT
            else (
                presentation.extractor_key if presentation is not None else "链接下载"
            )
        ),
        media_kind=media_kind,
        asset_count=_asset_count(snapshot.semantic_plan),
    )


def _asset_count(metadata: dict[str, object]) -> int:
    value = metadata.get("asset_count", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR)
    return value


def _execution_context(metadata: dict[str, object]) -> ExecutionContext | None:
    value = metadata.get("execution_context")
    if value is None:
        return None
    try:
        return ExecutionContext.from_document(value)
    except ValueError as exc:
        raise ApplicationError(ApplicationErrorCode.INTERNAL_ERROR) from exc
