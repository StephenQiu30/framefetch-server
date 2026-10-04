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

_OUTPUT_LANGUAGES = {"en-US", "zh-CN"}


class CreateDocumentAnalysis:
    def __init__(
        self,
        *,
        repository: AnalysisRepository,
        fingerprinter: RequestFingerprinter,
        now: Callable[[], datetime],
        new_id: Callable[[], UUID],
        max_attempts: int,
        skill_catalog: AnalysisSkillCatalog,
        enabled: bool = False,
        max_source_characters: int = 120_000,
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
        self._max_source_characters = max_source_characters

    async def __call__(
        self,
        document_id: UUID,
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
        output_language = validate_label(output_language, maximum=35)
        if output_language not in _OUTPUT_LANGUAGES:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        custom_prompt = validate_custom_prompt(custom_prompt)
        input_kind = AnalysisInputKind.SCREENPLAY
        skill = self._skill_catalog.resolve(skill_id, input_kind)
        if skill is None:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        source = await self._repository.get_document_for_analysis(document_id)
        if source is None or source.owner_hash != owner_hash:
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.NOT_FOUND)
        if source.status != "ready" or source.normalized_status != "ready":
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.ARTIFACT_NOT_READY
            )
        sha256 = validate_sha256(source.text_sha256 or "")
        if source.normalized_sha256 != sha256:
            raise AnalysisApplicationError(
                AnalysisApplicationErrorCode.ARTIFACT_NOT_READY
            )
        if (
            source.character_count is not None
            and source.character_count > self._max_source_characters
            and skill.view.result_contract.value == "structured-report"
        ):
            raise AnalysisApplicationError(AnalysisApplicationErrorCode.INVALID_REQUEST)
        instructions_sha256 = validate_sha256(skill.instructions_sha256)
        contract = skill.view.result_contract
        fingerprint = self._fingerprinter.fingerprint(
            "analysis",
            str(source.id),
            sha256,
            input_kind.value,
            contract.value,
            skill_id,
            instructions_sha256,
            output_language,
            custom_prompt or "",
        )
        command = AnalysisCreate(
            id=self._new_id(),
            run_id=self._new_id(),
            artifact_id=None,
            document_id=source.id,
            owner_hash=owner_hash,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            input_sha256=sha256,
            skill_id=skill_id,
            skill_instructions=skill.instructions,
            skill_instructions_sha256=instructions_sha256,
            output_language=output_language,
            custom_prompt=custom_prompt,
            max_attempts=self._max_attempts,
            outbox_event_id=self._new_id(),
            outbox_event_type="analysis.requested",
            input_kind=input_kind,
            result_contract=contract,
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
