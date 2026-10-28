"""Fresh-checkout configuration, diagnostics and explicit live delivery commands."""

import argparse
import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import uuid

from archon_dagu.engine import BASE, load, save
from archon_dagu.runtime import github_config

VARIANTS = ("simple-real", "detailed-real")


def config_path(value=""):
    return (
        pathlib.Path(value).expanduser().resolve() if value else BASE / "config/commands.local.json"
    )


def configuration(path):
    if not path.exists() and path != BASE / "config/commands.local.json":
        raise ValueError(f"Selected config does not exist: {path}")
    selected = path if path.exists() else BASE / "config/commands.json"
    config = github_config(load(selected))
    if config.get("test_transport"):
        raise ValueError("Live commands refuse test_transport; use fixture-demo for mock effects")
    argv = config.get("agent_argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise ValueError("agent_argv must be a nonempty argv array")
    return selected, config


def configure(path, model, agent):
    if not model or "/" not in model or any(c.isspace() for c in model):
        raise ValueError("Set MODEL to an available provider/model identifier from opencode models")
    if not agent.strip():
        raise ValueError("AGENT must not be empty")
    _, config = configuration(path)
    config["agent_argv"] = [
        "python",
        "-m",
        "archon_dagu.opencode",
        "--agent",
        agent,
        "--model",
        model,
    ]
    config["requires"] = list(dict.fromkeys([*config.get("requires", []), "opencode"]))
    save(path, config)
    print(f"Saved agent=opencode, agent profile={agent}, model={model} to {path}")


def doctor(path, *, agent_only=False):
    selected, config = configuration(path)
    argv = config["agent_argv"]
    if config.get("forge_source") == "gh" and not agent_only:
        print("Runtime: DAGU; forge: GitHub CLI (gh). Archon installation is not required.")
    print(f"Config: {selected}\nAgent command: {shlex.join(argv)}", flush=True)
    needed = [argv[0]]
    if "archon_dagu.opencode" in argv:
        needed.append("opencode")
        if "--model" not in argv:
            print(
                "Model: inherited from OpenCode; use configure-agent MODEL=provider/model to pin it"
            )
    if not agent_only:
        needed += [*config.get("requires", []), "node", "git"]
        if not shutil.which("dagu") and not (BASE / ".tools/bin/dagu").is_file():
            needed.append("dagu")
    missing = [name for name in dict.fromkeys(needed) if not shutil.which(name)]
    for name in missing:
        hint = {
            "opencode": "install OpenCode (https://opencode.ai/docs/), then opencode auth login",
            "bun": "run make tools",
            "dagu": "run make tools",
            "gh": "install GitHub CLI, then gh auth login",
            "node": "install Node.js 24",
        }.get(name, "install it or correct the selected command config")
        print(f"Missing {name}: {hint}", file=sys.stderr)
    if missing:
        raise ValueError("Missing prerequisites: " + ", ".join(missing))
    print("Executables found. Authentication/model access is unverified; run agent-smoke.")
    return selected, config


def smoke(path):
    _, config = doctor(path, agent_only=True)
    directory = BASE / ".runs/agent-smoke" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    print(f"REAL AGENT SMOKE: {directory}; no delivery or forge stage is invoked.", flush=True)
    prompt = (
        'Do not use tools or change files. Return exactly {"ok":true} without Markdown or prose.'
    )
    process = subprocess.Popen(
        config["agent_argv"],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=directory,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(prompt, timeout=120)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            pass
        raise ValueError(
            "Agent smoke interrupted or timed out; its process group was stopped"
        ) from None
    if process.returncode:
        raise ValueError(
            "Agent smoke failed; inspect provider authentication/model diagnostics above"
        )
    try:
        answer = json.loads(stdout)
    except ValueError:
        raise ValueError("Agent smoke did not return a bare JSON answer") from None
    if answer != {"ok": True}:
        raise ValueError("Agent smoke returned an unexpected answer")
    save(
        directory / "report.json",
        {"agent_invoked": True, "forge_stages_invoked": False, "result": answer},
    )
    print("Real agent transport passed. This does not test delivery or forge permissions.")


def deliver(path, variant, repo, work_file, state):
    if variant not in VARIANTS:
        raise ValueError("VARIANT must be simple-real or detailed-real")
    if not repo or not work_file:
        raise ValueError("Set REPO to an isolated checkout and WORK_FILE to the accepted work file")
    checkout = pathlib.Path(repo).expanduser().resolve()
    work = pathlib.Path(work_file).expanduser().resolve().read_text().strip()
    if not work:
        raise ValueError("WORK_FILE must contain accepted work")
    selected, config = doctor(path)
    state_dir = (
        pathlib.Path(state).expanduser().resolve()
        if state
        else (BASE / ".runs/live" / f"{variant}-{uuid.uuid4().hex[:12]}")
    )
    if state_dir.exists():
        raise ValueError("STATE_DIR must be new; inspect prior effects before retrying")
    # Snapshot the exact selected config, including the built-in fallback, for this run.
    state_dir.mkdir(parents=True)
    saved_config = state_dir / "commands.json"
    save(saved_config, config)
    binary = shutil.which("dagu") or str(BASE / ".tools/bin/dagu")
    print(
        f"LIVE DELIVERY: {variant}\nCheckout: {checkout}\nState: {state_dir}\n"
        f"Config: {selected}\nREAL agents and configured forge operations; no merge.",
        flush=True,
    )
    subprocess.run(
        [
            binary,
            "--dagu-home",
            str(BASE / ".runs/dagu"),
            "start",
            str(BASE / "workflows" / (variant + ".yaml")),
            "--",
            f"project_dir={BASE}",
            f"state_dir={state_dir}",
            f"repo={checkout}",
            f"commands={saved_config}",
            f"work={work}",
        ],
        cwd=BASE,
        check=True,
    )


def main():
    os.environ["PATH"] = str(BASE / ".tools/bin") + os.pathsep + os.environ.get("PATH", "")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=["configure-agent", "doctor", "agent-smoke", "deliver"])
    parser.add_argument("--config", default=os.environ.get("COMMANDS", ""))
    parser.add_argument("--model", default=os.environ.get("MODEL", ""))
    parser.add_argument("--agent", default=os.environ.get("AGENT", "build"))
    parser.add_argument("--variant", default=os.environ.get("VARIANT", "simple-real"))
    parser.add_argument("--repo", default=os.environ.get("REPO", ""))
    parser.add_argument("--work-file", default=os.environ.get("WORK_FILE", ""))
    parser.add_argument("--state-dir", default=os.environ.get("STATE_DIR", ""))
    args = parser.parse_args()
    path = config_path(args.config)
    try:
        match args.target:
            case "configure-agent":
                configure(path, args.model, args.agent)
            case "doctor":
                doctor(path)
            case "agent-smoke":
                smoke(path)
            case "deliver":
                deliver(path, args.variant, args.repo, args.work_file, args.state_dir)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
