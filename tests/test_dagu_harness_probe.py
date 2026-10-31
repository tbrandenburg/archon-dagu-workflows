"""Pinned native harness contracts use controlled effects, never provider/forge calls."""

import json
import runpy
import subprocess

import jsonschema
import pytest

from archon_dagu.engine import BASE
from archon_dagu.standalone import Run, snapshot

PROBE = runpy.run_path(str(BASE / "scripts/probe_dagu_harness.py"))


@pytest.mark.native
@pytest.mark.parametrize("case", PROBE["CASES"])
def test_actual_start_exposes_contract_gaps_and_reaps_owned_processes(tmp_path, case):
    root = tmp_path / case
    evidence = PROBE["probe"](root, case)
    assert evidence["validate_exit"] == 0
    assert evidence["source_output_certified"] is False
    assert evidence["api_calls"] is False
    assert json.loads((root / "cleanup.json").read_text()) == {
        "dagu_reaped": True,
        "worker_reaped": True,
    }
    if case == "managed":
        assert evidence["start_exit"] != 0 and evidence["native_result"] == "Failed"
        assert not (root / "invocation.json").exists()
        assert "requires a Dagu server or worker execution host" in (root / "start.log").read_text()
        return
    invocation = json.loads((root / "invocation.json").read_text())
    assert invocation["argv"][0] == "run" and invocation["stdin"] == ""
    assert invocation["cwd"] == str(root / "checkout")
    for flag, value in (
        ("--model", "controlled/no-provider"),
        ("--agent", "build"),
        ("--variant", "high"),
        ("--format", "json"),
    ):
        assert invocation["argv"][invocation["argv"].index(flag) + 1] == value
    assert "--session" not in invocation["argv"]
    assert evidence["prompt_exact"] is False
    original = (root / "prompts/investigate.md").read_text()
    assert "Probe literal $ARTIFACTS_DIR and $(touch escaped)" in original
    assert f"Probe literal {root} and $(touch escaped)" in invocation["argv"][1]
    assert not (root / "checkout/escaped").exists()
    if case == "jsonl":
        assert evidence["start_exit"] == 0 and evidence["native_result"] == "Succeeded"
        assert evidence["adapter_output_certified"] is True
        assert evidence["certification_error"] == "Extra data"
        assert invocation["env"]["ARTIFACTS_DIR"] == str(root)
        return
    assert evidence["service_owned_work_still_busy"] is True
    assert (root / "harness.stdout").read_text() == ""
    assert evidence["native_result"] == ("Failed" if case == "timeout" else "Aborted")
    client = subprocess.run(
        ["ps", "-p", str(invocation["pid"]), "-o", "state="],
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert not client.stdout.strip() or client.stdout.strip().startswith("Z")


def test_rendering_and_certification_retain_source_guards(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_SECRET", "must-not-be-inherited")
    env = PROBE["environment"](tmp_path, "jsonl")
    assert "PROBE_SECRET" not in env and "OPENCODE_SERVER_URL" not in env
    run, prompt = PROBE["prepare"](tmp_path, env)
    assert isinstance(run, Run) and "DAGU bound inputs (authoritative)" in prompt
    assert (tmp_path / "rendered.md").read_text() == prompt
    before = snapshot(run.repo)
    result = json.loads((tmp_path / "answer.json").read_text())
    for invalid in (
        {**result, "verdict": "invented"},
        {**result, "report": {**result["report"], "run_id": "foreign"}},
    ):
        with pytest.raises((ValueError, jsonschema.ValidationError)):
            run.check(invalid, run.nodes["investigate"])
    (tmp_path / "investigation.md").write_text("")
    with pytest.raises(ValueError, match="empty"):
        run.check(result, run.nodes["investigate"])
    assert snapshot(run.repo) == before
