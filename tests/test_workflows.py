import hashlib
import json

import yaml

from archon_dagu.engine import BASE, SOURCE


def test_vendor_files_match_pinned_manifest():
    manifest = json.loads((BASE / "SOURCE.json").read_text())
    assert manifest["commit"] == "72817c50dc51bb91773f71e5448bb7d387bfc8dd"
    for name, expected in manifest["hashes"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == expected, name


def test_detailed_round_has_parallel_independent_lenses():
    data = yaml.safe_load((BASE / "workflows/archon-round.yaml").read_text())
    steps = {step["id"]: step for step in data["steps"]}
    for lens in ["seams", "code", "tests", "errors", "docs"]:
        assert steps[lens]["depends"] == ["route"]
    assert set(steps["review"]["depends"]) == {"seams", "code", "tests", "errors", "docs"}


def test_generated_workflows_are_portable_and_never_merge():
    for file in (BASE / "workflows").glob("*.yaml"):
        text = file.read_text()
        assert "/workspace/" not in text
        data = yaml.safe_load(text)
        assert data["working_dir"] == "${params.project_dir}"
        assert all(step["id"] != "merge" for step in data["steps"])


def test_only_root_real_workflows_ask_for_human_input():
    for file in (BASE / "workflows").glob("*.yaml"):
        data = yaml.safe_load(file.read_text())
        tasks = [s for s in data["steps"] if s.get("action") == "human.task"]
        asks = file.stem.endswith("-real") or file.stem in {
            "plan-live",
            "triage-live",
            "investigate-live",
            "implement-live",
        }
        assert len(tasks) == (1 if asks else 0)


def test_manifest_has_canonical_file_order():
    manifest = json.loads((BASE / "SOURCE.json").read_text())
    assert list(manifest["hashes"]) == sorted(manifest["hashes"])
