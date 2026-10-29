import json
import subprocess
from types import SimpleNamespace

import pytest

from archon_dagu import engine


@pytest.mark.parametrize(
    ("review", "ci", "threads", "reason", "done"),
    [
        ({"ready": True}, "green", 0, "delivered", True),
        ({"ready": False, "action": "correct"}, "green", 0, "review_open", False),
        ({"ready": False, "action": "ask"}, "pr_caused", 0, "ask", True),
        ({"ready": False, "action": "replan"}, "green", 0, "replan", True),
        ({"ready": True}, "pr_caused", 0, "ci_pr_caused", False),
        ({"ready": True}, "other", 0, "ci_other", True),
        ({"ready": True}, "green", 1, "threads_open", False),
    ],
)
def test_round_uses_original_source(tmp_path, review, ci, threads, reason, done):
    values = {
        "implement": {"green": True, "red_cause": ""},
        "review": review,
        "ci": {"state": ci},
        "threads": {"open": threads},
    }
    result = engine.original_reduce(tmp_path, values, {})
    assert result["reason"] == reason
    assert result["done"] is done
    assert result["ready"] is (reason == "delivered")


def test_fourth_round_is_a_business_outcome(tmp_path):
    result = engine.original_reduce(
        tmp_path,
        {"implement": {"green": True}, "review": {"ready": False, "action": "correct"}},
        {"round": 3},
    )
    assert result["reason"] == "round_cap"
    assert result["done"] is True
    assert result["ready"] is False


@pytest.mark.parametrize("value", ["true", 1, None, []])
def test_control_booleans_are_not_coerced(value):
    with pytest.raises(ValueError):
        engine.validate("review", {"ready": value, "action": "none", "contract_left": []})


def test_dry_adapter_cannot_launch_a_process(tmp_path, monkeypatch):
    engine.save(tmp_path / "context.json", {"mode": "dry"})

    def forbidden(*args, **kwargs):
        pytest.fail("Dry agent/forge adapter attempted to launch a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    assert engine.invoke(tmp_path, "ci", {}, 1, {})["state"] == "green"


def test_live_transport_rejects_artifact_symlink_escape(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    outside = tmp_path / "outside.md"
    outside.write_text("not an artifact")
    artifacts.mkdir()
    (artifacts / "review").mkdir()
    (artifacts / "review/report.md").symlink_to(outside)
    engine.save(
        artifacts / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "command_config": {"commands": {"review": ["fake"]}},
        },
    )
    verdict = {
        "ready": True,
        "action": "none",
        "findings_summary": "none",
        "report": {"type": "archon_artifact", "run_id": "test", "path": "review/report.md"},
        "discoveries": [],
        "contract_left": [],
    }
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **k: SimpleNamespace(
            pid=0,
            returncode=0,
            communicate=lambda *args, **kwargs: (json.dumps(verdict), ""),
        ),
    )
    with pytest.raises(ValueError, match="symlink escapes"):
        engine.invoke(artifacts, "review", {}, 1, {})


def test_invalid_fixture_is_not_a_green_check():
    with pytest.raises(ValueError, match="invalid CI state"):
        engine.fixture_output("ci", {"ci": {"state": "pending"}})
