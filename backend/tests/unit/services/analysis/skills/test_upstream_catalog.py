from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.services.analysis.rules.enums import AnalysisInputKind
from app.services.analysis.skills.registry import BUILTIN_ANALYSIS_SKILLS
from app.services.analysis.skills.upstream_catalog import (
    RESOURCE_END,
    RESOURCE_MARKER,
    UPSTREAM_ROOT,
    UpstreamCatalog,
    frozen_packages,
)


def fixture_catalog(tmp_path: Path) -> UpstreamCatalog:
    root = tmp_path / "upstream"
    directory = root / "example"
    directory.mkdir(parents=True)
    files = {
        "LICENSE": "MIT",
        "references/full.md": "# Full\n\nStart\n\n## End\nTail\n",
    }
    hashes = {}
    for relative, text in files.items():
        path = directory / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        hashes[relative] = hashlib.sha256(text.encode()).hexdigest()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "packages": {
                    "example": {
                        "repository": "https://github.com/example/skills.git",
                        "commit": "a" * 40,
                        "license": "MIT",
                        "files": hashes,
                    }
                }
            }
        )
    )
    return UpstreamCatalog(root)


def test_all_pinned_packages_are_complete_and_byte_identical():
    catalog = UpstreamCatalog()
    assert set(catalog.packages) == {
        "reelbench",
        "ecc",
        "baoyu",
        "screenwriting",
        "drama",
    }
    assert sum(len(catalog.verify(name).files) for name in catalog.packages) == 478


@pytest.mark.parametrize("change", ["missing", "modified", "extra", "symlink"])
def test_pinned_package_changes_fail_closed(tmp_path, change):
    catalog = fixture_catalog(tmp_path)
    path = catalog.root / "example/references/full.md"
    if change == "missing":
        path.unlink()
    elif change == "modified":
        path.write_text("Changed")
    elif change == "extra":
        (path.parent / "extra.md").write_text("Unlisted")
    else:
        original = tmp_path / "outside.md"
        path.rename(original)
        path.symlink_to(original)
    with pytest.raises(ValueError):
        catalog.verify("example")


@pytest.mark.parametrize(
    "relative",
    [
        "../LICENSE",
        "/etc/passwd",
        "references/../LICENSE",
        "references\\full.md",
        "references//full.md",
    ],
)
def test_resource_paths_cannot_escape_package(tmp_path, relative):
    with pytest.raises(ValueError):
        fixture_catalog(tmp_path).read_markdown("example", relative)


def test_complete_methods_and_reference_fingerprints_enter_job_snapshot():
    skill = BUILTIN_ANALYSIS_SKILLS.get(
        "screenplay-analysis", AnalysisInputKind.SCREENPLAY
    )
    assert skill is not None
    packages = frozen_packages(skill.instructions)
    assert set(packages) == {"screenwriting", "drama"}
    catalog = UpstreamCatalog()
    for name, sha in packages.items():
        assert catalog.verify(name).fingerprint == sha
    for name in [
        "sw-story-structure",
        "sw-character-conflict",
        "sw-scene-craft",
        "sw-dialogue",
        "sw-premise-theme",
    ]:
        original = (
            UPSTREAM_ROOT
            / f"screenwriting/plugins/screenwriting/skills/{name}/SKILL.md"
        ).read_text()
        assert original in skill.instructions
    original = (UPSTREAM_ROOT / "drama/skills/short-drama-review/SKILL.md").read_text()
    assert original in skill.instructions


def test_ambiguous_and_malformed_snapshots_are_rejected():
    valid = RESOURCE_MARKER + json.dumps({"example": "a" * 64}) + RESOURCE_END
    assert frozen_packages("Historical method") == {}
    assert frozen_packages(valid) == {"example": "a" * 64}
    for malformed in [
        valid + valid,
        RESOURCE_MARKER + "{}" + RESOURCE_END,
        RESOURCE_MARKER + "{}",
    ]:
        with pytest.raises(ValueError):
            frozen_packages(malformed)
