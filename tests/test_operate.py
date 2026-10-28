"""Onboarding separates fixtures, actual agent transport and live forge runs."""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

from archon_dagu.engine import BASE

spec = importlib.util.spec_from_file_location("operate", BASE / "scripts/operate.py")
operate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operate)


def test_configure_persists_explicit_selection_and_preserves_other_settings(tmp_path):
    path = tmp_path / "commands.json"
    original = json.loads((BASE / "config/commands.json").read_text())
    original["custom"] = {"retain": True}
    path.write_text(json.dumps(original))
    operate.configure(path, "provider/model", "build")
    config = json.loads(path.read_text())
    assert config["agent_argv"][-4:] == ["--agent", "build", "--model", "provider/model"]
    assert config["commands"] == original["commands"]
    assert config["custom"] == original["custom"]


def test_fresh_config_uses_built_in_defaults(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    source = (BASE / "config/commands.json").read_text()
    (tmp_path / "config/commands.json").write_text(source)
    monkeypatch.setattr(operate, "BASE", tmp_path)
    path = tmp_path / "config/commands.local.json"
    operate.configure(path, "provider/model", "build")
    assert path.exists()
    assert json.loads(path.read_text())["agent_argv"][-1] == "provider/model"


@pytest.mark.parametrize("model", ["", "unspecified", "provider/model with spaces"])
def test_missing_model_is_actionable_and_does_not_write(tmp_path, model):
    path = tmp_path / "new.json"
    with pytest.raises(ValueError, match="MODEL"):
        operate.configure(path, model, "build")
    assert not path.exists()


def test_explicit_missing_config_never_falls_back(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        operate.configuration(tmp_path / "typo.json")


def test_live_commands_refuse_test_transport(tmp_path):
    path = tmp_path / "mock.json"
    path.write_text(json.dumps({"test_transport": True, "agent_argv": [sys.executable]}))
    with pytest.raises(ValueError, match="refuse test_transport"):
        operate.configuration(path)


def test_doctor_explains_missing_cli_without_invoking_commands(tmp_path, monkeypatch, capsys):
    path = tmp_path / "commands.json"
    path.write_text((BASE / "config/commands.json").read_text())
    monkeypatch.setattr(operate.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        operate.subprocess, "run", lambda *a, **k: pytest.fail("doctor invoked agent")
    )
    with pytest.raises(ValueError, match="Missing prerequisites"):
        operate.doctor(path, agent_only=True)
    assert "opencode auth login" in capsys.readouterr().err


def test_agent_smoke_invokes_configured_cli_without_delivery(tmp_path, monkeypatch):
    script = tmp_path / "agent.py"
    script.write_text(
        "import sys; assert 'Do not use tools' in sys.stdin.read(); print('{\"ok\":true}')"
    )
    config = {"agent_argv": [sys.executable, str(script)]}
    monkeypatch.setattr(operate, "BASE", tmp_path)
    monkeypatch.setattr(operate, "doctor", lambda *a, **k: (None, config))
    operate.smoke(tmp_path / "commands.json")
    report = json.loads(next((tmp_path / ".runs/agent-smoke").glob("*/report.json")).read_text())
    assert report == {"agent_invoked": True, "forge_stages_invoked": False, "result": {"ok": True}}


def test_delivery_uses_selected_config_and_literal_work_file(tmp_path, monkeypatch):
    work = tmp_path / "work.md"
    work.write_text("Fix O'Reilly's parser; $(do-not-run)\n")
    config = json.loads((BASE / "config/commands.json").read_text())
    selected = tmp_path / "commands.local.json"
    selected.write_text(json.dumps(config))
    monkeypatch.setattr(operate, "BASE", tmp_path)
    monkeypatch.setattr(operate, "doctor", lambda *a, **k: (selected, config))
    commands = []
    monkeypatch.setattr(operate.subprocess, "run", lambda argv, **k: commands.append(argv))
    state = tmp_path / "run"
    operate.deliver(selected, "detailed-real", str(tmp_path), str(work), str(state))
    argv = commands[0]
    assert str(tmp_path / "workflows/detailed-real.yaml") in argv
    assert "work=" + work.read_text().strip() in argv
    assert "commands=" + str(state / "commands.json") in argv
    assert json.loads((state / "commands.json").read_text()) == config
    with pytest.raises(ValueError, match="must be new"):
        operate.deliver(selected, "detailed-real", str(tmp_path), str(work), str(state))


def test_make_defaults_agent_and_forwards_explicit_model_and_agent(tmp_path):
    fake = tmp_path / "uv"
    fake.write_text(
        f"#!{sys.executable}\nimport os; print(os.environ['MODEL'] + '|' + os.environ['AGENT'])\n"
    )
    fake.chmod(0o755)
    value = "provider/model';touch should-not-exist;'"
    result = subprocess.run(
        ["make", "configure-agent", "UV=" + str(fake), "MODEL=" + value],
        cwd=BASE,
        env={"PATH": os.environ["PATH"], "AGENT": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert value + "|build" in result.stdout
    assert not (BASE / "should-not-exist").exists()

    explicit = subprocess.run(
        [
            "make",
            "configure-agent",
            "UV=" + str(fake),
            "MODEL=provider/model",
            "AGENT=plan",
        ],
        cwd=BASE,
        env={"PATH": os.environ["PATH"], "AGENT": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "provider/model|plan" in explicit.stdout

    named = subprocess.run(
        [
            "make",
            "configure-agent",
            "UV=" + str(fake),
            "MODEL=provider/model",
            "OPENCODE_AGENT=review",
        ],
        cwd=BASE,
        env={"PATH": os.environ["PATH"], "AGENT": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "provider/model|review" in named.stdout


def test_doctor_migrates_existing_local_config_without_losing_model(tmp_path, monkeypatch):
    path = tmp_path / "commands.json"
    config = json.loads((BASE / "config/commands.json").read_text())
    config["requires"].append("archon")
    config["archon_argv"] = ["archon"]
    config["agent_argv"] += ["--model", "openai/example"]
    path.write_text(json.dumps(config))
    monkeypatch.setattr(operate.shutil, "which", lambda name: None if name == "archon" else name)
    _, selected = operate.doctor(path)
    assert selected["agent_argv"] == config["agent_argv"]
    assert "archon" not in selected["requires"]
    # This read-only command leaves ignored user config intact.
    assert json.loads(path.read_text()) == config
