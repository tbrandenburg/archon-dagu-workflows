import re

import yaml

from archon_dagu.engine import BASE


def test_task_and_make_expose_the_same_public_targets():
    task = yaml.safe_load((BASE / "Taskfile.yml").read_text())["tasks"]
    make = (BASE / "Makefile").read_text()
    targets = set(re.findall(r"^([a-z-]+):", make, re.MULTILINE))
    assert set(task) - {"default"} == targets - {"help"}


def test_ci_actions_are_pinned_and_read_only():
    # PyYAML's YAML 1.1 interpretation of `on` is irrelevant to the job checks.
    workflow = yaml.safe_load((BASE / ".github/workflows/ci.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert job["timeout-minutes"] <= 15
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w/-]+@[0-9a-f]{40}", step["uses"])
    assert "ci-native" in str(workflow["jobs"]["native"]["steps"])
