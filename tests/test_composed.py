"""Contract, publication, approval and cleanup tests for issue #3."""

import json
import os
import sys

import pytest

from archon_dagu import standalone
from archon_dagu.composed import Composed, Stage, setup, when
from archon_dagu.engine import BASE, SOURCE, load, save
from archon_dagu.local_runner import run as local_run
from archon_dagu.standalone import git


@pytest.fixture
def start(tmp_path, monkeypatch):
    def make(workflow, case="happy"):
        config = json.loads((BASE / "config/composed.json").read_text())
        config["script_argv"] = [
            "node",
            "--experimental-transform-types",
            "--import",
            str(BASE / "tests/support/bun_compat.mjs"),
        ]
        configfile = tmp_path / "config.json"
        configfile.write_text(json.dumps(config))
        root = tmp_path / (workflow + "-" + case)
        for k, v in {
            "STANDALONE_WORKFLOW": workflow,
            "STANDALONE_MODE": "fixture",
            "STANDALONE_FIXTURE": str(BASE / "examples/composed" / f"{workflow}-{case}.json"),
            "STANDALONE_CONFIG": str(configfile),
            "STATE_DIR": str(root),
        }.items():
            monkeypatch.setenv(k, v)
        setup(root)
        return Composed(root)

    return make


def execute(run):
    pending = {
        sid: entry
        for sid, entry in run.graph.items()
        if not (run.name == "issue-response" and sid in ("review", "drop", "post"))
    }
    done = set()
    while pending:
        wave = [sid for sid, e in pending.items() if set(e["depends"]) <= done]
        assert wave
        for sid in wave:
            run.stage(sid)
            done.add(sid)
            pending.pop(sid)
    if run.name == "issue-response":
        run.stage("approval_snapshot")
        run.stage("post", approved=True)
    return run.report()


@pytest.mark.parametrize(
    "workflow", ["review", "simplify", "pr", "ship", "upkeep", "issue-response"]
)
def test_six_compositions_complete_with_original_contracts(start, workflow):
    report = execute(start(workflow))
    assert report["outcome"] is True
    assert report["external_effects"] == "simulated"


@pytest.mark.parametrize(
    "case,reason",
    [
        ("blocked", "blocked"),
        ("no-action", "no_action"),
        ("refuted", "refuted"),
        ("inconclusive", "not_rooted"),
        ("plan-blocked", "ask"),
    ],
)
def test_source_ship_spend_gates_stop_before_delivery(start, case, reason):
    run = start("ship", case)
    report = execute(run)
    assert report["result"]["reason"] == reason
    assert not (run.root / "delivery-request.json").exists()
    assert not report["outcome"]


def test_source_light_review_only_runs_code_and_keeps_cursor(start):
    run = start("review", "light")
    execute(run)
    assert run.result("mode")["cursor"] == git(run.repo, "rev-parse", "HEAD")
    assert run.result("route") is None
    assert run.result("code") is not None
    assert all(run.result(n) is None for n in ["seams", "tests", "errors", "docs"])
    assert (run.root / "review/reviewed-head").read_text().strip() == git(
        run.repo, "rev-parse", "HEAD"
    )


def test_scope_mismatch_stops_before_any_review_or_publication(start):
    run = start("review", "head-mismatch")
    result = execute(run)["result"]
    assert result["action"] == "ask"
    assert run.result("mode") is None and run.result("synthesize") is None
    assert not (run.root / "review/reviewed-head").exists()


def test_failed_selected_lens_blocks_ready_and_is_not_certified(start):
    run = start("review", "specialist-failed")
    report = execute(run)
    assert not report["outcome"]
    assert "code" in report["result"]["findings_summary"]
    assert "Incomplete review coverage" in (run.root / "review/report.md").read_text()
    assert load(run.root / "status/code.json")["status"] == "failed"
    listing = load(run.listing(""))
    assert "code" not in [r["nodeId"] for r in listing["artifactsByType"]["review-lens"]]


def test_original_cleanup_removes_registered_scratch_on_failure(start):
    run = start("simplify", "agent-failed")
    scratch = run.root / ".archon/scratch/simplify/probe"
    git(run.repo, "worktree", "add", "--detach", str(scratch), "HEAD")
    with pytest.raises(RuntimeError):
        run.stage("simplify")
    run.report(failed=True)
    assert not scratch.exists()
    assert str(scratch) not in git(run.repo, "worktree", "list", "--porcelain")


def test_approved_reply_is_byte_exact_and_retry_is_idempotent(start):
    run = start("issue-response")
    report = execute(run)
    posted = load(run.root / "effects/comment.json")
    assert report["result"]["posted"]
    assert posted["comment"] == run.result("investigate")["comment"]
    assert run.stage("post", approved=True)["posted"]
    assert "$()" in posted["comment"]


def test_changed_reply_or_target_invalidates_approval(start):
    run = start("issue-response")
    run.stage("classify")
    run.stage("investigate")
    run.stage("approval_snapshot")
    changed = run.result("investigate")
    changed["comment"] = "Different text"
    save(run.root / "nodes/investigate.json", changed)
    with pytest.raises(ValueError, match="changed"):
        run.stage("post", approved=True)
    assert not (run.root / "effects/comment.json").exists()


def test_rejected_reply_writes_nothing(start):
    run = start("issue-response", "reject")
    assert not execute(run)["result"]["posted"]
    assert not (run.root / "effects/comment.json").exists()


def test_uncertain_pr_publication_is_durable_and_cannot_replay(start):
    run = start("pr", "uncertain")
    run.stage("forge")
    run.stage("prepare")
    with pytest.raises(RuntimeError, match="uncertain"):
        run.stage("publish")
    assert (run.root / "effects/pr-uncertain.json").exists()
    with pytest.raises(ValueError, match="Uncertain"):
        run.stage("publish")


@pytest.mark.parametrize(
    "branch,expected",
    [
        ("workflow-test-issue16/validation", "authoritative as the PR head"),
        ("", "no explicit `branch` input was supplied"),
    ],
)
def test_pr_prepare_runtime_guidance_handles_detached_checkout(
    start, monkeypatch, branch, expected
):
    run = start("pr")
    run.ctx["inputs"]["branch"] = branch
    if branch:
        git(run.repo, "branch", branch)
    git(run.repo, "checkout", "--detach", "HEAD")
    assert git(run.repo, "branch", "--show-current") == ""
    stage = Stage(run, "prepare")
    stage.fixture = False
    stage.ctx["mode"] = "live"
    prompt = {}

    def capture(argv, cwd, env, stdin, timeout):
        prompt["text"] = stdin
        return "{}"

    monkeypatch.setattr(standalone, "invoke", capture)
    stage.agent(stage.nodes["prepare"], "prepare")

    assert expected in prompt["text"]
    if branch:
        assert "do not derive it from `git branch --show-current`" in prompt["text"]
        assert "fail preparation; never substitute another branch" in prompt["text"]
        assert "workflow-test-issue16/validation" in prompt["text"]
    else:
        assert "fail preparation before publication" in prompt["text"]


def test_local_harness_never_implicitly_approves_a_live_gate(tmp_path):
    with pytest.raises(ValueError, match="Approval gates require native"):
        local_run(
            BASE / "workflows/issue-response-live.yaml",
            {"project_dir": str(BASE), "state_dir": str(tmp_path)},
        )
    assert not (tmp_path / "context.json").exists()


def test_source_condition_short_circuit_and_no_code_execution():
    def missing(*_):
        raise AssertionError("Skipped producer was read")

    assert not when("false && $missing.output.value == true", missing)
    assert when("true || $missing.output.value == true", missing)
    with pytest.raises(ValueError):
        when("__import__('os')", missing)


def fake_github(stage, tmp_path):
    """Local gh double; unchanged upstream publisher performs all reads/writes."""
    directory = tmp_path / "fake-bin"
    directory.mkdir()
    state = tmp_path / "github.json"
    head = git(stage.repo, "rev-parse", "HEAD")
    save(state, {"head": head, "comments": [], "writes": []})
    script = directory / "gh"
    script.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import json,sys,pathlib,os
p=pathlib.Path(os.environ['FAKE_GITHUB_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
if a[:2]==['pr','view']:
 print(json.dumps({'number':42,'url':'https://github.com/example/repo/pull/42','title':'Fixture','body':'Fixture','state':'OPEN','isDraft':True,'headRefName':'feature','baseRefName':'main','headRefOid':s['head'],'headRepository':{'name':'repo'},'headRepositoryOwner':{'login':'example'},'maintainerCanModify':True}))
elif a[0]=='api':
 method=a[a.index('--method')+1] if '--method' in a else 'GET'
 if method in ('POST','PATCH'):
  body=json.loads(pathlib.Path(a[a.index('--input')+1]).read_text())['body']
  row={'id':1,'html_url':'https://github.com/example/repo/issues/42#issuecomment-1','body':body,'user':{'login':'fixture'}}
  s['comments']=[row];s['writes'].append(method);out=row;p.write_text(json.dumps(s))
 else:out=s['comments']
 print('HTTP/2.0 200 OK\\nContent-Type: application/json\\n\\n'+json.dumps(out))
else:raise SystemExit('Unexpected fake gh call: '+str(a))
"""
    )
    script.chmod(0o755)
    stage.env.update(
        PATH=str(directory) + os.pathsep + stage.env["PATH"],
        FAKE_GITHUB_STATE=str(state),
        TMPDIR=str(tmp_path),
    )
    return state


def test_original_publisher_updates_one_comment_and_refuses_stale_head(start, tmp_path):
    run = start("review")
    execute(run)
    stage = Stage(run, "publish")
    state = fake_github(stage, tmp_path)
    bindings = stage.bindings(stage.nodes["publish"])
    bindings["pr"] = {"repo": {"host": "github.com", "path": "example/repo"}, "number": 42}
    path = str(SOURCE / "review/scripts/publish-review.ts")
    stage.script(path, bindings)
    (run.root / "review/report.md").write_text(
        "# Updated review\nSecond evidence-backed verdict.\n"
    )
    stage.script(path, bindings)
    record = load(state)
    assert record["writes"] == ["POST", "PATCH"] and len(record["comments"]) == 1
    assert "Second evidence" in record["comments"][0]["body"]
    record["head"] = "changed-on-forge"
    save(state, record)
    with pytest.raises(RuntimeError, match="not pushed"):
        stage.script(path, bindings)
    assert load(state)["writes"] == ["POST", "PATCH"]


def test_offline_dependency_upgrade_updates_lock_and_repairs_breaking_api(tmp_path):
    import shutil
    import subprocess

    project = tmp_path / "dependency-project"
    shutil.copytree(BASE / "examples/projects/dependency-update", project)
    npm = shutil.which("npm")
    assert npm, "Node/npm are part of the documented test prerequisites"

    def command(*args, check=True):
        return subprocess.run(
            [npm, *args], cwd=project, capture_output=True, text=True, check=check
        )

    command("install", "--offline", "--ignore-scripts", "--no-audit", "--no-fund")
    command("test")
    package = project / "vendor/calc/package.json"
    value = json.loads(package.read_text())
    value["version"] = "2.0.0"
    package.write_text(json.dumps(value))
    (project / "vendor/calc/index.cjs").write_text(
        "exports.add = ({ left, right }) => left + right;\n"
    )
    command(
        "install", "--package-lock-only", "--offline", "--ignore-scripts", "--no-audit", "--no-fund"
    )
    assert command("test", check=False).returncode != 0
    (project / "test.cjs").write_text(
        "const assert = require('node:assert/strict'); const { add } = require('fixture-calc'); assert.equal(add({left:2,right:3}),5);\n"
    )
    command("test")
    locked = json.loads((project / "package-lock.json").read_text())
    assert locked["packages"]["vendor/calc"]["version"] == "2.0.0"
    assert locked["packages"][""]["name"] == "archon-upkeep-offline-example"


def test_event_adapter_filters_action_and_repository():
    import runpy

    normalize = runpy.run_path(str(BASE / "scripts/issue_event.py"))["normalize"]
    payload = {
        "action": "opened",
        "repository": {"full_name": "example/repo"},
        "issue": {"number": 7},
    }
    assert normalize(payload, "example/repo")["params"] == {
        "repository": "example/repo",
        "issue_number": "7",
    }
    assert not normalize({**payload, "action": "edited"}, "example/repo")["eligible"]
    assert not normalize({**payload, "issue": {"number": 7, "pull_request": {}}}, "example/repo")[
        "eligible"
    ]
    with pytest.raises(ValueError, match="does not match"):
        normalize(payload, "other/repo")
    with pytest.raises(ValueError, match="positive"):
        normalize({**payload, "issue": {"number": 0}}, "example/repo")


def test_not_ready_delivery_requests_a_root_decision(start):
    run = start("ship")
    run.ctx["fixture"]["delivery_rounds"] = [{"ci": {"state": "other"}}]
    save(run.root / "context.json", run.ctx)
    report = execute(run)
    assert report["result"]["reason"] == "ci_other"
    assert not report["outcome"] and report["needs_decision"]


@pytest.mark.parametrize(
    "case,lenses",
    [("happy", ["seams", "code", "tests"]), ("specialist-failed", ["seams", "tests"])],
)
def test_live_synthesis_transport_binds_typed_metadata_and_commit(start, tmp_path, case, lenses):
    run = start("review", case)
    execute(run)
    stage = Stage(run, "synthesize")
    stage.fixture = False
    expected = {
        "artifactsByType": {
            "review-lens": [
                {
                    "path": f"nodes/{lens}.json",
                    "nodeId": lens,
                    "producer": {"execution": {"path": lens, "invocation": {"loopPath": []}}},
                    "loopGroupPath": [],
                }
                for lens in lenses
            ]
        },
        "errors": [],
    }
    script = tmp_path / "controlled-synthesis.py"
    script.write_text("""import os,pathlib,sys,json
root=pathlib.Path(os.environ['ARTIFACTS_DIR'])
(root/'received-synthesis.txt').write_text(sys.stdin.read())
listing_path=pathlib.Path(os.environ['TYPED_ARTIFACTS_FILE'])
listing=json.loads(listing_path.read_text())
assert listing == json.loads(sys.argv[1]), listing
outputs={row['nodeId']:json.loads((root/row['path']).read_text()) for row in listing['artifactsByType']['review-lens']}
(root/'received-typed-artifacts.json').write_text(json.dumps({'path':str(listing_path),'listing':listing,'outputs':outputs}))
print(json.dumps({'ready':True,'action':'none','findings_summary':'Controlled transport','report':{'type':'archon_artifact','run_id':root.name,'path':'review/report.md'},'discoveries':[],'contract_left':[]}))
""")
    stage.config = {
        **stage.config,
        "agent_argv": [sys.executable, str(script), json.dumps(expected)],
    }
    node = stage.nodes["synthesize"]
    result = stage.agent(node, "synthesize")
    stage.check(result, node)
    prompt = (run.root / "received-synthesis.txt").read_text()
    assert "$TYPED_ARTIFACTS_FILE" not in prompt
    assert "$mode.output.head" not in prompt
    assert git(run.repo, "rev-parse", "HEAD") in prompt
    assert str(run.root / "typed/root.json") in prompt
    proof = load(run.root / "received-typed-artifacts.json")
    assert proof == {
        "path": str(run.root / "typed/root.json"),
        "listing": expected,
        "outputs": {
            lens: text
            for lens, text in {
                "seams": "Fixture seam lens completed.",
                "code": "Fixture code lens completed.",
                "tests": "Fixture tests lens completed.",
            }.items()
            if lens in lenses
        },
    }
    assert load(run.root / "status/code.json")["status"] == (
        "failed" if case == "specialist-failed" else "succeeded"
    )
    assert load(run.root / "status/errors.json")["status"] == "skipped"
    assert load(run.root / "status/docs.json")["status"] == "skipped"


def test_missing_lens_does_not_override_a_human_decision(start):
    run = start("review", "ask")
    run.ctx["fixture"]["fail"] = ["code"]
    save(run.root / "context.json", run.ctx)
    report = execute(run)
    assert report["result"]["action"] == "ask"
    assert report["needs_decision"]
    assert "Incomplete review coverage" in (run.root / "review/report.md").read_text()
