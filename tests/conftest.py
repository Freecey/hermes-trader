"""Test isolation: never read the developer's live .agent-config.json.

The repo-root config can legitimately be in PAPER (or LIVE) mode while a
local session runs alongside development; offline tests must not have their
behavior flipped by it — e.g. PAPER mode intercepts resolve_user_address /
fetch_account_state and breaks the hl_client tests. Point the config path at
an empty temp location BEFORE any hermes_trader import resolves it.
"""
import os
import tempfile

os.environ["HERMES_AGENT_CONFIG_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="hermes-test-config-"), "agent-config.json")
