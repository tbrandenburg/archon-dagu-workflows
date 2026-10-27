#!/usr/bin/env python3
"""Execute the YAML's exact commands/dependencies locally. NOT DAGU runtime.
Used to exercise the files when the host forbids DAGU's Unix sockets.
"""

import concurrent.futures
import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

B = pathlib.Path(__file__).resolve().parents[2]


def run(file, params, parent_env=None):
    d = yaml.safe_load(pathlib.Path(file).read_text())
    if any(step.get("approval") for step in d["steps"]):
        raise ValueError(
            "Approval gates require native DAGU; the local harness cannot approve them"
        )
    for p in d.get("params", []):
        if p["name"] not in params:
            if "default" not in p:
                raise ValueError("Missing param " + p["name"])
            params[p["name"]] = p["default"]
    env = dict(parent_env or os.environ)
    outputs = {}
    waiting = []

    def render(v):
        if isinstance(v, str):
            return re.sub(
                r"\$\{(params\.([\w]+)|([\w]+))\}",
                lambda m: str(params[m[2]]) if m[2] else outputs.get(m[3], m[0]),
                v,
            )
        if isinstance(v, dict):
            return {k: render(x) for k, x in v.items()}
        if isinstance(v, list):
            return [render(x) for x in v]
        return v

    env.update(render(d.get("env", {})))
    cwd = render(d.get("working_dir", str(B)))
    logs = []

    def execute(step):
        for cond in step.get("preconditions", []):
            if render(cond["condition"]) != cond["expected"]:
                return step["id"], "skipped", ""
        if step.get("action") == "human.task":
            return step["id"], "waiting", ""
        if step.get("action") == "dag.run":
            child = render(step["with"])
            result = run(B / "workflows" / (child["dag"] + ".yaml"), child["params"], env)
            return step["id"], "succeeded", json.dumps(result)
        p = subprocess.run(
            render(step["run"]), shell=True, env=env, cwd=cwd, capture_output=True, text=True
        )
        if p.returncode:
            raise RuntimeError(step["id"] + ": " + p.stderr[-2500:])
        return step["id"], "succeeded", p.stdout

    remaining = {x["id"]: x for x in d["steps"]}
    done = set()
    try:
        while remaining:
            wave = [s for s in remaining.values() if set(s.get("depends", [])) <= done]
            if not wave:
                raise ValueError("Cycle/missing dependency")
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                futures = [pool.submit(execute, s) for s in wave]
                for f in futures:
                    sid, status, stdout = f.result()
                    step = remaining.pop(sid)
                    done.add(sid)
                    logs.append({"step": sid, "status": status, "stdout": stdout})
                    if status == "waiting":
                        waiting.append(sid)
                    if "output" in step:
                        outputs[step["output"]] = stdout.strip()
            if waiting:
                break
    except Exception:
        handler = d.get("handler_on", {}).get("failure")
        if handler:
            subprocess.run(
                render(handler["run"]), shell=True, env=env, cwd=cwd, capture_output=True, text=True
            )
        raise
    return {
        "executor": "local YAML-command harness, not DAGU",
        "file": str(file),
        "status": "waiting" if waiting else "succeeded",
        "steps": logs,
    }


if __name__ == "__main__":
    params = dict(x.split("=", 1) for x in sys.argv[2:])
    result = run(pathlib.Path(sys.argv[1]), params)
    print(json.dumps(result, indent=2))
