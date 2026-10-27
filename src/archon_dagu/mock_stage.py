#!/usr/bin/env python3
"""Explicit test transport. Never invokes agent/forge commands."""

import json
import sys

from .engine import fixture_output

r = json.load(sys.stdin)
print(json.dumps(fixture_output(r["stage"], r["fixture"])))
