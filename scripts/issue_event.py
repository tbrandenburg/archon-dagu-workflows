"""Normalize a trusted GitHub issues/opened event into explicit DAGU parameters.

This is a file/stdin adapter, not an HTTP webhook/authentication service.
"""

import argparse
import json
import re
from pathlib import Path


def normalize(payload, repository):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Expected repository must be owner/name")
    if payload.get("repository", {}).get("full_name") != repository:
        raise ValueError("Event repository does not match the configured repository")
    issue = payload.get("issue")
    if payload.get("action") != "opened" or not issue or "pull_request" in issue:
        return {"eligible": False, "reason": "Only issue-opened events are eligible"}
    number = issue.get("number")
    if type(number) is not int or number < 1:
        raise ValueError("Issue number must be positive")
    return {"eligible": True, "params": {"repository": repository, "issue_number": str(number)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = normalize(json.loads(args.event.read_text()), args.repository)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value))


if __name__ == "__main__":
    main()
