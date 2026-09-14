#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LingoFuse LLM Proxy Tool Bridge (LTB) - v2.1

Role
----
A LingoFuse SERVICE that registers as LLM_Service on ipc:llm_service and
forwards each generate request to an OpenAI-compatible HTTP backend, with
OPTIONAL server-side tool execution via `language_middleware`.

Sibling of `llm_proxy.py` (v1.8, pure text proxy). Differences:

    llm_proxy.py       - pure text passthrough, 129+ backends
    llm_proxy_tool.py  - adds MCP tool discovery + server-side execution

Design principles
-----------------
1. Zero client changes.
   The client (`llm_test.py`, Pascal clients, any LingoFuse client) sends
   the same `generate` request as always. It does NOT need to know about
   tools, tool_calls, or tool_results. LTB handles everything internally
   and returns a normal `chunk` / `think` / `finish` stream.

2. Server-side tool execution.
   When the backend returns `tool_calls`, LTB executes them via
   `language_middleware.call_tool()` on the server. It then feeds the
   results back to the backend as `role=tool` messages and continues
   the conversation until the backend produces a final text answer.

3. Default: pure-text compatibility.
   If the MCP tools are unavailable (no beacon, no tool provider, or
   `--no-tools`), LTB behaves exactly like `llm_proxy.py`: the payload
   sent to the backend is byte-for-byte identical.

4. Bounded multi-round protocol.
   A single `generate` call may trigger up to `--max-tool-rounds`
   backend round-trips. The last round is always a forced text-answer
   round with no tools injected, so the loop always terminates. A
   per-call cap on total tool calls and total tool-result characters
   adds a second layer of protection against runaway models.

5. Server-side pre-connection (race fix).
   `Server.start()` internally calls `LF_PrepareDone()`, which starts
   the LingoFuse simulated main thread. If `language_middleware` were to
   connect AFTER that, its own `LF_PrepareDone()` would return 0 (main
   thread already active) and `_connect()` would mark the connection as
   failed. LTB therefore pre-connects the middleware BEFORE
   `Server.start()`.

6. Silent during normal operation.
   At INFO level and above, the service logs only startup, shutdown,
   session lifecycle, and errors. Every per-round and per-tool detail
   is logged at DEBUG level. Long-running deployments will not fill
   their consoles with per-request noise.

7. Global configuration only.
   Environment variables and command-line arguments are read exactly
   once at startup (inside `parse_args` / `_init_global_config`).
   Runtime code reads exclusively from the module-level `CONFIG`
   object and never touches `os.environ` or `sys.argv` again.

Command-Line Reference
======================

LingoFuse Service
-----------------
  --endpoint ADDRESS
      LingoFuse service endpoint. The client connects here to send
      `generate` requests. Format: `ipc:name` for IPC (same host),
      `host:port` for TCP (cross host).
      Default: ipc:llm_service
      Env:     LLM_PROXY_ENDPOINT

  --app-name NAME
      LingoFuse application name. Must match the name the client uses
      to look up this service.
      Default: LLM_Service
      Env:     LLM_PROXY_APP_NAME

  --notify-api NAME
      Notify API name used for streaming events back to the client.
      The client must register a notify callback with this exact name.
      Default: llm_stream
      Env:     LLM_PROXY_NOTIFY_API

Backend (OpenAI-compatible HTTP)
--------------------------------
  --backend-url URL
      Base URL of the OpenAI-compatible backend. The proxy appends
      `/chat/completions` to this URL.
      Default: http://127.0.0.1:12345/v1
      Env:     LLM_PROXY_BACKEND_URL
      Examples:
        LM Studio:  http://127.0.0.1:1234/v1
        Ollama:     http://127.0.0.1:11434/v1
        vLLM:       http://127.0.0.1:8000/v1
        DeepSeek:   https://api.deepseek.com/v1

  --backend-model ID
      Model id sent in the request body. Empty = auto-discover via
      `/v1/models`.
      Default: (empty)
      Env:     LLM_PROXY_BACKEND_MODEL

  --backend-key KEY
      API key / token sent in the auth header.
      Default: lm-studio
      Env:     LLM_PROXY_BACKEND_KEY

  --backend-key-file PATH
      Read the API key from a file. Overrides --backend-key.
      Env:     LLM_PROXY_BACKEND_KEY_FILE

  --backend-auth-header NAME
      HTTP header carrying the token.
      Default: Authorization
      Env:     LLM_PROXY_BACKEND_AUTH_HEADER

  --backend-auth-scheme PREFIX
      Token prefix. Empty string means raw token.
      Default: Bearer
      Env:     LLM_PROXY_BACKEND_AUTH_SCHEME

  --backend-extra-headers JSON
      Additional HTTP headers as a JSON object.
      Default: {} (no extra headers)
      Env:     LLM_PROXY_BACKEND_EXTRA_HEADERS
      Example: '{"HTTP-Referer": "https://example.com"}'

  --backend-timeout SECONDS
      HTTP read timeout for backend streaming requests.
      Default: 300
      Env:     LLM_PROXY_BACKEND_TIMEOUT

Sessions
--------
  --max-sessions N
      Maximum concurrent sessions. Requests that create sessions
      beyond this limit are rejected.
      Default: 1024
      Env:     LLM_PROXY_MAX_SESSIONS

  --max-history N
      Maximum number of messages retained per session (any role).
      Oldest messages are dropped first, but an assistant.tool_calls
      message and its matching role=tool replies are never separated.
      Default: 512
      Env:     LLM_PROXY_MAX_HISTORY

  --max-history-chars N
      Maximum total character count of the message history per
      session. Prevents unbounded growth from accumulated tool
      results in long-lived sessions.
      Default: 200000
      Env:     LLM_PROXY_MAX_HISTORY_CHARS

  --session-timeout SECONDS
      Idle timeout for sessions. A session that has not seen any
      `generate` request for this long is reclaimed.
      Default: 1800
      Env:     LLM_PROXY_SESSION_TIMEOUT

Tools (MCP)
-----------
  --enable-tools / --no-tools
      Enable or disable all tool-related behavior. When disabled,
      the proxy behaves exactly like llm_proxy.py.
      Default: enabled
      Env:     LLM_PROXY_ENABLE_TOOLS

  --mcp-endpoint ADDRESS
      LingoFuse endpoint of the MCP tool provider (beacon).
      Default: ipc:agent
      Env:     LLM_PROXY_MCP_ENDPOINT

  --mcp-timeout MS
      Timeout for MCP tool discovery and tool invocation calls.
      Default: 5000
      Env:     LLM_PROXY_MCP_TIMEOUT

  --mcp-reg-agent-app NAME
      Registration agent app name used by this proxy. MUST be
      different from the one used by mcp_api_tool.py (which uses
      `reg_agent`), so the two can run simultaneously.
      Default: llm_proxy_agent
      Env:     LLM_PROXY_MCP_REG_AGENT_APP

  --mcp-tool-provider-app NAME
      App name of the tool provider (the Pascal backend).
      Default: agent_main_app
      Env:     LLM_PROXY_MCP_TOOL_PROVIDER_APP

  --max-tool-rounds N
      Maximum number of model<->tool round trips per `generate` call.
      Higher values allow longer tool chains but also risk longer
      waits if the model loops. The last round is always a forced
      text-answer round.
      Default: 100
      Env:     LLM_PROXY_MAX_TOOL_ROUNDS

  --max-total-tool-calls N
      Maximum number of tool calls executed in a single `generate`
      call, regardless of how many rounds they span. Reaching this
      cap forces the loop to switch to the final text-answer round.
      Default: 50
      Env:     LLM_PROXY_MAX_TOTAL_TOOL_CALLS

  --max-tools-per-round N
      Maximum number of tool calls processed from a single backend
      response (OpenAI allows batch tool_calls).
      Default: 10
      Env:     LLM_PROXY_MAX_TOOLS_PER_ROUND

  --max-tool-result-chars N
      Maximum length of a single tool result string. Longer results
      are truncated before being appended to history.
      Default: 8000
      Env:     LLM_PROXY_MAX_TOOL_RESULT_CHARS

  --max-total-tool-result-chars N
      Maximum total character count of all tool results in a single
      `generate` call. Prevents unbounded growth from looping
      tool calls.
      Default: 200000
      Env:     LLM_PROXY_MAX_TOTAL_TOOL_RESULT_CHARS

Logging
-------
  --log-level LEVEL
      Log verbosity: DEBUG, INFO, WARNING, ERROR.
      At INFO and above, the service is silent during normal
      operation; only startup, shutdown, session lifecycle, and
      errors are logged. Use DEBUG to see per-round and per-tool
      details.
      Default: INFO
      Env:     LLM_PROXY_LOG_LEVEL

Relationship with siblings
--------------------------
    llm_service.py      - local inference (llama.cpp)
    llm_proxy.py        - pure text proxy
    llm_proxy_tool.py   - proxy with server-side tools (this file)
    mcp_api_tool.py     - MCP tool gateway (Host-side)

llm_proxy_tool.py and mcp_api_tool.py CAN coexist: they use different
`reg_agent_app_name` values (`llm_proxy_agent` vs `reg_agent`) and
share the same beacon on `ipc:agent`.

All three LLM services share the default endpoint `ipc:llm_service`
and app name `LLM_Service`, so only ONE may run at any time unless
you override `--endpoint` and `--app-name`.

All comments and log messages are in English.
"""

import os
import sys
import json
import time
import uuid
import signal
import socket
import logging
import argparse
import threading
import atexit
import ssl
import http.client
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Iterator

try:
    import requests
except ImportError:
    print("[FATAL] 'requests' is required for /v1/models probe. "
          "Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_SCRIPT_DIR, "..")))

from lingofuse import Server, set_option, check_app
from lingofuse.core import DataHandle
from lingofuse._lf_native import LF_Sequenced_Notify, LF_WriteBuffer

# ---- Optional: language_middleware for MCP tool discovery ----
#
# `language_middleware` is imported here. If it is missing (e.g. the
# project `src/` directory is not on PYTHONPATH), LTB silently falls
# back to pure-text proxy mode. It never crashes on a missing import.
try:
    from language_middleware import (
        LanguageMiddleware,
        LanguageConnectionError,
        LanguageCallError,
    )
    _HAS_MIDDLEWARE = True
except ImportError:
    _HAS_MIDDLEWARE = False
    LanguageMiddleware = None
    LanguageConnectionError = Exception
    LanguageCallError = Exception


# ----------------------------------------------------------------------
# Frozen-executable detection and help-text helpers
# ----------------------------------------------------------------------
def is_frozen_exe() -> bool:
    """Return True if running from a PyInstaller / Nuitka frozen executable."""
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')


def get_invocation_name() -> str:
    """Program name shown as `prog=` in argparse help."""
    if is_frozen_exe():
        return os.path.basename(sys.executable)
    return os.path.basename(os.path.abspath(__file__))


def get_example_invocation() -> str:
    """Command prefix used in the `--help` examples."""
    if is_frozen_exe():
        return os.path.basename(sys.executable)
    return f"{os.path.basename(sys.executable)} {os.path.basename(os.path.abspath(__file__))}"


# ----------------------------------------------------------------------
# Built-in defaults
# ----------------------------------------------------------------------
DEFAULT_ENDPOINT = "ipc:llm_service"
DEFAULT_APP_NAME = "LLM_Service"
DEFAULT_NOTIFY_API = "llm_stream"

DEFAULT_BACKEND_URL = "http://127.0.0.1:12345/v1"
DEFAULT_BACKEND_MODEL = ""
DEFAULT_BACKEND_KEY = "lm-studio"
DEFAULT_BACKEND_KEY_FILE = ""
DEFAULT_BACKEND_AUTH_HEADER = "Authorization"
DEFAULT_BACKEND_AUTH_SCHEME = "Bearer"
DEFAULT_BACKEND_EXTRA_HEADERS = ""
DEFAULT_BACKEND_TIMEOUT = 300

DEFAULT_MAX_HISTORY = 512
DEFAULT_MAX_HISTORY_CHARS = 200000
DEFAULT_MAX_SESSIONS = 1024
DEFAULT_SESSION_TIMEOUT = 1800

DEFAULT_LOG_LEVEL = "INFO"

# ---- LTB / MCP defaults ----
DEFAULT_ENABLE_TOOLS = True
DEFAULT_MCP_ENDPOINT = "ipc:agent"
DEFAULT_MCP_TIMEOUT_MS = 5000
DEFAULT_MCP_REG_AGENT_APP = "llm_proxy_agent"   # distinct from mcp_api_tool
DEFAULT_MCP_TOOL_PROVIDER_APP = "agent_main_app"
DEFAULT_MCP_AGENT_MAIN_API = "agent_main"
DEFAULT_MCP_AGENT_LOG_API = "agent_log"
DEFAULT_MAX_TOOL_ROUNDS = 100
DEFAULT_MAX_TOTAL_TOOL_CALLS = 50
DEFAULT_MAX_TOOL_RESULT_CHARS = 8000
DEFAULT_MAX_TOTAL_TOOL_RESULT_CHARS = 200000
DEFAULT_MAX_TOOLS_PER_ROUND = 10

# Number of consecutive failures before a re-attempt on the MCP
# middleware connection is allowed. Prevents hammering the beacon
# when the tool provider is down.
DEFAULT_MCP_RETRY_INTERVAL_SEC = 30.0

# Options keys accepted from clients and forwarded to the backend.
# Used only for DEBUG-level "ignored key" logging.
_FORWARDED_OPTION_KEYS = frozenset((
    "max_tokens", "temperature", "top_p", "top_k", "repeat_penalty",
    "tools", "tool_choice",
))


# ----------------------------------------------------------------------
# API capability matrix
# ----------------------------------------------------------------------
API_CAPABILITIES: Dict[str, int] = {
    # ---- Call APIs ----
    "generate":           1,
    "create_session":     1,
    "close_session":      1,
    "cancel_session":     1,
    "list_sessions":      1,
    "set_system_message": 0,   # llm_service-only
    "health":             1,

    # ---- Notify API ----
    "llm_stream":         1,

    # ---- LTB-specific capability flags ----
    "tools":              1,
    "tool_calls":         1,
    "tool_results":       1,
}

SERVER_KIND = "proxy"


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO),
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("llm_proxy_tool")


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
class ProxyConfig:
    """
    Process-wide configuration. Populated exactly once at startup by
    `_init_global_config()`. All runtime code reads from this object
    and never touches `os.environ` or `sys.argv` after that point.
    """

    def __init__(self) -> None:
        # ---- LingoFuse service ----
        self.endpoint: str = DEFAULT_ENDPOINT
        self.app_name: str = DEFAULT_APP_NAME
        self.notify_api: str = DEFAULT_NOTIFY_API

        # ---- Backend HTTP ----
        self.backend_url: str = DEFAULT_BACKEND_URL
        self.backend_model: str = DEFAULT_BACKEND_MODEL
        self.backend_key: str = DEFAULT_BACKEND_KEY
        self.backend_key_file: str = DEFAULT_BACKEND_KEY_FILE
        self.backend_auth_header: str = DEFAULT_BACKEND_AUTH_HEADER
        self.backend_auth_scheme: str = DEFAULT_BACKEND_AUTH_SCHEME
        self.backend_extra_headers: Dict[str, str] = {}
        self.backend_timeout: int = DEFAULT_BACKEND_TIMEOUT

        # ---- Sessions ----
        self.max_history: int = DEFAULT_MAX_HISTORY
        self.max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS
        self.max_sessions: int = DEFAULT_MAX_SESSIONS
        self.session_timeout: int = DEFAULT_SESSION_TIMEOUT

        # ---- Logging ----
        self.log_level: str = DEFAULT_LOG_LEVEL

        # ---- LTB / MCP ----
        self.enable_tools: bool = DEFAULT_ENABLE_TOOLS
        self.mcp_endpoint: str = DEFAULT_MCP_ENDPOINT
        self.mcp_timeout_ms: int = DEFAULT_MCP_TIMEOUT_MS
        self.mcp_reg_agent_app: str = DEFAULT_MCP_REG_AGENT_APP
        self.mcp_tool_provider_app: str = DEFAULT_MCP_TOOL_PROVIDER_APP
        self.mcp_agent_main_api: str = DEFAULT_MCP_AGENT_MAIN_API
        self.mcp_agent_log_api: str = DEFAULT_MCP_AGENT_LOG_API
        self.mcp_retry_interval_sec: float = DEFAULT_MCP_RETRY_INTERVAL_SEC

        self.max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
        self.max_total_tool_calls: int = DEFAULT_MAX_TOTAL_TOOL_CALLS
        self.max_tools_per_round: int = DEFAULT_MAX_TOOLS_PER_ROUND
        self.max_tool_result_chars: int = DEFAULT_MAX_TOOL_RESULT_CHARS
        self.max_total_tool_result_chars: int = DEFAULT_MAX_TOTAL_TOOL_RESULT_CHARS


CONFIG = ProxyConfig()


# ----------------------------------------------------------------------
# JSON helper
# ----------------------------------------------------------------------
def jdump(obj: Any) -> bytes:
    """
    Serialize to UTF-8 bytes with literal Unicode characters.

    `ensure_ascii=False` guarantees that Chinese, emoji and other
    non-ASCII content is emitted as-is, never as \\uXXXX escapes.
    `default=str` prevents a crash if a tool returns a non-serializable
    object (defensive; should not normally happen).
    """
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


# ----------------------------------------------------------------------
# Header helpers
# ----------------------------------------------------------------------
def _parse_extra_headers(raw: str) -> Dict[str, str]:
    """Parse a JSON object string into a header dict; raise on malformed input."""
    if not raw or not raw.strip():
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"--backend-extra-headers is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("--backend-extra-headers must be a JSON object")
    out: Dict[str, str] = {}
    for k, v in obj.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(
                f"--backend-extra-headers key/value must be strings: "
                f"{k!r} -> {v!r}")
        out[k] = v
    return out


def _load_key_from_file(path: str) -> str:
    """Read a single-line API key from a file; raise on any problem."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            key = f.read().strip()
    except OSError as e:
        raise ValueError(f"Cannot read --backend-key-file {path!r}: {e}") from e
    if not key:
        raise ValueError(f"--backend-key-file {path!r} is empty")
    return key


# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
class SessionState:
    """
    A persistent conversation session.

    Holds:
      - a fixed `client_name` (destination for streaming messages)
      - a fixed `system_message` (snapshotted at creation time)
      - a message history that grows with each successful generation
      - status flags used by the worker and the watchdog

    The messages list may contain richer entries:
      - {"role": "user", "content": "..."}
      - {"role": "assistant", "content": "..."}
      - {"role": "assistant", "content": None, "tool_calls": [...]}
      - {"role": "tool", "tool_call_id": "...", "content": "..."}

    Thread safety:
      * `self.lock` guards every mutation of `self.messages` and every
        read-modify-write on the status flags.
      * The `running` flag and `cancel_event` are meant to be set
        *atomically* by the request handler before the worker thread
        starts; the worker only clears them at the end.
    """

    def __init__(self, session_id: str, client_name: str,
                 system_message: str = "") -> None:
        self.session_id = session_id
        self.client_name = client_name
        self.system_message = system_message
        self.messages: List[Dict[str, Any]] = []
        self.created_at = time.time()
        self.last_active = self.created_at
        self.cancel_event: Optional[threading.Event] = None
        self.running: bool = False
        self.lock = threading.Lock()

    # ---- Message mutators (all acquire the lock) ----

    def add_user(self, content: str) -> None:
        with self.lock:
            self.messages.append({"role": "user", "content": content})
            self._trim_locked()

    def add_assistant(self, content: str) -> None:
        with self.lock:
            self.messages.append({"role": "assistant", "content": content})
            self._trim_locked()

    def add_assistant_tool_calls(
            self, tool_calls: List[Dict[str, Any]]) -> None:
        """
        Append an assistant message with content=None + tool_calls.

        This is the OpenAI-compatible representation of "the assistant
        decided to call these tools".
        """
        with self.lock:
            self.messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            })
            self._trim_locked()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        """
        Append a `role=tool` message linked to a specific tool_call_id.

        The backend requires the tool_call_id to match an id from the
        immediately preceding assistant.tool_calls message.
        """
        with self.lock:
            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            })
            self._trim_locked()

    # ---- Trimming ----

    def _trim_locked(self) -> None:
        """
        Keep the history under both the count limit (`max_history`) and
        the character budget (`max_history_chars`).

        Invariants:
          * Never split an assistant.tool_calls message from its matching
            role=tool replies. If dropping the oldest entry would leave
            a dangling role=tool message at the head, keep dropping until
            the head is not role=tool.

        Called under `self.lock` by every message mutator.
        """
        # Safety: guarantee progress even with pathological configuration.
        safety_budget = len(self.messages) + 8

        while self.messages and safety_budget > 0:
            safety_budget -= 1

            over_count = len(self.messages) > CONFIG.max_history
            over_chars = (self._total_chars_locked()
                          > CONFIG.max_history_chars)
            if not over_count and not over_chars:
                break

            # If the head is an assistant with tool_calls, drop the whole
            # group (assistant + its role=tool replies) in one go.
            if (len(self.messages) >= 2
                    and self.messages[1].get("role") == "tool"):
                j = 1
                while (j < len(self.messages)
                       and self.messages[j].get("role") == "tool"):
                    j += 1
                del self.messages[:j]
            else:
                del self.messages[0]

            # Never leave role=tool at the head.
            while (self.messages
                   and self.messages[0].get("role") == "tool"):
                del self.messages[0]

    def _total_chars_locked(self) -> int:
        """
        Rough character count of the current history. Called under
        `self.lock`. O(n) per call, but n is bounded by `max_history`
        (default 512), so the worst case is fine.
        """
        total = 0
        for m in self.messages:
            c = m.get("content")
            if isinstance(c, str):
                total += len(c)
            tcs = m.get("tool_calls")
            if isinstance(tcs, list):
                # Each tool_call entry is roughly 100 chars of JSON.
                total += 100 * len(tcs)
        return total

    # ---- Snapshots and lifecycle ----

    def snapshot(self) -> List[Dict[str, Any]]:
        """
        Return a shallow copy of the message list for safe iteration.

        The copy protects the caller from concurrent appends, but the
        nested dicts are shared references. Callers must not mutate
        them.
        """
        with self.lock:
            return [dict(m) for m in self.messages]

    def touch(self) -> None:
        with self.lock:
            self.last_active = time.time()

    def end_run(self) -> None:
        """Clear running state and update the last-active timestamp."""
        with self.lock:
            self.cancel_event = None
            self.running = False
            self.last_active = time.time()

    def request_cancel(self) -> bool:
        """Signal cancellation if a task is currently running."""
        with self.lock:
            if self.cancel_event is None:
                return False
            self.cancel_event.set()
            return True

    def to_summary(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "session_id": self.session_id,
                "client_name": self.client_name,
                "created_at": self.created_at,
                "last_active_at": self.last_active,
                "status": "running" if self.running else "idle",
                "message_count": len(self.messages),
            }


# ----------------------------------------------------------------------
# OpenAI-compatible streaming client (http.client based)
# ----------------------------------------------------------------------
class OpenAIStreamClient:
    """
    HTTP+SSE client using Python's standard-library `http.client`.

    Why `http.client` instead of `requests`:
        requests / urllib3 buffer the SSE response at the socket layer
        in ways that no `iter_content` / `iter_lines` /
        `Accept-Encoding` configuration can disable. `HTTPResponse`
        from `http.client` wraps the raw socket in a BufferedReader, and
        iterating over the response yields a line the moment its
        terminating newline arrives.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = DEFAULT_BACKEND_TIMEOUT,
        auth_header: str = DEFAULT_BACKEND_AUTH_HEADER,
        auth_scheme: str = DEFAULT_BACKEND_AUTH_SCHEME,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.auth_header = auth_header
        self.auth_scheme = auth_scheme
        self.extra_headers = dict(extra_headers or {})

    def _build_headers(self, accept: str) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": accept,
            # SSE must not be compressed. gzip decoding buffers whole
            # deflate blocks, which destroys incremental delivery.
            "Accept-Encoding": "identity",
        }
        if self.auth_header and self.api_key:
            if self.auth_scheme:
                headers[self.auth_header] = (
                    f"{self.auth_scheme} {self.api_key}")
            else:
                headers[self.auth_header] = self.api_key
        headers.update(self.extra_headers)
        return headers

    def list_models(self) -> List[str]:
        """Probe `/v1/models` and return the list of model ids (best-effort)."""
        url = f"{self.base_url}/models"
        headers = self._build_headers("application/json")
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Failed to list backend models: %s", e)
            return []
        ids: List[str] = []
        for entry in data.get("data", []) or []:
            mid = entry.get("id")
            if mid:
                ids.append(mid)
        return ids

    def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        options: Dict[str, Any],
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Stream a chat completion from the backend.

        Yields dicts with any of the following keys:

            {"content": "..."}              - user-visible answer chunk
            {"reasoning_content": "..."}    - thinking / reasoning chunk
            {"tool_calls": [ ... ]}         - fully-assembled tool calls
                                              (only yielded once, at the
                                              end of the stream)

        tool_calls arrive as streamed fragments in the SSE delta; this
        method accumulates them by `index` and yields the consolidated
        list exactly once, after `[DONE]` is seen or the stream closes.

        Any exception during the HTTP conversation (connection refused,
        timeout, malformed SSE, etc.) propagates to the caller; the
        connection is always closed via the `finally` block.
        """
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers("text/event-stream")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        # Forward scalar options
        for key in ("max_tokens", "temperature", "top_p",
                    "top_k", "repeat_penalty"):
            if key in options and options[key] is not None:
                payload[key] = options[key]
        # Forward tools / tool_choice
        for key in ("tools", "tool_choice"):
            if key in options and options[key] is not None:
                payload[key] = options[key]

        body = jdump(payload)

        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port
        path = parsed.path or "/"
        if parsed.query:
            path = path + "?" + parsed.query

        is_https = parsed.scheme == "https"
        if port is None:
            port = 443 if is_https else 80

        logger.debug("Backend request: url=%s model=%s msgs=%d tools=%s",
                     url, model, len(messages),
                     "yes" if payload.get("tools") else "no")

        if is_https:
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(
                host, port, timeout=self.timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(
                host, port, timeout=self.timeout)

        try:
            if conn.sock is None:
                conn.connect()
            # Disable Nagle so small SSE frames go out immediately.
            try:
                conn.sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
        except Exception:
            pass

        try:
            conn.putrequest("POST", path, skip_accept_encoding=True)
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.putheader("Content-Length", str(len(body)))
            conn.endheaders()
            conn.send(body)

            resp = conn.getresponse()
            logger.debug("Backend response: status=%d content_type=%r",
                         resp.status, resp.getheader("Content-Type"))

            if resp.status >= 400:
                try:
                    detail = resp.read().decode(
                        "utf-8", errors="replace")[:500]
                except Exception:
                    detail = ""
                raise RuntimeError(
                    f"Backend HTTP {resp.status}: {detail}")

            # ---- Tool-call accumulator: index -> partial tool_call dict ----
            tool_calls_acc: Dict[int, Dict[str, Any]] = {}

            for raw_line in resp:
                if cancel_event is not None and cancel_event.is_set():
                    logger.debug("Backend stream cancelled by client")
                    return

                try:
                    line = raw_line.decode(
                        "utf-8", errors="replace").rstrip("\r\n")
                except Exception:
                    continue

                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break

                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                delta = self._extract_delta(obj)
                if not delta:
                    continue

                # Emit text events immediately.
                if "content" in delta or "reasoning_content" in delta:
                    yield delta

                # Accumulate tool_calls fragments by index; do NOT yield
                # them yet. `arguments` is a *string* that must be
                # concatenated, not merged.
                if "tool_calls" in delta:
                    for tc in delta["tool_calls"]:
                        if not isinstance(tc, dict):
                            continue
                        idx = tc.get("index", 0)
                        if not isinstance(idx, int):
                            idx = 0
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "arguments": "",
                                },
                            }
                        if tc.get("id"):
                            tool_calls_acc[idx]["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if not isinstance(fn, dict):
                            continue
                        if fn.get("name"):
                            tool_calls_acc[idx]["function"]["name"] = \
                                fn["name"]
                        if fn.get("arguments"):
                            tool_calls_acc[idx]["function"]["arguments"] += \
                                fn["arguments"]

            # End of stream: emit consolidated tool_calls if any.
            if tool_calls_acc:
                ordered = [tool_calls_acc[i]
                           for i in sorted(tool_calls_acc)]
                yield {"tool_calls": ordered}

        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _extract_delta(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract content / reasoning_content / tool_calls from one SSE
        frame. Does NOT accumulate; accumulation lives in `stream_chat`.
        """
        if not isinstance(obj, dict):
            return None
        choices = obj.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        if not isinstance(choice, dict):
            return None
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            return None
        out: Dict[str, Any] = {}

        content = delta.get("content")
        if isinstance(content, str) and content:
            out["content"] = content

        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            out["reasoning_content"] = reasoning

        tcs = delta.get("tool_calls")
        if isinstance(tcs, list) and tcs:
            out["tool_calls"] = tcs

        return out or None


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
class LLMProxyToolService:
    """
    Main service class.

    Sits between LingoFuse clients (LLM_Service on ipc:llm_service) and
    an OpenAI-compatible HTTP backend, with server-side MCP tool
    execution via `language_middleware`.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._sessions_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._backend = OpenAIStreamClient(
            base_url=CONFIG.backend_url,
            api_key=CONFIG.backend_key,
            timeout=CONFIG.backend_timeout,
            auth_header=CONFIG.backend_auth_header,
            auth_scheme=CONFIG.backend_auth_scheme,
            extra_headers=CONFIG.backend_extra_headers,
        )
        self._resolved_model: str = CONFIG.backend_model or ""

        # ---- MCP / tools (lazy) ----
        self._mw = None
        self._openai_tools_cache: Optional[List[Dict[str, Any]]] = None
        self._mcp_init_lock = threading.Lock()
        self._mcp_last_attempt: float = 0.0

        self.server = Server(
            CONFIG.app_name,
            "LingoFuse LLM Tool Bridge (LTB) - proxy with server-side tools")
        self._register_apis()

    # ------------------------------------------------------------------
    # Model resolution
    # ------------------------------------------------------------------
    def resolve_model(self) -> str:
        """Auto-discover the backend model id if not explicitly set."""
        if self._resolved_model:
            return self._resolved_model
        ids = self._backend.list_models()
        if ids:
            self._resolved_model = ids[0]
            logger.info("Auto-selected backend model: %s",
                        self._resolved_model)
        else:
            self._resolved_model = "unknown"
            logger.warning("Could not auto-discover backend model; "
                           "set LLM_PROXY_BACKEND_MODEL or --backend-model")
        return self._resolved_model

    # ------------------------------------------------------------------
    # MCP: tool discovery (lazy, with retry on failure)
    # ------------------------------------------------------------------
    def _ensure_tools_ready(self) -> bool:
        """
        Lazily connect to `language_middleware` and fetch the MCP tool
        list. Converts each tool to OpenAI tools-schema and caches it.

        Returns True if the OpenAI-format cache is non-empty.

        Retry policy:
          * On success, the cache is populated once and never refreshed
            during this process. Restart to pick up new tools.
          * On failure, a retry is attempted at most every
            `mcp_retry_interval_sec` seconds, so that a beacon that
            starts late still gets picked up.

        Thread safety:
          Guarded by `self._mcp_init_lock`, so concurrent `generate`
          calls cannot race to initialize the middleware.
        """
        if not CONFIG.enable_tools:
            return False
        if not _HAS_MIDDLEWARE:
            logger.warning("language_middleware not available; "
                           "tools are disabled")
            return False

        # Fast path: already have a non-empty cache.
        if self._openai_tools_cache:
            return True

        now = time.time()

        # Rate-limit re-attempts after a failed discovery.
        if self._openai_tools_cache is not None:  # empty cache = previous fail
            if now - self._mcp_last_attempt < CONFIG.mcp_retry_interval_sec:
                return False

        with self._mcp_init_lock:
            # Re-check inside the lock.
            if self._openai_tools_cache:
                return True
            if self._openai_tools_cache is not None:
                if (now - self._mcp_last_attempt
                        < CONFIG.mcp_retry_interval_sec):
                    return False

            self._mcp_last_attempt = now
            try:
                self._mw = LanguageMiddleware.get_instance(
                    endpoint=CONFIG.mcp_endpoint,
                    timeout_ms=CONFIG.mcp_timeout_ms,
                    reg_agent_app_name=CONFIG.mcp_reg_agent_app,
                    tool_provider_app=CONFIG.mcp_tool_provider_app,
                    agent_main_api=CONFIG.mcp_agent_main_api,
                    agent_log_api=CONFIG.mcp_agent_log_api,
                )
                self._mw._ensure_connected()
                mcp_tools = self._mw.get_tools() or []
                self._openai_tools_cache = [
                    self._mcp_tool_to_openai(t)
                    for t in mcp_tools
                    if isinstance(t, dict) and t.get("name")
                ]
                logger.info("MCP tools loaded: %d tools",
                            len(self._openai_tools_cache))
            except Exception as e:
                logger.error("Failed to initialize MCP tools: %s", e)
                self._openai_tools_cache = []

            return bool(self._openai_tools_cache)

    @staticmethod
    def _mcp_tool_to_openai(tool: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert an MCP tool entry to OpenAI tools-schema.

        MCP's `parameters` field is already a JSON Schema, so it is
        passed through unchanged. A minimal schema is filled in when
        `parameters` is missing.
        """
        params = tool.get("parameters")
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": params,
            },
        }

    # ------------------------------------------------------------------
    # API registration
    # ------------------------------------------------------------------
    def _register_apis(self) -> None:
        @self.server.expose("generate")
        def generate(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_generate(data)

        @self.server.expose("create_session")
        def create_session(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_create_session(data)

        @self.server.expose("close_session")
        def close_session(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_close_session(data)

        @self.server.expose("cancel_session")
        def cancel_session(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_cancel_session(data)

        @self.server.expose("list_sessions")
        def list_sessions(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_list_sessions(data)

        @self.server.expose("set_system_message")
        def set_system_message(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_set_system_message(data)

        @self.server.expose("get_api_capabilities")
        def get_api_capabilities(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_get_api_capabilities(data)

        @self.server.expose("health")
        def health(data: Dict[str, Any]) -> Dict[str, Any]:
            return self._handle_health(data)

        logger.info("Registered APIs: generate, create_session, "
                    "close_session, cancel_session, list_sessions, "
                    "set_system_message (unsupported), "
                    "get_api_capabilities, health")

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------
    def _count_sessions(self) -> int:
        with self._sessions_lock:
            return len(self._sessions)

    def _lookup(self, session_id: str) -> Optional[SessionState]:
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def _drop(self, session_id: str) -> Optional[SessionState]:
        with self._sessions_lock:
            return self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _handle_generate(self, data: Any) -> Dict[str, Any]:
        """
        Entry point for the `generate` Call API.

        Accepted request fields:
          * session_id          (str, optional for new sessions)
          * content             (str, required unless tool_results given)
          * prompt              (str, optional)
          * client_name         (str, required for new sessions)
          * options.tools       (list, optional)
          * options.tool_choice (str or dict, optional)
          * tool_results        (list, optional; reserved, unused by LTB
                                since tools execute server-side)

        Returns:
          {code, session_id, task_id, mode, expects_tool_results}

        `expects_tool_results` is always False for LTB, because tool
        execution is fully internal.
        """
        if not isinstance(data, dict):
            return {"code": -1, "error": "generate expects a JSON object"}

        content = data.get("content", "") or ""
        prompt = data.get("prompt", "") or ""
        client_name = data.get("client_name")
        session_id = data.get("session_id")
        options_raw = data.get("options", {}) or {}
        tool_results = data.get("tool_results")

        if not content and not prompt and not tool_results:
            return {"code": -1,
                    "error": "Missing content, prompt, or tool_results"}
        if not isinstance(options_raw, dict):
            return {"code": -1, "error": "options must be a JSON object"}
        if session_id is not None and not isinstance(session_id, str):
            return {"code": -1, "error": "session_id must be a string"}

        # ---- Validate tool_results (defensive; unused by LTB) ----
        if tool_results is not None:
            if not isinstance(tool_results, list):
                return {"code": -1, "error": "tool_results must be a list"}
            for tr in tool_results:
                if not isinstance(tr, dict):
                    return {"code": -1,
                            "error": "each tool_result must be an object"}
                if not tr.get("tool_call_id"):
                    return {"code": -1,
                            "error": "tool_result missing tool_call_id"}
                if "content" not in tr:
                    return {"code": -1,
                            "error": "tool_result missing content"}

        options = self._sanitize_options(options_raw)
        if tool_results:
            options["tool_results"] = tool_results

        has_tools = bool(options.get("tools"))

        # ---- Resolve or create session (ATOMIC occupancy) ----
        sess: Optional[SessionState] = None
        cancel_ev: Optional[threading.Event] = None
        mode: str

        if session_id:
            sess = self._lookup(session_id)
            if sess is None:
                return {"code": -1,
                        "error": f"Session not found: {session_id}"}
            if client_name and client_name != sess.client_name:
                return {"code": -1,
                        "error": "client_name does not match session owner"}
            # Atomic occupancy: check and set under the session lock so
            # two concurrent generate calls cannot both start a task.
            with sess.lock:
                if sess.running:
                    return {"code": -1,
                            "error": f"Session already running: "
                                     f"{session_id}"}
                sess.running = True
                cancel_ev = threading.Event()
                sess.cancel_event = cancel_ev
            mode = "continue"
        else:
            if not client_name or not isinstance(client_name, str):
                return {"code": -1,
                        "error": "Missing client_name for new session"}
            # Atomic check-and-create under the sessions lock, so the
            # session count limit cannot be exceeded by racing requests.
            with self._sessions_lock:
                if len(self._sessions) >= CONFIG.max_sessions:
                    return {"code": -1,
                            "error": f"Session limit reached "
                                     f"({CONFIG.max_sessions})"}
                sid = str(uuid.uuid4())
                sess = SessionState(sid, client_name)
                sess.running = True
                cancel_ev = threading.Event()
                sess.cancel_event = cancel_ev
                self._sessions[sid] = sess
            mode = "new"

        # sess and cancel_ev are guaranteed non-None beyond this point.
        sess.touch()
        task_id = str(uuid.uuid4())

        try:
            t = threading.Thread(
                target=self._run_generation,
                args=(sess, task_id, content, prompt, options, cancel_ev),
                name=f"llm-proxy-tool-{task_id[:8]}",
                daemon=True,
            )
            t.start()
        except Exception as e:
            # Thread creation failure: roll back the occupancy flag so
            # the session is not left permanently "running".
            logger.error("Failed to start worker thread: %s", e)
            sess.end_run()
            return {"code": -1, "error": f"Failed to start task: {e}"}

        logger.debug("generate queued: mode=%s session=%s task=%s "
                     "tools=%s tr=%s",
                     mode, sess.session_id, task_id,
                     has_tools, bool(tool_results))
        return {
            "code": 0,
            "session_id": sess.session_id,
            "task_id": task_id,
            "mode": mode,
            # LTB executes tools server-side, so the client is never
            # expected to submit tool results.
            "expects_tool_results": False,
        }

    def _handle_create_session(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"code": -1,
                    "error": "create_session expects a JSON object"}
        client_name = data.get("client_name")
        if not client_name or not isinstance(client_name, str):
            return {"code": -1,
                    "error": "Missing client_name (string required)"}
        system_message = data.get("system_message") or ""
        if not isinstance(system_message, str):
            return {"code": -1,
                    "error": "system_message must be a string"}

        with self._sessions_lock:
            if len(self._sessions) >= CONFIG.max_sessions:
                return {"code": -1,
                        "error": f"Session limit reached "
                                 f"({CONFIG.max_sessions})"}
            sid = str(uuid.uuid4())
            sess = SessionState(sid, client_name, system_message)
            self._sessions[sid] = sess

        logger.info("Session created: %s (system_message=%d chars)",
                    sess.session_id, len(system_message))
        return {
            "code": 0,
            "session_id": sess.session_id,
            "client_name": client_name,
        }

    def _handle_close_session(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"code": -1,
                    "error": "close_session expects a JSON object"}
        session_id = data.get("session_id")
        if not session_id or not isinstance(session_id, str):
            return {"code": -1, "error": "Missing session_id"}
        sess = self._drop(session_id)
        if sess is None:
            return {"code": -1,
                    "error": f"Session not found: {session_id}"}
        sess.request_cancel()
        self._emit(sess, {"type": "closed",
                          "session_id": sess.session_id,
                          "reason": "client"})
        logger.info("Session closed: %s", session_id)
        return {"code": 0, "status": "closed"}

    def _handle_cancel_session(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"code": -1,
                    "error": "cancel_session expects a JSON object"}
        session_id = data.get("session_id")
        if not session_id or not isinstance(session_id, str):
            return {"code": -1, "error": "Missing session_id"}
        sess = self._lookup(session_id)
        if sess is None:
            return {"code": -1,
                    "error": f"Session not found: {session_id}"}
        ok = sess.request_cancel()
        logger.debug("Cancel requested for session %s (running=%s)",
                     session_id, ok)
        return {"code": 0,
                "status": "cancel_requested" if ok else "no_active_task"}

    def _handle_list_sessions(self, data: Any) -> Dict[str, Any]:
        client_filter = None
        if isinstance(data, dict):
            client_filter = data.get("client_name")
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        summaries = [
            s.to_summary() for s in sessions
            if (client_filter is None or s.client_name == client_filter)
        ]
        return {"code": 0, "sessions": summaries, "count": len(summaries)}

    def _handle_set_system_message(self, data: Any) -> Dict[str, Any]:
        """
        set_system_message is UNSUPPORTED in this proxy.

        Like `llm_proxy.py`, LTB is a stateless forwarder: each session
        captures its system message at creation and rebuilds the
        messages array before every backend call.
        """
        logger.debug("set_system_message rejected: not supported by "
                     "llm_proxy_tool (stateless forwarder)")
        return {
            "code": -1,
            "status": "unsupported",
            "error": (
                "set_system_message is not supported by llm_proxy_tool.\n"
                "The system message is fixed at session creation.\n"
                "To change it, close the current session and create\n"
                "a new one with the desired system_message.\n"
            ),
        }

    def _handle_get_api_capabilities(self, data: Any) -> Dict[str, Any]:
        return {
            "code": 0,
            "server_kind": SERVER_KIND,
            "capabilities": dict(API_CAPABILITIES),
        }

    def _handle_health(self, data: Any) -> Dict[str, Any]:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        idle = sum(1 for s in sessions if not s.running)
        running = sum(1 for s in sessions if s.running)

        auth_configured = bool(
            CONFIG.backend_auth_header and CONFIG.backend_key)

        mcp_connected = False
        if self._mw is not None:
            try:
                mcp_connected = bool(self._mw.is_connected())
            except Exception:
                mcp_connected = False

        return {
            "code": 0,
            "status": "ok",
            "server_kind": SERVER_KIND,
            "backend_url": CONFIG.backend_url,
            "backend_model": self._resolved_model or CONFIG.backend_model,
            "backend_auth_header": CONFIG.backend_auth_header,
            "backend_auth_scheme": CONFIG.backend_auth_scheme,
            "backend_auth_configured": auth_configured,
            "backend_extra_headers": list(
                CONFIG.backend_extra_headers.keys()),
            "notify_api": CONFIG.notify_api,
            "set_system_message_supported": False,
            "sessions_total": len(sessions),
            "sessions_idle": idle,
            "sessions_running": running,
            "session_limit": CONFIG.max_sessions,
            "session_timeout": CONFIG.session_timeout,
            "max_history": CONFIG.max_history,
            "max_history_chars": CONFIG.max_history_chars,
            "api_capabilities": dict(API_CAPABILITIES),
            # ---- LTB-specific ----
            "tools_enabled": CONFIG.enable_tools,
            "mcp_connected": mcp_connected,
            "mcp_tools_count": len(self._openai_tools_cache or []),
            "max_tool_rounds": CONFIG.max_tool_rounds,
            "max_total_tool_calls": CONFIG.max_total_tool_calls,
            "max_tool_result_chars": CONFIG.max_tool_result_chars,
            "max_total_tool_result_chars":
                CONFIG.max_total_tool_result_chars,
            "tool_execution_mode": "server-side",
        }

    # ------------------------------------------------------------------
    # Options sanitizer
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_options(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Keep only the option keys that this proxy forwards to the
        backend. Unknown keys are dropped and (at DEBUG level) logged.

        Note: `tools` and `tool_choice` are passed through. Whether
        they actually reach the backend is decided later in
        `_run_generation` (see the multi-round logic).
        """
        out: Dict[str, Any] = {}

        if logger.isEnabledFor(logging.DEBUG):
            unsupported = [k for k in raw.keys()
                           if k not in _FORWARDED_OPTION_KEYS]
            if unsupported:
                logger.debug(
                    "Options keys not supported by the proxy and ignored: %s",
                    ", ".join(unsupported))

        # Scalar options
        for key, cast, lo, hi in (
            ("max_tokens", int, 1, 1 << 20),
            ("temperature", float, 0.0, 2.0),
            ("top_p", float, 0.0, 1.0),
            ("top_k", int, 0, 1000),
            ("repeat_penalty", float, 0.0, 4.0),
        ):
            if key in raw and raw[key] is not None:
                try:
                    v = cast(raw[key])
                    v = max(lo, min(hi, v))
                    out[key] = v
                except (TypeError, ValueError):
                    pass

        # tools / tool_choice: passed through without deep validation.
        tools = raw.get("tools")
        if isinstance(tools, list):
            out["tools"] = tools

        tool_choice = raw.get("tool_choice")
        if isinstance(tool_choice, (str, dict)):
            out["tool_choice"] = tool_choice

        return out

    # ------------------------------------------------------------------
    # Core: multi-round generation with server-side tool execution
    # ------------------------------------------------------------------
    def _run_generation(self, sess: SessionState, task_id: str,
                        content: str, prompt: str,
                        options: Dict[str, Any],
                        cancel_event: threading.Event) -> None:
        """
        Multi-round generation with SERVER-SIDE tool execution.

        Round protocol
        --------------
        * Rounds [0, max_tool_rounds - 2] : inject `tools`.
          The backend may return tool_calls; LTB executes them,
          appends assistant.tool_calls + role=tool to history, and
          continues to the next round.

        * Last round (max_tool_rounds - 1) : do NOT inject `tools`.
          This forces the model to emit a final text answer regardless
          of how many tools it has called so far.

        Additional caps
        ---------------
        * `max_total_tool_calls`         - total tool executions per
                                           `generate` call, across all
                                           rounds.
        * `max_total_tool_result_chars`  - total characters of all tool
                                           results per `generate` call.

        When either cap is hit, the loop switches to the final
        text-answer round immediately.

        Streaming output
        ----------------
        Both `reasoning_content` (think) and `content` (chunk) are
        emitted to the client as soon as they arrive. On completion,
        LTB emits exactly one `finish(reason="stop")` (or
        `finish(reason="error")` on failure).

        Session occupancy
        -----------------
        `sess.running` and `sess.cancel_event` are set by the caller
        (`_handle_generate`) BEFORE this method runs. This method must
        always clear them via `sess.end_run()` in its `finally` block.
        """
        user_text = content + ("\n\n" + prompt if prompt else "")
        sess.add_user(user_text)

        model = self._resolved_model or CONFIG.backend_model
        if not model:
            model = self.resolve_model()

        # ---- Decide whether tool injection is possible at all ----
        tools_available = False
        try:
            tools_available = (
                CONFIG.enable_tools
                and self._ensure_tools_ready()
                and bool(self._openai_tools_cache)
            )
        except Exception as e:
            logger.error("Tool availability check failed: %s", e)

        if tools_available:
            logger.debug("Task %s: tools available (%d)",
                         task_id, len(self._openai_tools_cache or []))
        else:
            logger.debug("Task %s: no tools available; "
                         "running as pure text proxy", task_id)

        # Per-call counters for the two additional caps.
        total_tool_calls = 0
        total_tool_result_chars = 0
        force_final_round = False

        try:
            for round_idx in range(CONFIG.max_tool_rounds):
                if cancel_event.is_set():
                    break

                # ---- Build messages (system + history) ----
                history = sess.snapshot()
                messages: List[Dict[str, Any]] = []
                if sess.system_message:
                    messages.append({"role": "system",
                                     "content": sess.system_message})
                messages.extend(history)

                # ---- Decide whether to inject tools this round ----
                #
                # CRITICAL: tools are injected on every round except the
                # last. Reasoning models (e.g. Nemotron) often call one
                # tool at a time, inspect the result, then decide the
                # next step. Stripping tools after round 0 would prevent
                # multi-tool sequences even when the user explicitly
                # asked for them.
                #
                # The last round (or a round forced by a cap) omits
                # tools to force a text answer, so the loop always
                # terminates with a final response.
                is_final_round = (
                    force_final_round
                    or round_idx == CONFIG.max_tool_rounds - 1
                )

                round_options = dict(options)
                round_options.pop("tool_results", None)

                if tools_available and not is_final_round:
                    round_options["tools"] = self._openai_tools_cache
                else:
                    round_options.pop("tools", None)
                    round_options.pop("tool_choice", None)

                logger.debug("Task %s round %d/%d: msgs=%d tools=%s",
                             task_id, round_idx, CONFIG.max_tool_rounds,
                             len(messages),
                             "yes" if round_options.get("tools") else "no")

                # ---- Stream from the backend ----
                answer_pieces: List[str] = []
                tool_calls: Optional[List[Dict[str, Any]]] = None

                for delta in self._backend.stream_chat(
                        model, messages, round_options,
                        cancel_event=cancel_event):
                    if cancel_event.is_set():
                        break
                    if "reasoning_content" in delta:
                        # Thinking stream: relay in real time.
                        self._emit(sess, {
                            "type": "think",
                            "session_id": sess.session_id,
                            "text": delta["reasoning_content"],
                        })
                    if "content" in delta:
                        # Stream content immediately, so the user sees
                        # progress even during tool-calling rounds.
                        text = delta["content"]
                        answer_pieces.append(text)
                        self._emit(sess, {
                            "type": "chunk",
                            "session_id": sess.session_id,
                            "text": text,
                        })
                    if "tool_calls" in delta:
                        tool_calls = delta["tool_calls"]

                # ---- No tool calls: this is the final text answer ----
                if not tool_calls:
                    sess.add_assistant("".join(answer_pieces))
                    logger.debug("Task %s round %d: final answer (%d chars)",
                                 task_id, round_idx,
                                 len("".join(answer_pieces)))
                    break

                # ---- Defensive: tool_calls on the final round ----
                if is_final_round:
                    logger.warning(
                        "Task %s: model returned tool_calls on the final "
                        "round despite tools not being injected; "
                        "recording text and stopping", task_id)
                    sess.add_assistant("".join(answer_pieces))
                    break

                # ---- Decide how many tool calls to execute this round ----
                remaining_total = (CONFIG.max_total_tool_calls
                                   - total_tool_calls)
                if remaining_total <= 0:
                    logger.warning(
                        "Task %s: total tool-call cap reached (%d); "
                        "switching to final text round",
                        task_id, CONFIG.max_total_tool_calls)
                    force_final_round = True
                    continue

                num_to_exec = min(
                    len(tool_calls),
                    CONFIG.max_tools_per_round,
                    remaining_total,
                )

                # Record only the tool_calls we actually executed, so
                # that every id in assistant.tool_calls has a matching
                # role=tool reply in history.
                exec_calls = tool_calls[:num_to_exec]
                sess.add_assistant_tool_calls(exec_calls)

                logger.debug(
                    "Task %s round %d: executing %d of %d tool call(s)",
                    task_id, round_idx, num_to_exec, len(tool_calls))

                for tc in exec_calls:
                    if cancel_event.is_set():
                        break

                    tc_id = tc.get("id", "") or ""
                    fn = tc.get("function") or {}
                    tool_name = fn.get("name", "") or ""
                    args_str = fn.get("arguments", "") or ""

                    logger.debug("  -> %s(%s)", tool_name, args_str)

                    # Parse arguments
                    try:
                        args = json.loads(args_str) if args_str else {}
                        if not isinstance(args, dict):
                            args = {}
                    except json.JSONDecodeError as e:
                        result_content = json.dumps(
                            {"error": f"invalid tool arguments: {e}"},
                            ensure_ascii=False)
                        logger.debug("  !! bad args JSON: %s", e)
                    else:
                        # Execute via middleware
                        try:
                            if self._mw is None:
                                raise RuntimeError(
                                    "MCP middleware not initialized")
                            result = self._mw.call_tool(tool_name, args)
                            if result is None:
                                result_content = json.dumps(
                                    {"result": None},
                                    ensure_ascii=False)
                            else:
                                result_content = json.dumps(
                                    result, ensure_ascii=False,
                                    default=str)
                        except Exception as e:
                            logger.debug(
                                "  !! tool execution failed: %s", e)
                            result_content = json.dumps(
                                {"error": str(e)}, ensure_ascii=False)

                    # Truncate this single result if oversized.
                    if len(result_content) > CONFIG.max_tool_result_chars:
                        result_content = (
                            result_content[:CONFIG.max_tool_result_chars]
                            + "...(truncated)"
                        )

                    # Enforce the per-call total tool-result budget.
                    remaining_chars = (
                        CONFIG.max_total_tool_result_chars
                        - total_tool_result_chars
                    )
                    if remaining_chars <= 0:
                        result_content = "...(tool-result budget exhausted)"
                    elif len(result_content) > remaining_chars:
                        result_content = (
                            result_content[:remaining_chars]
                            + "...(tool-result budget exhausted)"
                        )
                    total_tool_result_chars += len(result_content)

                    preview = result_content[:200]
                    logger.debug("  <- %s", preview
                                 + ("..." if len(result_content) > 200
                                    else ""))

                    sess.add_tool_result(tc_id, result_content)
                    total_tool_calls += 1

                # Loop back for the next round

            # ---- All rounds done; emit exactly one finish event ----
            self._emit(sess, {"type": "finish",
                              "session_id": sess.session_id,
                              "reason": "stop"})
            logger.debug("Task %s finished", task_id)

        except Exception as e:
            error_message = str(e)
            logger.error("Task %s backend error: %s", task_id, error_message)
            try:
                self._emit(sess, {"type": "error",
                                  "session_id": sess.session_id,
                                  "message": error_message})
                self._emit(sess, {"type": "finish",
                                  "session_id": sess.session_id,
                                  "reason": "error"})
            except Exception as ee:
                logger.error("Task %s: failed to emit error finish: %s",
                             task_id, ee)
        finally:
            # Always release the session occupancy flag, no matter how
            # the loop exited. This guarantees that a bug in the loop
            # never leaves the session stuck in "running" state.
            try:
                sess.end_run()
            except Exception as e:
                logger.error("Task %s: failed to end_run session: %s",
                             task_id, e)

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------
    def _emit(self, sess: SessionState, payload: Dict[str, Any]) -> None:
        """
        Send one structured JSON event to the client via the notify API.

        Payload is serialized with `ensure_ascii=False` so that
        non-ASCII content (Chinese, emoji) is preserved verbatim.

        Failures (client offline, DataHandle issues) are logged at
        DEBUG level and swallowed. They must never crash the worker
        thread.
        """
        hnd = None
        try:
            hnd = DataHandle(CONFIG.notify_api)
            data = jdump(payload) + b"\x00"
            written = LF_WriteBuffer(hnd.raw, data, len(data))
            if written != len(data):
                logger.warning("Partial write to DataHandle: %d/%d bytes",
                               written, len(data))
            LF_Sequenced_Notify(sess.client_name.encode("utf-8"), hnd.raw)
        except Exception as e:
            logger.debug("Notify to '%s' failed (%s): %s",
                         sess.client_name, payload.get("type"), e)
        finally:
            if hnd is not None:
                try:
                    hnd.free()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------
    def _watchdog_loop(self) -> None:
        """
        Reclaim sessions that have been idle past `session_timeout`.

        Running sessions are skipped: they are mid-generation and the
        worker thread owns their state. This is a simpler policy than
        `llm_service.py`'s dual-condition check because LTB does not own
        the model context; its sessions only hold a message list.
        """
        while not self._shutdown.wait(timeout=5.0):
            now = time.time()
            expired: List[str] = []
            try:
                with self._sessions_lock:
                    for sid, sess in self._sessions.items():
                        if sess.running:
                            continue
                        if now - sess.last_active > CONFIG.session_timeout:
                            expired.append(sid)
                    for sid in expired:
                        self._sessions.pop(sid, None)
            except Exception as e:
                logger.error("Watchdog iteration failed: %s", e)
                continue
            for sid in expired:
                logger.debug("Session %s expired by idle timeout", sid)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """
        Start the LTB service.

        Ordering is critical:

        `Server.start()` internally calls `LF_PrepareDone()`, which
        starts the LingoFuse simulated main thread. Once that main
        thread is running, a subsequent `LF_PrepareDone()` call from
        `language_middleware._connect()` returns 0 (not 1), and
        `_connect()` treats that as a hard failure, permanently
        disabling the tool cache for the rest of the process.

        To avoid that, we call `_ensure_tools_ready()` FIRST, so the
        middleware wins the race: it starts the main thread, then
        `Server.start()` detects the active main thread via
        `LF_CheckMainThread()` and proceeds with a warning instead of
        raising.
        """
        logger.info("Backend URL: %s", CONFIG.backend_url)
        if CONFIG.backend_auth_header and CONFIG.backend_key:
            logger.info(
                "Backend auth: header=%s scheme=%s token_chars=%d",
                CONFIG.backend_auth_header,
                CONFIG.backend_auth_scheme or "(none)",
                len(CONFIG.backend_key))
        else:
            logger.info("Backend auth: disabled (no token)")
        if CONFIG.backend_extra_headers:
            logger.info("Backend extra headers: %s",
                        list(CONFIG.backend_extra_headers.keys()))
        self.resolve_model()

        # ---- CRITICAL: pre-connect MCP middleware BEFORE Server.start() ----
        if CONFIG.enable_tools and _HAS_MIDDLEWARE:
            logger.info("Pre-connecting MCP middleware before server start")
            ok = self._ensure_tools_ready()
            if ok:
                logger.info("MCP middleware ready: %d tool(s) cached",
                            len(self._openai_tools_cache or []))
            else:
                logger.warning(
                    "MCP middleware pre-connect did not yield any tools. "
                    "Tool execution will be disabled until a retry "
                    "succeeds. Make sure `pascal_agent_service.exe` and "
                    "`pascal_agent_api.exe` are running on ipc:agent.")
        elif not _HAS_MIDDLEWARE:
            logger.warning("language_middleware not importable; "
                           "running as pure-text proxy")
        elif not CONFIG.enable_tools:
            logger.info("Tools disabled by configuration "
                        "(--no-tools); running as pure-text proxy")

        threading.Thread(target=self._watchdog_loop,
                         name="llm-proxy-tool-watchdog",
                         daemon=True).start()
        self.server.start(CONFIG.endpoint)
        logger.info("LLM Tool Bridge service '%s' running on %s",
                    CONFIG.app_name, CONFIG.endpoint)

    def stop(self) -> None:
        """Graceful shutdown: cancel sessions, close MCP, stop server."""
        self._shutdown.set()
        try:
            with self._sessions_lock:
                sessions = list(self._sessions.values())
            for sess in sessions:
                sess.request_cancel()
        except Exception as e:
            logger.warning("Session cancellation during shutdown: %s", e)

        # Shutdown MCP middleware if it was ever initialized.
        if self._mw is not None:
            try:
                self._mw.shutdown()
                logger.info("MCP middleware shut down")
            except Exception as e:
                logger.warning("MCP middleware shutdown error: %s", e)
            self._mw = None

        try:
            self.server.stop(full_cleanup=True)
        except Exception as e:
            logger.warning("Server stop error: %s", e)


# ----------------------------------------------------------------------
# Banner
# ----------------------------------------------------------------------
def print_banner() -> None:
    """Print a compact status banner at startup."""
    if CONFIG.backend_auth_header and CONFIG.backend_key:
        auth_display = (
            f"{CONFIG.backend_auth_header}: "
            f"{CONFIG.backend_auth_scheme + ' ' if CONFIG.backend_auth_scheme else ''}"
            f"<redacted, {len(CONFIG.backend_key)} chars>")
    else:
        auth_display = "(disabled)"

    extra_display = (", ".join(CONFIG.backend_extra_headers.keys())
                     if CONFIG.backend_extra_headers else "(none)")

    supported = [k for k, v in API_CAPABILITIES.items() if v == 1]
    unsupported = [k for k, v in API_CAPABILITIES.items() if v == 0]

    lines = [
        "=" * 70,
        " LINGOFUSE LLM PROXY TOOL BRIDGE (LTB) v2.1",
        "=" * 70,
        f"  Service kind            : {SERVER_KIND}",
        f"  Service endpoint        : {CONFIG.endpoint}",
        f"  Service app name        : {CONFIG.app_name}",
        f"  Notify API name         : {CONFIG.notify_api}",
        f"  Backend URL             : {CONFIG.backend_url}",
        f"  Backend model           : "
        f"{CONFIG.backend_model or '(auto-discover)'}",
        f"  Backend auth            : {auth_display}",
        f"  Backend extra headers   : {extra_display}",
        f"  Backend timeout (s)     : {CONFIG.backend_timeout}",
        f"  Backend transport       : http.client",
        f"  Max history per session : {CONFIG.max_history} messages "
        f"/ {CONFIG.max_history_chars} chars",
        f"  Max sessions            : {CONFIG.max_sessions}",
        f"  Session idle timeout(s) : {CONFIG.session_timeout}",
        f"  set_system_message      : unsupported (llm_service-only)",
        f"  Log level               : {CONFIG.log_level}",
        "-" * 70,
        f"  Tools enabled           : {CONFIG.enable_tools}",
        f"  Tool execution mode     : server-side (client-transparent)",
        f"  MCP endpoint            : {CONFIG.mcp_endpoint}",
        f"  MCP reg agent app       : {CONFIG.mcp_reg_agent_app}",
        f"  MCP tool provider app   : {CONFIG.mcp_tool_provider_app}",
        f"  Max tool rounds         : {CONFIG.max_tool_rounds}",
        f"  Max total tool calls    : {CONFIG.max_total_tool_calls}",
        f"  Max tools per round     : {CONFIG.max_tools_per_round}",
        f"  Max tool result chars   : {CONFIG.max_tool_result_chars}",
        f"  Max total tool-result   : "
        f"{CONFIG.max_total_tool_result_chars} chars",
        "-" * 70,
        f"  Supported APIs          : {', '.join(supported)}",
        f"  Unsupported APIs        : {', '.join(unsupported) or '(none)'}",
        "=" * 70,
    ]
    print("\n".join(lines))


# ----------------------------------------------------------------------
# Signal handling
# ----------------------------------------------------------------------
_SHUTDOWN = threading.Event()


def _install_signal_handlers() -> None:
    """
    Convert SIGINT / SIGTERM into a shutdown signal.

    The main loop waits on `_SHUTDOWN`; setting it causes a graceful
    exit through `service.stop()`.
    """
    def _handler(signum, frame):
        logger.info("Received signal %s; shutting down", signum)
        _SHUTDOWN.set()

    for sig in ("SIGINT", "SIGTERM"):
        s = getattr(signal, sig, None)
        if s is None:
            continue
        try:
            signal.signal(s, _handler)
        except (ValueError, OSError):
            pass


# ----------------------------------------------------------------------
# Argument parsing
# ----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    This is the ONLY place in the module that reads `os.environ`.
    Every value is then copied into `CONFIG` by
    `_init_global_config()`, and no runtime code ever touches
    environment variables or `sys.argv` again.
    """
    invocation = get_example_invocation()

    supported = [k for k, v in API_CAPABILITIES.items() if v == 1]
    unsupported = [k for k, v in API_CAPABILITIES.items() if v == 0]

    epilog = (
        "==============================================================\n"
        " Command-Line Reference\n"
        "==============================================================\n"
        "\n"
        "LingoFuse Service\n"
        "-----------------\n"
        "  --endpoint ADDRESS\n"
        "      LingoFuse service endpoint. `ipc:name` for IPC (same\n"
        "      host), `host:port` for TCP (cross host).\n"
        f"      Default: {DEFAULT_ENDPOINT}\n"
        "      Env:     LLM_PROXY_ENDPOINT\n"
        "\n"
        "  --app-name NAME\n"
        "      LingoFuse application name. Must match the name the\n"
        "      client uses to look up this service.\n"
        f"      Default: {DEFAULT_APP_NAME}\n"
        "      Env:     LLM_PROXY_APP_NAME\n"
        "\n"
        "  --notify-api NAME\n"
        "      Notify API name used for streaming events back to the\n"
        "      client. The client must register a notify callback\n"
        "      with this exact name.\n"
        f"      Default: {DEFAULT_NOTIFY_API}\n"
        "      Env:     LLM_PROXY_NOTIFY_API\n"
        "\n"
        "Backend (OpenAI-compatible HTTP)\n"
        "--------------------------------\n"
        "  --backend-url URL\n"
        "      Base URL of the backend. The proxy appends\n"
        "      `/chat/completions` to this URL.\n"
        f"      Default: {DEFAULT_BACKEND_URL}\n"
        "      Env:     LLM_PROXY_BACKEND_URL\n"
        "      Examples:\n"
        "        LM Studio:  http://127.0.0.1:1234/v1\n"
        "        Ollama:     http://127.0.0.1:11434/v1\n"
        "        vLLM:       http://127.0.0.1:8000/v1\n"
        "        DeepSeek:   https://api.deepseek.com/v1\n"
        "\n"
        "  --backend-model ID\n"
        "      Model id sent in the request body. Empty = auto-discover\n"
        "      via `/v1/models`.\n"
        "      Default: (empty)\n"
        "      Env:     LLM_PROXY_BACKEND_MODEL\n"
        "\n"
        "  --backend-key KEY\n"
        "      API key / token sent in the auth header.\n"
        f"      Default: {DEFAULT_BACKEND_KEY}\n"
        "      Env:     LLM_PROXY_BACKEND_KEY\n"
        "\n"
        "  --backend-key-file PATH\n"
        "      Read the API key from a file. Overrides --backend-key.\n"
        "      Env:     LLM_PROXY_BACKEND_KEY_FILE\n"
        "\n"
        "  --backend-auth-header NAME\n"
        "      HTTP header carrying the token.\n"
        f"      Default: {DEFAULT_BACKEND_AUTH_HEADER}\n"
        "      Env:     LLM_PROXY_BACKEND_AUTH_HEADER\n"
        "\n"
        "  --backend-auth-scheme PREFIX\n"
        "      Token prefix. Empty string means raw token.\n"
        f"      Default: {DEFAULT_BACKEND_AUTH_SCHEME}\n"
        "      Env:     LLM_PROXY_BACKEND_AUTH_SCHEME\n"
        "\n"
        "  --backend-extra-headers JSON\n"
        "      Additional HTTP headers as a JSON object.\n"
        "      Default: {} (no extra headers)\n"
        "      Env:     LLM_PROXY_BACKEND_EXTRA_HEADERS\n"
        "      Example: '{\"HTTP-Referer\": \"https://example.com\"}'\n"
        "\n"
        "  --backend-timeout SECONDS\n"
        "      HTTP read timeout for backend streaming requests.\n"
        f"      Default: {DEFAULT_BACKEND_TIMEOUT}\n"
        "      Env:     LLM_PROXY_BACKEND_TIMEOUT\n"
        "\n"
        "Sessions\n"
        "--------\n"
        "  --max-sessions N\n"
        "      Maximum concurrent sessions. Requests that create\n"
        "      sessions beyond this limit are rejected.\n"
        f"      Default: {DEFAULT_MAX_SESSIONS}\n"
        "      Env:     LLM_PROXY_MAX_SESSIONS\n"
        "\n"
        "  --max-history N\n"
        "      Maximum number of messages retained per session.\n"
        "      Oldest messages are dropped first, but an\n"
        "      assistant.tool_calls message and its matching\n"
        "      role=tool replies are never separated.\n"
        f"      Default: {DEFAULT_MAX_HISTORY}\n"
        "      Env:     LLM_PROXY_MAX_HISTORY\n"
        "\n"
        "  --max-history-chars N\n"
        "      Maximum total character count of the message history\n"
        "      per session. Prevents unbounded growth from accumulated\n"
        "      tool results in long-lived sessions.\n"
        f"      Default: {DEFAULT_MAX_HISTORY_CHARS}\n"
        "      Env:     LLM_PROXY_MAX_HISTORY_CHARS\n"
        "\n"
        "  --session-timeout SECONDS\n"
        "      Idle timeout for sessions. A session that has not seen\n"
        "      any `generate` request for this long is reclaimed.\n"
        f"      Default: {DEFAULT_SESSION_TIMEOUT}\n"
        "      Env:     LLM_PROXY_SESSION_TIMEOUT\n"
        "\n"
        "Tools (MCP)\n"
        "-----------\n"
        "  --enable-tools / --no-tools\n"
        "      Enable or disable all tool-related behavior. When\n"
        "      disabled, the proxy behaves exactly like llm_proxy.py.\n"
        f"      Default: {'enabled' if DEFAULT_ENABLE_TOOLS else 'disabled'}\n"
        "      Env:     LLM_PROXY_ENABLE_TOOLS\n"
        "\n"
        "  --mcp-endpoint ADDRESS\n"
        "      LingoFuse endpoint of the MCP tool provider (beacon).\n"
        f"      Default: {DEFAULT_MCP_ENDPOINT}\n"
        "      Env:     LLM_PROXY_MCP_ENDPOINT\n"
        "\n"
        "  --mcp-timeout MS\n"
        "      Timeout for MCP tool discovery and tool invocation.\n"
        f"      Default: {DEFAULT_MCP_TIMEOUT_MS}\n"
        "      Env:     LLM_PROXY_MCP_TIMEOUT\n"
        "\n"
        "  --mcp-reg-agent-app NAME\n"
        "      Registration agent app name used by this proxy. MUST\n"
        "      differ from the one used by mcp_api_tool.py (which\n"
        "      uses `reg_agent`) so the two can run simultaneously.\n"
        f"      Default: {DEFAULT_MCP_REG_AGENT_APP}\n"
        "      Env:     LLM_PROXY_MCP_REG_AGENT_APP\n"
        "\n"
        "  --mcp-tool-provider-app NAME\n"
        "      App name of the tool provider (the Pascal backend).\n"
        f"      Default: {DEFAULT_MCP_TOOL_PROVIDER_APP}\n"
        "      Env:     LLM_PROXY_MCP_TOOL_PROVIDER_APP\n"
        "\n"
        "  --max-tool-rounds N\n"
        "      Maximum model<->tool round trips per `generate` call.\n"
        "      Higher values allow longer tool chains but also risk\n"
        "      longer waits if the model loops. The last round is\n"
        "      always a forced text-answer round.\n"
        f"      Default: {DEFAULT_MAX_TOOL_ROUNDS}\n"
        "      Env:     LLM_PROXY_MAX_TOOL_ROUNDS\n"
        "\n"
        "  --max-total-tool-calls N\n"
        "      Maximum number of tool calls executed in a single\n"
        "      `generate` call, across all rounds. Reaching this cap\n"
        "      forces the loop into the final text-answer round.\n"
        f"      Default: {DEFAULT_MAX_TOTAL_TOOL_CALLS}\n"
        "      Env:     LLM_PROXY_MAX_TOTAL_TOOL_CALLS\n"
        "\n"
        "  --max-tools-per-round N\n"
        "      Maximum number of tool calls processed from a single\n"
        "      backend response (OpenAI allows batch tool_calls).\n"
        f"      Default: {DEFAULT_MAX_TOOLS_PER_ROUND}\n"
        "      Env:     LLM_PROXY_MAX_TOOLS_PER_ROUND\n"
        "\n"
        "  --max-tool-result-chars N\n"
        "      Maximum length of a single tool result string.\n"
        f"      Default: {DEFAULT_MAX_TOOL_RESULT_CHARS}\n"
        "      Env:     LLM_PROXY_MAX_TOOL_RESULT_CHARS\n"
        "\n"
        "  --max-total-tool-result-chars N\n"
        "      Maximum total character count of all tool results in\n"
        "      a single `generate` call. Prevents unbounded growth\n"
        "      from looping tool calls.\n"
        f"      Default: {DEFAULT_MAX_TOTAL_TOOL_RESULT_CHARS}\n"
        "      Env:     LLM_PROXY_MAX_TOTAL_TOOL_RESULT_CHARS\n"
        "\n"
        "Logging\n"
        "-------\n"
        "  --log-level LEVEL\n"
        "      Log verbosity: DEBUG, INFO, WARNING, ERROR.\n"
        "      At INFO and above, the service is silent during normal\n"
        "      operation; only startup, shutdown, session lifecycle,\n"
        "      and errors are logged. Use DEBUG to see per-round and\n"
        "      per-tool details.\n"
        f"      Default: {DEFAULT_LOG_LEVEL}\n"
        "      Env:     LLM_PROXY_LOG_LEVEL\n"
        "\n"
        "Examples\n"
        "--------\n"
        f"  # Minimal: LM Studio backend, all defaults\n"
        f"  {invocation} --backend-url http://127.0.0.1:1234/v1\n"
        "\n"
        f"  # Tools disabled (pure text proxy, like llm_proxy.py)\n"
        f"  {invocation} --no-tools\n"
        "\n"
        f"  # Larger tool budget\n"
        f"  {invocation} --max-tool-rounds 200 "
        f"--max-total-tool-calls 100\n"
        "\n"
        f"  # Coexist with mcp_api_tool.py on the same beacon\n"
        f"  {invocation} --mcp-reg-agent-app llm_proxy_agent "
        f"--mcp-tool-provider-app agent_main_app\n"
        "\n"
        f"  # Verbose debugging\n"
        f"  {invocation} --log-level DEBUG\n"
        "\n"
        "Relationship with siblings\n"
        "--------------------------\n"
        "  llm_service.py      - local inference (llama.cpp)\n"
        "  llm_proxy.py        - pure text proxy\n"
        "  llm_proxy_tool.py   - proxy with server-side tools (this file)\n"
        "  mcp_api_tool.py     - MCP tool gateway (Host-side)\n"
        "\n"
        "  llm_proxy_tool and mcp_api_tool CAN coexist. All three\n"
        "  LLM services share the default endpoint ipc:llm_service\n"
        "  and app name LLM_Service, so only ONE may run at any time\n"
        "  unless you override --endpoint and --app-name.\n"
        "\n"
        "API capability advertisement\n"
        "----------------------------\n"
        f"  Supported APIs   : {', '.join(supported)}\n"
        f"  Unsupported APIs : {', '.join(unsupported) or '(none)'}\n"
        "    (call get_api_capabilities at runtime for the canonical map)\n"
    )

    parser = argparse.ArgumentParser(
        prog=get_invocation_name(),
        description=(
            "LingoFuse LLM Tool Bridge (LTB) - v2.1\n"
            "\n"
            "A proxy that forwards to an OpenAI-compatible HTTP backend,\n"
            "with optional server-side MCP tool execution via\n"
            "language_middleware.\n"
            "\n"
            "The client sends a normal `generate` request and receives a\n"
            "normal `chunk` / `think` / `finish` stream. All tool-call\n"
            "plumbing happens server-side; zero client changes required.\n"
            "\n"
            "Run with --help for a full command-line reference."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ---- LingoFuse service ----
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("LLM_PROXY_ENDPOINT", DEFAULT_ENDPOINT),
        metavar="ADDRESS",
        help="LingoFuse service endpoint. Default: ipc:llm_service")
    parser.add_argument(
        "--app-name",
        default=os.environ.get("LLM_PROXY_APP_NAME", DEFAULT_APP_NAME),
        metavar="NAME",
        help="LingoFuse application name. Default: LLM_Service")
    parser.add_argument(
        "--notify-api",
        default=os.environ.get("LLM_PROXY_NOTIFY_API", DEFAULT_NOTIFY_API),
        metavar="NAME",
        help="Notify API name for streaming chunks. Default: llm_stream")

    # ---- Backend ----
    parser.add_argument(
        "--backend-url",
        default=os.environ.get("LLM_PROXY_BACKEND_URL", DEFAULT_BACKEND_URL),
        metavar="URL",
        help="Base URL of the OpenAI-compatible backend. "
             "Default: http://127.0.0.1:12345/v1")
    parser.add_argument(
        "--backend-model",
        default=os.environ.get("LLM_PROXY_BACKEND_MODEL",
                               DEFAULT_BACKEND_MODEL),
        metavar="ID",
        help="Model id sent to the backend. Empty = auto-discover.")
    parser.add_argument(
        "--backend-key",
        default=os.environ.get("LLM_PROXY_BACKEND_KEY", DEFAULT_BACKEND_KEY),
        metavar="KEY",
        help="API key / token. Default: lm-studio")
    parser.add_argument(
        "--backend-key-file",
        default=os.environ.get("LLM_PROXY_BACKEND_KEY_FILE",
                               DEFAULT_BACKEND_KEY_FILE),
        metavar="PATH",
        help="File containing the API key; overrides --backend-key.")
    parser.add_argument(
        "--backend-auth-header",
        default=os.environ.get("LLM_PROXY_BACKEND_AUTH_HEADER",
                               DEFAULT_BACKEND_AUTH_HEADER),
        metavar="NAME",
        help="Header carrying the token. Default: Authorization")
    parser.add_argument(
        "--backend-auth-scheme",
        default=os.environ.get("LLM_PROXY_BACKEND_AUTH_SCHEME",
                               DEFAULT_BACKEND_AUTH_SCHEME),
        metavar="PREFIX",
        help="Scheme prefix. Empty string = raw token. Default: Bearer")
    parser.add_argument(
        "--backend-extra-headers",
        default=os.environ.get("LLM_PROXY_BACKEND_EXTRA_HEADERS",
                               DEFAULT_BACKEND_EXTRA_HEADERS),
        metavar="JSON",
        help="Extra HTTP headers as JSON. Default: {}")
    parser.add_argument(
        "--backend-timeout", type=int,
        default=int(os.environ.get("LLM_PROXY_BACKEND_TIMEOUT",
                                   DEFAULT_BACKEND_TIMEOUT)),
        metavar="SECONDS",
        help="HTTP read timeout for backend streaming. Default: 300")

    # ---- Sessions ----
    parser.add_argument(
        "--max-history", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_HISTORY",
                                   DEFAULT_MAX_HISTORY)),
        metavar="N",
        help="Max messages retained per session. Default: 512")
    parser.add_argument(
        "--max-history-chars", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_HISTORY_CHARS",
                                   DEFAULT_MAX_HISTORY_CHARS)),
        metavar="N",
        help="Max total characters of message history per session. "
             "Default: 200000")
    parser.add_argument(
        "--max-sessions", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_SESSIONS",
                                   DEFAULT_MAX_SESSIONS)),
        metavar="N",
        help="Max concurrent sessions. Default: 1024")
    parser.add_argument(
        "--session-timeout", type=int,
        default=int(os.environ.get("LLM_PROXY_SESSION_TIMEOUT",
                                   DEFAULT_SESSION_TIMEOUT)),
        metavar="SECONDS",
        help="Idle timeout for sessions. Default: 1800")

    # ---- LTB / tools ----
    parser.add_argument(
        "--enable-tools", dest="enable_tools", action="store_true",
        default=os.environ.get("LLM_PROXY_ENABLE_TOOLS", "1").lower()
        in ("1", "true", "yes"),
        help="Enable MCP tool discovery and server-side execution "
             "(default).")
    parser.add_argument(
        "--no-tools", dest="enable_tools", action="store_false",
        help="Disable all tool-related behavior; behave like llm_proxy.py.")
    parser.add_argument(
        "--mcp-endpoint",
        default=os.environ.get("LLM_PROXY_MCP_ENDPOINT",
                               DEFAULT_MCP_ENDPOINT),
        metavar="ADDRESS",
        help="LingoFuse endpoint of the MCP tool provider. "
             "Default: ipc:agent")
    parser.add_argument(
        "--mcp-timeout", type=int,
        default=int(os.environ.get("LLM_PROXY_MCP_TIMEOUT",
                                   DEFAULT_MCP_TIMEOUT_MS)),
        metavar="MS",
        help="MCP call timeout in ms. Default: 5000")
    parser.add_argument(
        "--mcp-reg-agent-app",
        default=os.environ.get("LLM_PROXY_MCP_REG_AGENT_APP",
                               DEFAULT_MCP_REG_AGENT_APP),
        metavar="NAME",
        help="Registration agent app name for MCP middleware. "
             "Default: llm_proxy_agent (distinct from mcp_api_tool).")
    parser.add_argument(
        "--mcp-tool-provider-app",
        default=os.environ.get("LLM_PROXY_MCP_TOOL_PROVIDER_APP",
                               DEFAULT_MCP_TOOL_PROVIDER_APP),
        metavar="NAME",
        help="Tool provider app name. Default: agent_main_app")
    parser.add_argument(
        "--max-tool-rounds", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_TOOL_ROUNDS",
                                   DEFAULT_MAX_TOOL_ROUNDS)),
        metavar="N",
        help="Max tool-call rounds per generate. Default: 100")
    parser.add_argument(
        "--max-total-tool-calls", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_TOTAL_TOOL_CALLS",
                                   DEFAULT_MAX_TOTAL_TOOL_CALLS)),
        metavar="N",
        help="Max total tool calls per generate. Default: 50")
    parser.add_argument(
        "--max-tools-per-round", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_TOOLS_PER_ROUND",
                                   DEFAULT_MAX_TOOLS_PER_ROUND)),
        metavar="N",
        help="Max tools processed per round. Default: 10")
    parser.add_argument(
        "--max-tool-result-chars", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_TOOL_RESULT_CHARS",
                                   DEFAULT_MAX_TOOL_RESULT_CHARS)),
        metavar="N",
        help="Truncate a single tool result above this length. "
             "Default: 8000")
    parser.add_argument(
        "--max-total-tool-result-chars", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_TOTAL_TOOL_RESULT_CHARS",
                                   DEFAULT_MAX_TOTAL_TOOL_RESULT_CHARS)),
        metavar="N",
        help="Truncate total tool results per generate above this "
             "length. Default: 200000")

    # ---- Logging ----
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LLM_PROXY_LOG_LEVEL",
                               DEFAULT_LOG_LEVEL).upper(),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity. Default: INFO")

    return parser.parse_args()


def _init_global_config(args: argparse.Namespace) -> None:
    """
    Copy parsed arguments into the global CONFIG object.

    After this function returns, no runtime code will read
    `os.environ` or `sys.argv` again. Everything reads from CONFIG.
    """
    # LingoFuse service
    CONFIG.endpoint = args.endpoint
    CONFIG.app_name = args.app_name
    CONFIG.notify_api = args.notify_api

    # Backend
    CONFIG.backend_url = args.backend_url.rstrip("/")
    CONFIG.backend_model = args.backend_model
    CONFIG.backend_key = args.backend_key
    CONFIG.backend_key_file = args.backend_key_file
    CONFIG.backend_auth_header = args.backend_auth_header
    CONFIG.backend_auth_scheme = args.backend_auth_scheme
    CONFIG.backend_timeout = args.backend_timeout

    # Sessions
    CONFIG.max_history = max(2, args.max_history)
    CONFIG.max_history_chars = max(1000, args.max_history_chars)
    CONFIG.max_sessions = max(1, args.max_sessions)
    CONFIG.session_timeout = max(10, args.session_timeout)

    # Logging
    CONFIG.log_level = args.log_level

    # LTB / MCP
    CONFIG.enable_tools = bool(args.enable_tools)
    CONFIG.mcp_endpoint = args.mcp_endpoint
    CONFIG.mcp_timeout_ms = max(100, args.mcp_timeout)
    CONFIG.mcp_reg_agent_app = args.mcp_reg_agent_app
    CONFIG.mcp_tool_provider_app = args.mcp_tool_provider_app
    CONFIG.max_tool_rounds = max(1, args.max_tool_rounds)
    CONFIG.max_total_tool_calls = max(1, args.max_total_tool_calls)
    CONFIG.max_tools_per_round = max(1, args.max_tools_per_round)
    CONFIG.max_tool_result_chars = max(64, args.max_tool_result_chars)
    CONFIG.max_total_tool_result_chars = max(
        64, args.max_total_tool_result_chars)

    # Extra headers
    try:
        CONFIG.backend_extra_headers = _parse_extra_headers(
            args.backend_extra_headers)
    except ValueError as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        sys.exit(1)

    # Key file overrides --backend-key
    if CONFIG.backend_key_file:
        try:
            CONFIG.backend_key = _load_key_from_file(CONFIG.backend_key_file)
        except ValueError as e:
            print(f"[FATAL] {e}", file=sys.stderr)
            sys.exit(1)

    # Apply log level (root logger + our own)
    lvl = getattr(logging, CONFIG.log_level, logging.INFO)
    logging.getLogger().setLevel(lvl)
    logger.setLevel(lvl)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    _init_global_config(args)

    print_banner()

    if not _HAS_MIDDLEWARE:
        logger.warning("language_middleware not found on PYTHONPATH. "
                       "Tool features will be unavailable; "
                       "the program will behave as a pure-text proxy.")

    service: Optional[LLMProxyToolService] = None
    try:
        service = LLMProxyToolService()
        atexit.register(service.stop)
        _install_signal_handlers()
    except Exception as e:
        logger.error("Failed to construct service: %s", e)
        return 1

    try:
        service.start()
        logger.info("Press Ctrl+C to stop...")
        while not _SHUTDOWN.is_set():
            if _SHUTDOWN.wait(timeout=1.0):
                break
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error("Service error: %s", e)
        return 1
    finally:
        logger.info("Shutting down")
        try:
            service.stop()
        except Exception as e:
            logger.error("Final stop error: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())