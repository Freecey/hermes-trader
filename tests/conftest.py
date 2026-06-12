"""Test isolation: never read the developer's live .agent-config.json.

The repo-root config can legitimately be in PAPER (or LIVE) mode while a
local session runs alongside development; offline tests must not have their
behavior flipped by it — e.g. PAPER mode intercepts resolve_user_address /
fetch_account_state and breaks the hl_client tests. Point the config path at
an empty temp location BEFORE any hermes_trader import resolves it.
"""
import os
import tempfile

_TEST_STATE_DIR = tempfile.mkdtemp(prefix="hermes-test-state-")

# Config AND every state file the daemon shares: tests exercising the
# executor/DSL/paper/session-log paths must never write into a live
# session's files (observed: partial-close tests appending phantom
# "error BTC" events to the operator's real session feed).
os.environ["HERMES_AGENT_CONFIG_FILE"] = os.path.join(_TEST_STATE_DIR, "agent-config.json")
os.environ["SESSION_LOG_PATH"] = os.path.join(_TEST_STATE_DIR, "session-log.jsonl")
os.environ["HERMES_DSL_STATE_FILE"] = os.path.join(_TEST_STATE_DIR, "dsl-state.json")
os.environ["HERMES_PAPER_STATE_FILE"] = os.path.join(_TEST_STATE_DIR, "paper-state.json")
os.environ["HERMES_AGENT_MEMORY_FILE"] = os.path.join(_TEST_STATE_DIR, "agent-memory.json")
