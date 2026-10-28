"""DAGU runtime settings for the pinned scripts' native GitHub CLI path."""

import copy


def github_config(config):
    """Migrate only this repository's built-in live transport, not custom adapters."""
    result = copy.deepcopy(config)
    commands = result.get("commands", {})
    builtin = bool(commands) and all(
        isinstance(argv, list) and len(argv) == 3 and argv[1:] == ["-m", "archon_dagu.live_stage"]
        for argv in commands.values()
    )
    if builtin:
        if result.get("forge_source", "gh") != "gh":
            raise ValueError(
                "DAGU delivery supports forge_source=gh; Archon plugins are not required"
            )
        result["forge_source"] = "gh"
        result["requires"] = [item for item in result.get("requires", []) if item != "archon"]
        result.pop("archon_argv", None)
    return result


def github_env(environ):
    """Prevent inherited Archon plugin settings from changing the GitHub path."""
    env = dict(environ)
    env["ARCHON_SDLC_FORGE"] = "gh"
    env.pop("ARCHON_CLI_COMMAND", None)
    return env


RUNTIME_GUIDANCE = """
DAGU runtime instructions (override Archon-specific invocation examples above):
This delivery runs in DAGU, not the Archon application. The forge source is gh.
Use qualified GitHub CLI commands for forge reads/writes allowed by this stage.
No Archon CLI, host, forge plugin, workflow service or state service is available.
Never invoke archon commands. Rerun guidance must refer to the appropriate DAGU
simple-real/detailed-real delivery entrypoint with a new state directory and the
accepted work/PR inputs, rather than an Archon workflow command.
"""
