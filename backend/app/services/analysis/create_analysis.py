from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.services.analysis.errors import (
    AnalysisApplicationError,
    AnalysisApplicationErrorCode,
    PersistenceConflict,
    PersistenceIdempotencyConflict,
    PersistenceNotFound,
)
from app.services.analysis.models import AnalysisCreate, AnalysisJobView
from app.services.analysis.ports import (
    AnalysisRepository,
    AnalysisSkillCatalog,
    RequestFingerprinter,
)
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.validation import (
    validate_custom_prompt,
    validate_idempotency_key,
    validate_label,
    validate_now,
    validate_owner_hash,
    validate_sha256,
)
from app.services.analysis.views import analysis_job_view
from app.services.quotas import DEFAULT_USER_QUOTA, UserQuota


class CreateAnalysis:
    def __init__(
        self,
        *,
        repository: AnalysisRepository,
        fingerprinter: RequestFingerprinter,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        max_attempts: int,
        skill_catalog: AnalysisSkillCatalog,
        enabled: bool = True,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max attempts must be positive")
        self._repository = repository
        self._fingerprinter = fingerprinter
        self._now = now
        self._new_id = new_id
        self._max_attempts = max_attempts
        self._skill_catalog = skill_catalog
        self._enabled = enabled

    async def __call__(
        self,
        download_id: UUID,
        owner_hash: str,
        idempotency_key: str,
        skill_id: str,
        output_language: str,
        custom_prompt: str | None = None,
        *,
        quota: UserQuota = DEFAULT_USER_QUOTA,
    ) -> AnalysisJobView:
        now = validate_now(self._now())
        # Admission is durable: a temporarily unavailable consumer must not
        # turn a valid request into a lost request. Outbox/RabbitMQ and the
        # worker recovery loop own eventual delivery.
        if not self._enabled:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.SERVICE_UNAVAILABLE
            )
        owner_hash = validate_owner_hash(owner_hash)
        idempotency_key = validate_idempotency_key(idempotency_key)
        skill_id = validate_label(skill_id, maximum=128)
        input_kind = AnalysisInputKind.VIDEO
        skill = self._skill_catalog.resolve(skill_id, input_kind)
        if skill is None:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        skill_instructions = skill.instructions
        skill_instructions_sha256 = validate_sha256(skill.instructions_sha256)
        output_language = validate_label(output_language, maximum=35)
        if output_language not in {"zh-CN", "en-US"}:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        custom_prompt = validate_custom_prompt(custom_prompt)
        try:
            artifact = await self._repository.get_artifact_for_download(download_id)
        except PersistenceNotFound as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.NOT_FOUND
            ) from exc
        if artifact is None or artifact.owner_hash != owner_hash:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.NOT_FOUND)
        if artifact.download_status != "succeeded":
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.ARTIFACT_NOT_READY
            )
        sha256 = validate_sha256(artifact.sha256)
        result_contract = skill.view.result_contract
        fingerprint = self._fingerprinter.fingerprint(
            "analysis",
            str(artifact.id),
            sha256,
            input_kind.value,
            result_contract.value,
            skill_id,
            skill_instructions_sha256,
            output_language,
            custom_prompt or "",
        )
        command = AnalysisCreate(
            id=self._new_id(),
            run_id=self._new_id(),
            artifact_id=artifact.id,
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            input_sha256=sha256,
            skill_id=skill_id,
            skill_instructions=skill_instructions,
            skill_instructions_sha256=skill_instructions_sha256,
            output_language=output_language,
            custom_prompt=custom_prompt,
            max_attempts=self._max_attempts,
            outbox_event_id=self._new_id(),
            outbox_event_type="analysis.requested",
            input_kind=input_kind,
            result_contract=result_contract,
            quota=quota,
        )
        try:
            saved = await self._repository.create_job_and_enqueue(command, now=now)
        except PersistenceIdempotencyConflict as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.IDEMPOTENCY_CONFLICT
            ) from exc
        except PersistenceNotFound as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.NOT_FOUND
            ) from exc
        except PersistenceConflict as exc:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.ARTIFACT_NOT_READY
            ) from exc
        result = await self._repository.get_result(saved.job.id)
        if saved.job.status == "succeeded" and result is None:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INTERNAL_ERROR)
        return analysis_job_view(saved.job, result=result)
