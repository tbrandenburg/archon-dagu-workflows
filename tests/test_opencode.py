"""OpenCode event contract and subprocess transport, without model credentials."""

import json
import os
import subprocess
import sys

import pytest

from archon_dagu.engine import BASE
from archon_dagu.opencode import final_answer


def event(kind, message="final", **fields):
    return json.dumps({"type": kind, "part": {"messageID": message, **fields}})


def test_final_message_excludes_commentary_tools_and_reasoning():
    stream = "\n".join(
        [
            event("text", "earlier", text="Let me inspect this."),
            event("tool_use", output="secret tool output"),
            event("reasoning", text="private reasoning"),
            event("text", text='{"done":'),
            event("text", text="true}"),
            event("step_finish", reason="stop"),
        ]
    )
    assert final_answer(stream) == '{"done":true}'


def test_raw_text_and_missing_finish_remain_supported():
    assert final_answer(event("text", text="Brief\nSTATE\n")) == "Brief\nSTATE\n"


@pytest.mark.parametrize(
    "stream",
    [
        "",
        "not JSON",
        "[]",
        '{"type":"error","error":{"message":"failed"}}',
        '{"type":"text","part":{"text":"missing identity"}}',
        '{"type":"text","part":null}',
        event("text", text=" "),
        event("text", text="partial") + "\n" + event("step_finish", reason="length"),
        event("text", text="before tools") + "\n" + event("step_finish", reason="tool-calls"),
    ],
)
def test_invalid_or_failed_stream_is_rejected(stream):
    with pytest.raises(ValueError):
        final_answer(stream)


def test_defaults_use_adapter_and_check_opencode_prerequisite():
    for name in ("commands", "standalone", "composed"):
        config = json.loads((BASE / "config" / (name + ".json")).read_text())
        assert config["agent_argv"] == ["python", "-m", "archon_dagu.opencode", "--agent", "build"]
        assert "opencode" in config.get("agent_requires", config.get("requires", []))
        assert "claude" not in config.get("requires", [])


@pytest.mark.parametrize("failure", ["", "exit", "event"])
def test_cli_preserves_stdin_cwd_flags_and_failure(tmp_path, failure):
    fake = tmp_path / "opencode"
    record = tmp_path / "record.json"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['RECORD']).write_text(json.dumps(\n"
        " {'argv':sys.argv[1:], 'stdin':sys.stdin.read(), 'cwd':os.getcwd(), 'pwd':os.environ.get('PWD')}))\n"
        "print(json.dumps({'type':'text','part':{'messageID':'answer',"
        " 'text':'{\\\"ready\\\":true}'}}))\n"
        "if os.environ['FAILURE']=='event': print(json.dumps({'type':'error'}))\n"
        "sys.exit(7 if os.environ['FAILURE']=='exit' else 0)\n"
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "RECORD": str(record),
        "FAILURE": failure,
    }
    prompt = "Large prompt\n" * 10000 + "$(touch should-not-exist)"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "archon_dagu.opencode",
            "--model",
            "provider/model",
            "--agent",
            "build",
            "--variant",
            "high",
        ],
        input=prompt,
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
    )
    sent = json.loads(record.read_text())
    assert sent == {
        "argv": [
            "run",
            "--format",
            "json",
            "--model",
            "provider/model",
            "--agent",
            "build",
            "--variant",
            "high",
        ],
        "stdin": prompt,
        "cwd": str(tmp_path),
        "pwd": str(tmp_path),
    }
    assert not (tmp_path / "should-not-exist").exists()
    if failure:
        assert run.returncode != 0 and run.stdout == ""
    else:
        assert run.returncode == 0 and json.loads(run.stdout) == {"ready": True}
