"""Behavior checks for source contracts, real subprocess transport and recovery."""

import json
import pathlib
import sys

import jsonschema
import pytest

from archon_dagu.engine import BASE
from archon_dagu.standalone import Run, git, initialize, load, snapshot


@pytest.fixture
def node_config(tmp_path):
    config = json.loads((BASE / "config/standalone.json").read_text())
    config["script_argv"] = [
        "node",
        "--experimental-transform-types",
        "--import",
        str(BASE / "tests/support/bun_compat.mjs"),
    ]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


def start(tmp_path, node_config, workflow, case="happy", **overrides):
    env = {
        "STANDALONE_WORKFLOW": workflow,
        "STANDALONE_MODE": "fixture",
        "STANDALONE_FIXTURE": str(BASE / "examples/standalone" / f"{workflow}-{case}.json"),
        "STANDALONE_CONFIG": str(node_config),
        **overrides,
    }
    root = tmp_path / (workflow + "-" + case)
    initialize(root, env)
    return Run(root), env


def execute(run):
    for node in run.doc["nodes"]:
        if run.name == "implement":
            for turn in range(1, 6):
                run.stage("implement_" + str(turn))
        else:
            run.stage(node["id"])
    return run.report()


@pytest.mark.parametrize(
    "workflow", ["validate", "investigate", "plan", "triage", "implement", "standup"]
)
def test_original_scripts_and_contracts_complete(workflow, tmp_path, node_config):
    run, _ = start(tmp_path, node_config, workflow)
    report = execute(run)
    assert report["outcome"] is True
    assert report["external_effects"] == "simulated"
    assert report["lifecycle"] == "completed"


def test_validation_stops_failed_group_but_runs_independent_gate(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "validate", "red-introduced")
    report = execute(run)
    assert report["result"]["red_cause"] == "introduced"
    text = (run.root / "validation.md").read_text()
    assert "never ran" in text and "independent" in text and "passed (exit 0)" in text
    assert not (run.root / "validation/2.log").exists()
    assert "independent gate ran" in (run.root / "validation/3.log").read_text()


def test_validation_unstartable_is_incomplete_not_red(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "validate", "incomplete")
    assert execute(run)["result"]["red_cause"] == "incomplete"
    assert run.result("classify") is None


def test_implementation_five_turn_cap_does_not_certify_completion(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "implement", "cap")
    report = execute(run)
    assert report["reason"] == "iteration_cap"
    assert report["outcome"] is False and report["needs_decision"] is True
    assert len(list((run.root / "nodes").glob("implement_*.json"))) == 5


def test_done_implementation_does_not_call_more_agents(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "implement")
    # Only implement_1 exists in this fixture; an extra call would raise KeyError.
    assert execute(run)["outcome"] is True
    assert run.result("implement_1") == run.result("implement_5")


def test_fixture_publish_cannot_write_labels(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "triage", PUBLISH="true")
    result = execute(run)["result"]
    assert result["published"] is False
    assert "archon-ready" in result["labels"]


def test_illegal_triage_tuple_rejected_before_verdict(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "triage", "invalid-decision")
    run.stage("policy")
    with pytest.raises(jsonschema.ValidationError):
        run.stage("triage")
    assert not (run.root / "nodes/verdict.json").exists()


def test_report_pointer_must_belong_to_run_and_not_escape(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "plan")
    run.stage("policy")
    node = run.nodes["plan"]
    value = run.agent(node, "plan")
    value["report"]["run_id"] = "other-run"
    with pytest.raises(ValueError, match="foreign"):
        run.check(value, node)
    value["report"]["run_id"] = run.root.name
    report = run.root / "plan.md"
    report.unlink()
    report.symlink_to(node_config)
    with pytest.raises(ValueError, match="escaping"):
        run.check(value, node)


def test_retry_reuses_success_and_refuses_uncertain_attempt(tmp_path, node_config):
    run, env = start(tmp_path, node_config, "investigate")
    first = run.stage("investigate")
    initialize(run.root, env)
    assert Run(run.root).stage("investigate") == first
    marker = run.root / "journal/verdict.started"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text("{}")
    with pytest.raises(ValueError, match="Reconcile"):
        run.stage("verdict")
    with pytest.raises(ValueError, match="different inputs"):
        initialize(run.root, {**env, "WORK_INPUT": "changed request"})


def test_standup_continuity_uses_prior_state_and_saves_dated_brief(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "standup", "prior-state")
    execute(run)
    assert run.result("read-context")["prior_state"]["last_dev_sha"] == "prior-fixture-head"
    persisted = run.result("persist")
    assert (run.repo / persisted["brief_path"]).read_text().startswith("# Maintainer Standup")
    assert load(run.repo / persisted["state_path"])["last_dev_sha"] == "fixture-head"


def live_run(tmp_path, node_config, workflow, mutate=False):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "code.txt").write_text("original\n")
    git(repo, "add", "code.txt")
    git(repo, "commit", "-qm", "Baseline")
    stub = tmp_path / "controlled_agent.py"
    # A controlled CLI exercises the live stdin/stdout transport, not an LLM.
    fixture = BASE / "examples/standalone" / f"{workflow}-happy.json"
    stub.write_text("""import json,os,pathlib,sys
prompt=sys.stdin.read()
root=pathlib.Path(os.environ['ARTIFACTS_DIR'])
spec=json.loads(pathlib.Path(sys.argv[1]).read_text())
(root/'received-prompt.txt').write_text(prompt)
for path,text in spec.get('artifacts',{}).items():
 (root/path).write_text(text)
value=next(iter(spec['agents'].values()))
value=json.loads(json.dumps(value).replace('$RUN_ID',root.name))
if sys.argv[2]=='mutate': pathlib.Path('code.txt').write_text('changed')
print(json.dumps(value))
""")
    config = json.loads(node_config.read_text())
    config["agent_requires"] = []  # This controlled transport does not use OpenCode.
    config["agent_argv"] = [
        sys.executable,
        str(stub),
        str(fixture),
        "mutate" if mutate else "clean",
    ]
    node_config.write_text(json.dumps(config))
    root = tmp_path / "live"
    initialize(
        root,
        {
            "STANDALONE_WORKFLOW": workflow,
            "STANDALONE_MODE": "live",
            "STANDALONE_CONFIG": str(node_config),
            "TARGET_REPO": str(repo),
            "WORK_INPUT": "Investigate $ARTIFACTS_DIR as literal user text",
        },
    )
    return Run(root), repo


def test_live_transport_isolates_checkout_and_expands_prompt_once(tmp_path, node_config):
    run, source = live_run(tmp_path, node_config, "investigate")
    before = snapshot(source)
    assert execute(run)["outcome"] is True
    assert snapshot(source) == before
    assert run.repo != source
    prompt = (run.root / "received-prompt.txt").read_text()
    assert "Investigate $ARTIFACTS_DIR as literal user text" in prompt
    assert str(run.root) in prompt
    assert run.report()["external_effects"].startswith("live;")


def test_advisory_agent_mutation_is_detected_and_contained(tmp_path, node_config):
    run, source = live_run(tmp_path, node_config, "investigate", mutate=True)
    with pytest.raises(ValueError, match="modified"):
        run.stage("investigate")
    assert (source / "code.txt").read_text() == "original\n"
    assert not (run.root / "nodes/investigate.json").exists()


def test_standup_refuses_implicit_in_place_writes(tmp_path, node_config):
    # Configuration is checked before any fetch, pull or persistence.
    run, source = live_run(tmp_path, node_config, "investigate")
    with pytest.raises(ValueError, match="standup_in_place"):
        initialize(
            tmp_path / "standup-live",
            {
                "STANDALONE_WORKFLOW": "standup",
                "STANDALONE_MODE": "live",
                "STANDALONE_CONFIG": str(node_config),
                "TARGET_REPO": str(source),
            },
        )


def test_timeout_becomes_incomplete_and_does_not_classify_red(tmp_path, node_config, monkeypatch):
    run, _ = start(tmp_path, node_config, "validate")
    run.stage("discover")
    original = run.script

    def timeout(relative, *args, **kwargs):
        if relative.endswith("/run-checks.ts"):
            raise TimeoutError("Controlled runner timeout")
        return original(relative, *args, **kwargs)

    monkeypatch.setattr(run, "script", timeout)
    run.stage("run")
    run.stage("classify")
    run.stage("result")
    assert run.report()["result"]["red_cause"] == "incomplete"
    assert run.result("classify") is None


def test_live_implement_commits_on_its_own_branch(tmp_path, node_config):
    run, source = live_run(tmp_path, node_config, "implement")
    agent = pathlib.Path(run.config["agent_argv"][1])
    script = agent.read_text().replace(
        "print(json.dumps(value))",
        """import subprocess
pathlib.Path('code.txt').write_text('implemented in isolated branch\\n')
subprocess.run(['git','add','code.txt'],check=True)
subprocess.run(['git','commit','-qm','Implement controlled change'],check=True)
print(json.dumps(value))""",
    )
    agent.write_text(script)
    original_head = git(source, "rev-parse", "HEAD")
    assert execute(run)["outcome"] is True
    assert git(source, "rev-parse", "HEAD") == original_head
    assert git(run.repo, "rev-parse", "HEAD") != original_head
    assert git(run.repo, "branch", "--show-current").startswith("dagu/implement-")
    assert (source / "code.txt").read_text() == "original\n"


def test_live_standup_claim_excludes_other_run_and_releases(tmp_path, node_config):
    _, source = live_run(tmp_path, node_config, "investigate")
    config = json.loads(node_config.read_text())
    config["standup_in_place"] = True
    node_config.write_text(json.dumps(config))
    env = {
        "STANDALONE_WORKFLOW": "standup",
        "STANDALONE_MODE": "live",
        "STANDALONE_CONFIG": str(node_config),
        "TARGET_REPO": str(source),
    }
    first = tmp_path / "standup-one"
    initialize(first, env)
    with pytest.raises(FileExistsError):
        initialize(tmp_path / "standup-two", env)
    Run(first).report(failed=True)
    initialize(tmp_path / "standup-three", env)
    assert pathlib.Path(Run(tmp_path / "standup-three").ctx["standup_claim"]).exists()
    Run(tmp_path / "standup-three").report(failed=True)


@pytest.mark.parametrize("workflow", ["plan", "triage", "validate"])
def test_other_live_stage_transports_with_controlled_cli(workflow, tmp_path, node_config):
    run, source = live_run(tmp_path, node_config, workflow)
    original_head = git(source, "rev-parse", "HEAD")
    assert execute(run)["outcome"] is True
    assert git(source, "rev-parse", "HEAD") == original_head
    if workflow == "triage":
        assert run.report()["result"]["published"] is False


def test_live_standup_local_git_and_stub_forge_persist_continuity(tmp_path, node_config):
    _, source = live_run(tmp_path, node_config, "investigate")
    git(source, "branch", "dev")
    git(source, "remote", "add", "origin", str(source))
    agent = tmp_path / "standup_agent.py"
    agent.write_text("""import os,pathlib,sys
prompt=sys.stdin.read()
root=pathlib.Path(os.environ['ARTIFACTS_DIR'])
(root/'received-prompt.txt').write_text(prompt)
print('# Maintainer Standup\\n\\nP1: review the local fixture.\\nARCHON_STATE_JSON_BEGIN\\n{"last_dev_sha":"controlled-head","last_run_at":"2026-10-27T08:00:00Z"}\\nARCHON_STATE_JSON_END')
""")
    config = json.loads(node_config.read_text())
    config.update(standup_in_place=True, agent_argv=[sys.executable, str(agent)])
    node_config.write_text(json.dumps(config))
    root = tmp_path / "standup-live"
    initialize(
        root,
        {
            "STANDALONE_WORKFLOW": "standup",
            "STANDALONE_MODE": "live",
            "STANDALONE_CONFIG": str(node_config),
            "TARGET_REPO": str(source),
        },
    )
    run = Run(root)
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    gh = fakebin / "gh"
    gh.write_text('#!/bin/sh\nprintf "[]\\n"\n')
    gh.chmod(0o755)
    run.env["PATH"] = str(fakebin) + ":" + run.env["PATH"]
    assert execute(run)["outcome"] is True
    assert run.result("git-status")["current_dev_sha"] == git(source, "rev-parse", "HEAD")
    assert (
        load(source / ".archon/maintainer-standup/state.json")["last_dev_sha"] == "controlled-head"
    )
    assert not pathlib.Path(run.ctx["standup_claim"]).exists()
    received = (root / "received-prompt.txt").read_text()
    assert "$git-status.output" not in received
    assert "current_dev_sha" in received


def test_no_action_is_a_valid_end_without_requesting_a_decision(tmp_path, node_config):
    run, _ = start(tmp_path, node_config, "triage", "no-action")
    report = execute(run)
    assert not report["outcome"] and not report["needs_decision"]


def test_cancelling_step_forwards_signal_to_command(tmp_path):
    import signal
    import subprocess
    import time

    child = tmp_path / "child.py"
    ready, stopped = tmp_path / "ready", tmp_path / "stopped"
    child.write_text("""import pathlib,signal,time,sys
ready,stopped=map(pathlib.Path,sys.argv[1:])
def stop(*_):
 stopped.write_text('stopped')
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
ready.write_text('ready')
while True: time.sleep(.1)
""")
    wrapper = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,sys; from archon_dagu.standalone import invoke; invoke(sys.argv[1:],os.getcwd(),os.environ)",
            sys.executable,
            str(child),
            str(ready),
            str(stopped),
        ],
        cwd=BASE,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "controlled command did not start"
        wrapper.send_signal(signal.SIGTERM)
        assert wrapper.wait(timeout=5) == 128 + signal.SIGTERM
        assert stopped.read_text() == "stopped"
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait()


def test_live_work_cannot_start_from_missing_request(tmp_path, node_config):
    _, source = live_run(tmp_path, node_config, "investigate")
    with pytest.raises(ValueError, match="explicit input"):
        initialize(
            tmp_path / "missing-request",
            {
                "STANDALONE_WORKFLOW": "implement",
                "STANDALONE_MODE": "live",
                "STANDALONE_CONFIG": str(node_config),
                "TARGET_REPO": str(source),
            },
        )
    assert not (tmp_path / "missing-request/checkout").exists()


@pytest.mark.parametrize("name", ["standalone", "composed"])
@pytest.mark.parametrize("mode", ["fixture", "live"])
def test_saved_agent_selection_is_shared_only_by_live_defaults(tmp_path, monkeypatch, name, mode):
    import archon_dagu.standalone as module

    folder = tmp_path / "config"
    folder.mkdir()
    config = {"agent_argv": ["default-agent"], "script_argv": ["bun"]}
    path = folder / (name + ".json")
    path.write_text(json.dumps(config))
    selected = [sys.executable, "-m", "archon_dagu.opencode", "--model", "provider/model"]
    (folder / "commands.local.json").write_text(json.dumps({"agent_argv": selected}))
    monkeypatch.setattr(module, "BASE", tmp_path)
    loaded = module.workflow_config(path, mode)
    assert loaded["agent_argv"] == (selected if mode == "live" else config["agent_argv"])
    assert loaded["script_argv"] == ["bun"]


def test_custom_workflow_config_keeps_its_agent(tmp_path, monkeypatch):
    import archon_dagu.standalone as module

    (tmp_path / "config").mkdir()
    (tmp_path / "config/commands.local.json").write_text(
        json.dumps({"agent_argv": ["shared-agent"]})
    )
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({"agent_argv": ["custom-agent"]}))
    monkeypatch.setattr(module, "BASE", tmp_path)
    assert module.workflow_config(path, "live")["agent_argv"] == ["custom-agent"]


def test_workflow_runtime_rejects_inherited_archon_plugin_route(tmp_path, node_config, monkeypatch):
    monkeypatch.setenv("ARCHON_SDLC_FORGE", "forge")
    monkeypatch.setenv("ARCHON_CLI_COMMAND", '["archon"]')
    run, _ = start(tmp_path, node_config, "investigate")
    assert run.env["ARCHON_SDLC_FORGE"] == "gh"
    assert "ARCHON_CLI_COMMAND" not in run.env
