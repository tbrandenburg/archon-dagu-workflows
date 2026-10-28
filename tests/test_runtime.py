"""GitHub delivery has no Archon executable or service dependency."""

import json
import os
import subprocess
import sys

import pytest

from archon_dagu.engine import BASE, preflight
from archon_dagu.runtime import github_config, github_env


def legacy():
    config = json.loads((BASE / "config/commands.json").read_text())
    config["requires"].append("archon")
    config["archon_argv"] = ["archon"]
    config["agent_argv"] += ["--model", "openai/example"]
    return config


def test_old_local_config_keeps_model_and_drops_obsolete_host():
    old = legacy()
    current = github_config(old)
    assert "archon" not in current["requires"]
    assert "archon_argv" not in current
    assert current["agent_argv"] == old["agent_argv"]
    assert current["forge_source"] == "gh"
    assert "archon" in old["requires"]  # Never mutate the caller's config.


def test_custom_adapters_are_not_silently_migrated():
    custom = {"commands": {"forge": ["custom"]}, "requires": ["archon"]}
    assert github_config(custom) == custom


def test_archon_plugin_selection_is_not_a_supported_runtime():
    config = legacy()
    config["forge_source"] = "forge"
    with pytest.raises(ValueError, match="forge_source=gh"):
        github_config(config)


def test_inherited_archon_settings_cannot_select_plugin():
    env = github_env({"ARCHON_CLI_COMMAND": '["archon"]', "ARCHON_SDLC_FORGE": "forge"})
    assert env == {"ARCHON_SDLC_FORGE": "gh"}


def test_direct_engine_preflight_migrates_old_config(tmp_path, monkeypatch):
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(legacy()))
    for key, value in {
        "PORT_MODE": "real",
        "STAGE_COMMANDS": str(path),
        "TARGET_REPO": str(BASE),
        "WORK": "Accepted work",
    }.items():
        monkeypatch.setenv(key, value)
    import archon_dagu.engine as engine

    def executable(name):
        assert name != "archon", "preflight still checked Archon"
        return sys.executable

    monkeypatch.setattr(engine.shutil, "which", executable)
    preflight()


@pytest.mark.parametrize("authenticated", [True, False])
def test_original_forge_preflight_uses_gh_without_archon(tmp_path, authenticated):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "https://github.com/example/widgets.git",
        ],
        check=True,
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    log = tmp_path / "commands.jsonl"
    fake = tools / "gh"
    fake.write_text(
        f"#!{sys.executable}\n"
        + """import json,os,sys
with open(os.environ['GH_TEST_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if os.environ['GH_TEST_AUTH']=='false':
 print('not authenticated',file=sys.stderr); sys.exit(4)
print('{}')
"""
    )
    fake.chmod(0o755)
    forbidden = tools / "archon"
    forbidden.write_text(f"#!{sys.executable}\nraise SystemExit('Archon must never be invoked')\n")
    forbidden.chmod(0o755)
    env = github_env(
        {**os.environ, "ARCHON_SDLC_FORGE": "forge", "ARCHON_CLI_COMMAND": '["archon"]'}
    )
    env.update(
        PATH=str(tools) + os.pathsep + os.environ["PATH"],
        GH_TEST_LOG=str(log),
        GH_TEST_AUTH=str(authenticated).lower(),
    )
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        env.pop(name, None)
    source = BASE / "vendor/archon/.archon/workflows/sdlc/deliver/scripts/forge-check.ts"
    if os.environ.get("FORGE_TEST_RUNTIME") == "bun":
        argv = [str(BASE / ".tools/bin/bun"), str(source)]
    else:
        # Test-only Bun.spawnSync shim. CI separately runs the same test with real Bun.
        shim = tmp_path / "bun-shim.mjs"
        shim.write_text("""import {spawnSync} from 'node:child_process';
globalThis.Bun = {spawnSync(argv, options={}) {
 const r=spawnSync(argv[0],argv.slice(1),{env: options.env ?? process.env});
 if(r.error) throw r.error;
 return {exitCode:r.status,stdout:r.stdout ?? Buffer.alloc(0),stderr:r.stderr ?? Buffer.alloc(0)};
}};
""")
        argv = ["node", "--experimental-transform-types", "--import", str(shim), str(source)]
    result = subprocess.run(argv, cwd=repo, env=env, text=True, capture_output=True)
    assert (result.returncode == 0) == authenticated, result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert commands[0] == ["auth", "status", "--active", "--hostname", "github.com"]
    if authenticated:
        assert json.loads(result.stdout) == {"source": "gh"}
        assert commands[1] == ["api", "--hostname", "github.com", "repos/example/widgets"]
    else:
        assert "not authenticated" in result.stderr
        assert len(commands) == 1
