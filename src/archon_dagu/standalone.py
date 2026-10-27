"""Source-backed standalone workflows; fixture and live transports share contracts."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

import jsonschema
import yaml

from .engine import BASE, SOURCE, load, save

VENDOR = BASE / "vendor/archon"
SOURCES = {
    "validate": "validate/archon-validate.yaml",
    "investigate": "investigate/archon-investigate.yaml",
    "plan": "plan/archon-plan-block.yaml",
    "triage": "triage/archon-triage-block.yaml",
    "implement": "implement/archon-implement.yaml",
    "standup": "../maintainer/maintainer-standup.yaml",
}


def canonical(value):
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@contextlib.contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def snapshot(repo):
    """Include untracked/ignored files, modes and links, not just git status."""
    head = git(repo, "rev-parse", "HEAD")
    files = {}
    for p in pathlib.Path(repo).rglob("*"):
        relative = p.relative_to(repo)
        if ".git" in relative.parts or (p.is_dir() and not p.is_symlink()):
            continue
        files[str(relative)] = [
            p.lstat().st_mode,
            os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest(),
        ]
    return digest([head, git(repo, "status", "--porcelain=v1", "--untracked-files=all"), files])


@contextlib.contextmanager
def forward_cancellation(proc):
    """DAGU signals the Python step; forward cancellation to its detached command."""

    def stop(signum, _frame):
        try:
            os.killpg(proc.pid, signum)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise SystemExit(128 + signum)

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def invoke(argv, cwd, env, stdin="", timeout=3600):
    """Stop a complete process group; upstream check runner also stops its children."""
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    with forward_cancellation(proc):
        try:
            stdout, stderr = proc.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
            raise TimeoutError(f"Process exceeded {timeout}s") from None
    if proc.returncode:
        raise RuntimeError(
            f"{pathlib.Path(argv[0]).name} failed ({proc.returncode}): {stderr[-4000:]}"
        )
    if stderr:
        print(stderr, file=sys.stderr, end="")
    return stdout


class Run:
    def __init__(self, root):
        self.root = pathlib.Path(root).resolve()
        self.ctx = load(self.root / "context.json")
        if not self.ctx:
            raise ValueError("Run setup first")
        self.name = self.ctx["workflow"]
        self.fixture = self.ctx["mode"] == "fixture"
        self.doc = yaml.safe_load((SOURCE / SOURCES[self.name]).read_text())
        self.nodes = {n["id"]: n for n in self.doc["nodes"]}
        self.repo = pathlib.Path(self.ctx["checkout"])
        self.config = self.ctx["config"]
        self.env = {
            **os.environ,
            "PATH": str(BASE / ".tools/bin") + os.pathsep + os.environ.get("PATH", ""),
            "ARTIFACTS_DIR": str(self.root),
            "WORKFLOW_ID": self.root.name,
        }
        if self.fixture:
            # No model/forge transport is invoked in fixture mode.
            self.env = {
                k: v
                for k, v in self.env.items()
                if not re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL", k, re.I)
            }
        self.env.setdefault("ARCHON_SDLC_FORGE", "gh")
        self.env["ARCHON_CLI_COMMAND"] = json.dumps(self.config.get("archon_argv", ["archon"]))
        self.env["ARCHON_RUN_ENV_KEYS"] = json.dumps(
            [k for k in self.env if k.startswith(("INPUTS_", "STANDALONE_"))]
            + [
                "ARTIFACTS_DIR",
                "WORKFLOW_ID",
                "ARCHON_CLI_COMMAND",
                "ARCHON_RUN_ENV_KEYS",
                "STATE_DIR",
                "TARGET_REPO",
                "WORK_INPUT",
                "SCOPE",
                "PRIOR_REPORT",
                "RELATED",
                "PUBLISH",
            ]
        )
        for key, value in self.ctx["inputs"].items():
            self.env["INPUTS_" + key.upper()] = canonical(value)

    def result(self, node):
        return load(self.root / "nodes" / (node + ".json"))

    def bindings(self, node):
        def resolve(value):
            if isinstance(value, dict) and "from" in value:
                return resolve(value["from"])
            if isinstance(value, str) and value.startswith("$INPUTS."):
                return self.ctx["inputs"][value[8:]]
            if isinstance(value, str) and value.startswith("$"):
                match = re.fullmatch(r"\$([\w-]+)\.output(?:\.(\w+))?", value)
                if not match:
                    raise ValueError("Unsupported source binding: " + value)
                data = self.result(match[1])
                return data[match[2]] if match[2] and data is not None else data
            return value

        return {key: resolve(value) for key, value in node.get("with", {}).items()}

    def check(self, value, node):
        if node.get("output_format"):
            jsonschema.Draft202012Validator(node["output_format"]).validate(value)

        def pointer(v):
            if isinstance(v, dict):
                if v.get("type") == "archon_artifact":
                    path = self.root / v["path"]
                    if (
                        v.get("run_id") != self.root.name
                        or not path.resolve().is_relative_to(self.root)
                        or not path.is_file()
                        or not path.stat().st_size
                    ):
                        raise ValueError("Missing, foreign, empty or escaping report artifact")
                for child in v.values():
                    pointer(child)
            elif isinstance(v, list):
                for child in v:
                    pointer(child)

        pointer(value)
        if (
            self.name == "plan"
            and node["id"] == "plan"
            and not value["ready"]
            and not value["open_questions"]
        ):
            raise ValueError("A blocked plan must name its questions")

    def script(self, relative, bindings=None, stdin="", timeout=120, raw=False):
        env = {
            **self.env,
            **{"INPUTS_" + k.upper(): canonical(v) for k, v in (bindings or {}).items()},
        }
        env["ARCHON_RUN_ENV_KEYS"] = json.dumps(
            sorted(
                set(json.loads(env["ARCHON_RUN_ENV_KEYS"]))
                | {k for k in env if k.startswith("INPUTS_")}
            )
        )
        argv = [*self.config["script_argv"], str(VENDOR / relative)]
        output = invoke(argv, self.repo, env, stdin, timeout)
        return output.rstrip("\n") if raw else json.loads(output)

    def agent(self, node, sid):
        if self.fixture:
            spec = self.ctx["fixture"]
            if sid in spec.get("fail", []):
                raise RuntimeError("Fixture injected failure: " + sid)
            if self.name == "standup":
                return spec["agents"]["synthesize"]
            result = spec["agents"][sid if sid in spec["agents"] else node["id"]]
            # Resolve fixture-only run IDs before certifying the original schema.
            result = json.loads(json.dumps(result).replace("$RUN_ID", self.root.name))
            for relative, text in spec.get("artifacts", {}).items():
                path = self.root / relative
                if not path.resolve().is_relative_to(self.root):
                    raise ValueError("Fixture artifact escapes state directory")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            return result
        prompt = (BASE / "prompts/standalone" / f"{self.name}-{node['id']}.md").read_text()
        values = {**self.ctx["inputs"], **self.bindings(node)}
        substitutions = {"$INPUTS." + k: canonical(v) for k, v in values.items()}
        substitutions.update(
            {
                "$ARCHON_CLI_COMMAND": self.env["ARCHON_CLI_COMMAND"],
                "$ARTIFACTS_DIR": str(self.root),
                "$WORKFLOW_ID": self.root.name,
                "$ARGUMENTS": self.ctx["inputs"].get("work")
                or self.ctx["inputs"].get("target")
                or self.ctx["inputs"].get("scope", ""),
                "$LOOP_PREV_OUTPUT": canonical(
                    self.result("implement_" + str(int(sid.split("_")[-1]) - 1)) or ""
                )
                if self.name == "implement"
                else "",
            }
        )
        for key in self.nodes:
            substitutions["$" + key + ".output"] = canonical(self.result(key))
        # One pass: operator text containing tokens must never be expanded again.
        prompt = re.sub(
            "|".join(re.escape(k) for k in sorted(substitutions, key=len, reverse=True)),
            lambda m: substitutions[m[0]],
            prompt,
        )
        prompt += "\n\nDAGU bound inputs (authoritative):\n" + json.dumps(values)
        if node.get("output_format"):
            prompt += (
                "\nReturn exactly one JSON object on stdout matching this schema; no envelope or Markdown fences:\n"
                + json.dumps(node["output_format"])
            )
        (self.root / "prompts").mkdir(exist_ok=True)
        (self.root / "prompts" / (sid + ".md")).write_text(prompt)
        before = (
            snapshot(self.repo)
            if node.get("mutates_checkout") is False or self.name in ("validate", "standup")
            else None
        )
        try:
            raw = invoke(
                self.config["agent_argv"],
                self.repo,
                {**self.env, "STANDALONE_STAGE": sid},
                prompt,
                self.config.get("agent_timeout_seconds", 3600),
            )
        finally:
            if before is not None and before != snapshot(self.repo):
                raise ValueError("Advisory agent modified its isolated checkout")
        return json.loads(raw) if node.get("output_format") else raw

    def stage(self, sid):
        with lock(self.root / "locks" / (sid + ".lock")):
            node_id = "implement" if self.name == "implement" else sid
            node = self.nodes[node_id]
            result_path = self.root / "nodes" / (sid + ".json")
            dependencies = node.get("depends_on", [])
            for dependency in dependencies:
                if not (self.root / "nodes" / (dependency + ".json")).exists():
                    raise ValueError("Missing prerequisite: " + dependency)
            if self.name == "implement" and sid != "implement_1":
                previous_path = (
                    self.root
                    / "nodes"
                    / ("implement_" + str(int(sid.split("_")[-1]) - 1) + ".json")
                )
                if not previous_path.exists():
                    raise ValueError("Missing preceding implementation turn")
            if result_path.exists():
                cached = self.result(sid)
                if cached is not None:
                    self.check(cached, node)
                return cached
            if (self.root / "report.json").exists():
                raise ValueError("Run is terminal; use a new state directory")
            started = self.root / "journal" / (sid + ".started")
            if started.exists():
                raise ValueError(
                    f"{sid} has an interrupted/failed attempt. Reconcile effects before retrying; use a new run or explicitly clear its journal entry."
                )
            save(started, {"stage": sid})
            if self.name == "implement" and sid != "implement_1":
                previous = self.result("implement_" + str(int(sid.split("_")[-1]) - 1))
                if previous["done"]:
                    save(result_path, previous)
                    return previous
            if sid == "classify" and self.result("run")["status"] != "red":
                value = None
            elif "command" in node or "loop" in node:
                value = self.agent(node, sid)
            elif self.name == "standup":
                if sid == "persist":
                    value = self.script(
                        ".archon/scripts/maintainer-standup-persist.ts",
                        stdin=self.result("synthesize"),
                    )
                elif self.fixture and sid != "read-context":
                    value = self.ctx["fixture"]["facts"][sid]
                else:
                    value = self.script(
                        ".archon/scripts/maintainer-standup-" + sid + ".ts",
                        timeout=node.get("timeout", 120000) / 1000,
                    )
            else:
                bindings = self.bindings(node)
                if self.fixture and self.name == "triage" and sid == "verdict":
                    bindings["publish"] = "false"
                relative = (
                    ".archon/workflows/sdlc/" + self.name + "/scripts/" + node["script"] + ".ts"
                )
                if (
                    sid == "result"
                    and self.name == "validate"
                    and self.result("run").get("status") == "incomplete"
                ):
                    bindings["run"] = self.result("run")
                try:
                    value = self.script(
                        relative, bindings, timeout=node.get("timeout", 120000) / 1000
                    )
                except TimeoutError:
                    if self.name != "validate" or sid != "run":
                        raise
                    value = {
                        "status": "incomplete",
                        "summary": "Check runner exceeded its two-hour limit; see validation.md.",
                    }
            if value is not None:
                self.check(value, node)
            save(result_path, value)
            return value

    def release(self):
        if self.name == "standup" and not self.fixture:
            claim = pathlib.Path(self.ctx["standup_claim"])
            if load(claim) == {"run": str(self.root)}:
                claim.unlink(missing_ok=True)

    def report(self, failed=False):
        previous = load(self.root / "report.json")
        if previous and not failed:
            self.release()
            return previous
        final = "implement_5" if self.name == "implement" else self.doc.get("returns", "persist")
        result = self.result(final)
        if not failed:
            if result is None:
                raise ValueError("Final stage has not completed")
            self.check(result, self.nodes["implement" if self.name == "implement" else final])
        outcome = (
            result.get(self.doc.get("outcome_field", ""), True)
            if isinstance(result, dict)
            else False
        )
        capped = self.name == "implement" and result is not None and not result["done"]
        if capped:
            outcome = False
        needs_decision = False
        if result is not None and not failed:
            if self.name == "investigate":
                needs_decision = result["verdict"] == "inconclusive"
            elif self.name == "triage":
                needs_decision = result["contract"] in ("BLOCKED", "NEEDS_CONTRACT_WORK")
            elif self.name in ("plan", "implement"):
                needs_decision = not outcome
        report = {
            "workflow": self.name,
            "mode": self.ctx["mode"],
            "lifecycle": "failed" if failed else "completed",
            "outcome": False if failed else outcome,
            "reason": "failed" if failed else "iteration_cap" if capped else "completed",
            "needs_decision": needs_decision,
            "result": result,
            "checkout": str(self.repo),
            "external_effects": "simulated"
            if self.fixture
            else "live; agent/forge behavior experimental",
            "source_commit": json.loads((BASE / "STANDALONE_SOURCE.json").read_text())["commit"],
        }
        save(self.root / "report.json", report)
        self.release()
        return report


def initialize(root, environ=None):
    env = environ or os.environ
    root = pathlib.Path(root).resolve()
    name, mode = env["STANDALONE_WORKFLOW"], env["STANDALONE_MODE"]
    if name not in SOURCES or mode not in ("fixture", "live"):
        raise ValueError("Unknown workflow/mode")
    config_path = pathlib.Path(env.get("STANDALONE_CONFIG", "config/standalone.json"))
    if not config_path.is_absolute():
        config_path = BASE / config_path
    config = json.loads(config_path.read_text())
    fixture = None
    if mode == "fixture":
        path = pathlib.Path(env["STANDALONE_FIXTURE"])
        if not path.is_absolute():
            path = BASE / path
        fixture = json.loads(path.read_text())
        if fixture["workflow"] != name:
            raise ValueError("Fixture belongs to another workflow")
    inputs = {
        "target": env.get("WORK_INPUT", ""),
        "work": env.get("WORK_INPUT", ""),
        "scope": env.get("SCOPE", ""),
        "report": env.get("PRIOR_REPORT", ""),
        "related": env.get("RELATED", "[]"),
        "publish": env.get("PUBLISH", "false"),
    }
    if inputs["publish"] not in ("true", "false"):
        raise ValueError("publish must be true or false")
    identity = digest([name, mode, config, fixture, inputs, env.get("TARGET_REPO", "")])
    root.mkdir(parents=True, exist_ok=True)
    with lock(root / "locks/setup.lock"):
        existing = load(root / "context.json")
        if existing:
            if existing["identity"] != identity:
                raise ValueError(
                    "State directory belongs to different inputs/config; start a new run"
                )
            return
        if (root / "setup.started").exists():
            raise ValueError("Interrupted setup; inspect checkout/claim before starting a new run")
        for key in ("agent_argv", "script_argv"):
            if (
                not isinstance(config[key], list)
                or not config[key]
                or not all(isinstance(x, str) and x for x in config[key])
            ):
                raise ValueError(key + " must be a nonempty argv array")
        # Resolve the verified locally installed Bun without mutating config/provenance.
        if config["script_argv"][0] == "bun" and (BASE / ".tools/bin/bun").exists():
            config["script_argv"][0] = str(BASE / ".tools/bin/bun")
        if not shutil.which(config["script_argv"][0]):
            raise ValueError("Bun is required for original scripts: run make tools")
        repo = pathlib.Path(env.get("TARGET_REPO", "")).resolve()
        claim = None
        if mode == "live":
            if (
                name in ("investigate", "plan", "triage", "implement")
                and not inputs["work"].strip()
            ):
                raise ValueError(
                    "Live workflow requires explicit input; no Archon trigger message is available"
                )
            if not env.get("TARGET_REPO"):
                raise ValueError("Live runs require an explicit repo path")
            git(repo, "rev-parse", "--show-toplevel")
            if not shutil.which(config["agent_argv"][0]):
                raise ValueError("Configured agent CLI is not installed")
            if name == "standup" and not config.get("standup_in_place"):
                raise ValueError(
                    "Standup fetches/pulls and persists local state; set standup_in_place=true explicitly"
                )
            if name == "standup" and root.is_relative_to(repo):
                raise ValueError("Standup state_dir must be outside its in-place checkout")
            if name != "standup" and git(repo, "status", "--porcelain"):
                raise ValueError("Live source checkout must be clean before isolation")
        save(root / "setup.started", {"workflow": name, "mode": mode})
        if mode == "fixture":
            checkout = root / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            for key, value in [("user.email", "fixture@example.invalid"), ("user.name", "Fixture")]:
                git(checkout, "config", key, value)
            git(checkout, "commit", "--allow-empty", "-qm", "Fixture baseline")
            if fixture.get("prior_state"):
                save(checkout / ".archon/maintainer-standup/state.json", fixture["prior_state"])
        elif name == "standup":
            checkout = repo
            common = pathlib.Path(
                git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
            )
            claim = common / "archon-dagu-standup.json"
            with claim.open("x") as handle:
                json.dump({"run": str(root)}, handle)
        else:
            checkout = root / "checkout"
            args = ["worktree", "add"]
            args += ["-b", "dagu/implement-" + root.name] if name == "implement" else ["--detach"]
            git(repo, *args, str(checkout), "HEAD")
        save(
            root / "context.json",
            {
                "identity": identity,
                "workflow": name,
                "mode": mode,
                "inputs": inputs,
                "config": config,
                "fixture": fixture,
                "checkout": str(checkout),
                "standup_claim": str(claim) if claim else None,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "stage", "report", "failure"])
    parser.add_argument("stage", nargs="?")
    args = parser.parse_args()
    root = os.environ["STATE_DIR"]
    if args.action == "init":
        initialize(root)
    else:
        run = Run(root)
        if args.action == "stage":
            run.stage(args.stage)
        else:
            report = run.report(failed=args.action == "failure")
            print(str(report["needs_decision"]).lower())


if __name__ == "__main__":
    main()
