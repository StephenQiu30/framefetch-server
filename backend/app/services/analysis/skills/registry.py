from __future__ import annotations

from pathlib import Path

from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.skills.loader import load_skill
from app.services.analysis.skills.models import AnalysisSkill

_ROOT = Path(__file__).resolve().parent


class AnalysisSkillRegistry:
    def __init__(self, skills: tuple[AnalysisSkill, ...]) -> None:
        if not skills:
            raise ValueError("at least one analysis skill is required")
        by_id: dict[str, AnalysisSkill] = {}
        for skill in skills:
            if skill.id in by_id:
                raise ValueError(f"duplicate analysis skill: {skill.id}")
            by_id[skill.id] = skill
        self._skills = tuple(sorted(skills, key=lambda item: (item.order, item.id)))
        self._by_id = by_id

    @classmethod
    def from_directory(cls, root: Path) -> AnalysisSkillRegistry:
        root = root.resolve(strict=True)
        paths: list[Path] = []
        for candidate in sorted(root.iterdir(), key=lambda item: item.name):
            if candidate.is_symlink():
                raise ValueError(f"analysis skill symlink is forbidden: {candidate}")
            skill_path = candidate / "SKILL.md"
            if candidate.is_dir() and skill_path.exists():
                paths.append(skill_path)
        return cls(tuple(load_skill(path) for path in paths))

    def list(self, input_kind: AnalysisInputKind) -> tuple[AnalysisSkill, ...]:
        return tuple(skill for skill in self._skills if input_kind in skill.input_kinds)

    def get(self, skill_id: str, input_kind: AnalysisInputKind) -> AnalysisSkill | None:
        skill = self._by_id.get(skill_id)
        return skill if skill is not None and input_kind in skill.input_kinds else None


BUILTIN_ANALYSIS_SKILLS = AnalysisSkillRegistry.from_directory(_ROOT)
