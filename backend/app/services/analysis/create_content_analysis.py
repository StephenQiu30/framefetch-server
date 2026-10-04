"""Admit a content task with an immutable, task-owned set of text materials."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
    PersistenceIdempotencyConflict,
)
from app.services.analysis.models import AnalysisCreate, AnalysisJobView
from app.services.analysis.ports import (
    AnalysisRepository,
    AnalysisSkillCatalog,
    RequestFingerprinter,
)
from app.services.analysis.rules.content_document import ContentSourceSet
from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract
from app.services.analysis.validation import (
    validate_idempotency_key,
    validate_now,
    validate_owner_hash,
)
from app.services.analysis.views import analysis_job_view
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota

CONTENT_SKILL = "content-writing"


class CreateContentAnalysis:
    def __init__(
        self,
        *,
        repository: AnalysisRepository,
        fingerprinter: RequestFingerprinter,
        skill_catalog: AnalysisSkillCatalog,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        enabled: bool,
    ) -> None:
        self._repository = repository
        self._fingerprinter = fingerprinter
        self._catalog = skill_catalog
        self._now = now
        self._new_id = new_id
        self._enabled = enabled

    async def __call__(
        self,
        source: ContentSourceSet,
        output_language: str,
        owner_hash: str,
        idempotency_key: str,
        *,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> AnalysisJobView:
        if not self._enabled:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE
            )
        now = validate_now(self._now())
        owner_hash = validate_owner_hash(owner_hash)
        idempotency_key = validate_idempotency_key(idempotency_key)
        if output_language not in {"zh-CN", "en-US"}:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        skill_id = CONTENT_SKILL
        skill = self._catalog.resolve(skill_id, AnalysisInputKind.CONTENT)
        if skill is None:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        fingerprint = self._fingerprinter.fingerprint(
            "content", source.sha256, output_language, skill.instructions_sha256
        )
        command = AnalysisCreate(
            id=self._new_id(),
            run_id=self._new_id(),
            artifact_id=None,
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            input_sha256=source.sha256,
            skill_id=skill_id,
            skill_instructions=skill.instructions,
            skill_instructions_sha256=skill.instructions_sha256,
            output_language=output_language,
            custom_prompt=None,
            max_attempts=1,
            outbox_event_id=self._new_id(),
            outbox_event_type="analysis.requested",
            input_kind=AnalysisInputKind.CONTENT,
            result_contract=AnalysisResultContract.CONTENT_DOCUMENT,
            quota=quota,
            content_source=source,
        )
        try:
            saved = await self._repository.create_job_and_enqueue(command, now=now)
        except PersistenceIdempotencyConflict as error:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.IDEMPOTENCY_CONFLICT
            ) from error
        result = await self._repository.get_result(saved.job.id)
        return analysis_job_view(saved.job, result=result)
