#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LingoFuse LLM Proxy - LingoFuse service forwarding to OpenAI-compatible backends.

Role
----
LingoFuse SERVICE that registers as LLM_Service on ipc:llm_service and
forwards each generate request to an OpenAI-compatible HTTP backend
(LM Studio, Ollama, vLLM, DeepSeek, OpenRouter, Azure OpenAI, ...).
Streaming chunks are relayed back to LingoFuse clients through
LF_Sequenced_Notify.

Backend transport
-----------------
Streaming uses Python's standard-library http.client module, NOT
requests. requests / urllib3 buffer SSE responses at the socket layer,
which manifests as multi-second silence followed by a batch of text -
no combination of iter_lines / iter_content / Accept-Encoding settings
avoids it. http.client's HTTPResponse reads directly from the socket
via a BufferedReader; `for line in resp:` yields a line the instant a
newline arrives from the wire.

Reasoning models
----------------
Reasoning models (Nemotron, DeepSeek-R1, Qwen3-thinking, ...) emit two
distinct fields in each SSE delta:

    reasoning_content  - the internal thinking chain
    content            - the final user-visible answer

Both are forwarded to the LingoFuse client without any policy applied
here. The client decides what to display:

    reasoning_content  ->  {"type": "think", ...}
    content            ->  {"type": "chunk", ...}

Whether a model produces a thinking chain at all is determined by the
backend and its model configuration, not by this proxy. There is no
proxy-side switch; the stream that arrives from the backend is
forwarded as-is.

set_system_message is not supported
-----------------------------------
Unlike llm_service.py (which owns an in-process message history), this
proxy is a STATELESS FORWARDER. Each session captures its system
message at creation time and rebuilds the messages array before every
backend call. Changing the system message of an existing session would
require the backend to re-process the entire history from a different
context, which is impossible without invalidating the model's KV cache.

The set_system_message API therefore returns:

    {"code": -1, "status": "unsupported", "error": "..."}

Clients that need a different system message must:

    1. close_session(current_session_id)
    2. create_session(client_name, system_message=<new message>)
    3. continue with the new session_id

Other client-side options that the proxy cannot honour (for example
`thinking` and `ephemeral`, which are backend-specific concepts) are
silently ignored; their keys are logged at DEBUG level so operators can
see what was dropped.

Relationship with llm_service.py
--------------------------------
Siblings with identical Call API surface EXCEPT set_system_message,
which is a no-op here. Because the default endpoint (ipc:llm_service)
and app name (LLM_Service) are the same, ONLY ONE of the two may run
at a given time.

API capability advertisement
----------------------------
Clients can discover which LLM-service APIs this server supports by
calling the `get_api_capabilities` Call API. It returns a JSON object:

    {"code": 0,
     "server_kind": "proxy",           # or "service"
     "capabilities": {"<api_name>": 0|1, ...}}

The same dictionary is included in the `health` response under the
field `api_capabilities`. A value of 1 means the API is supported by
this server, 0 means it is not (it belongs to the sibling server kind).

Client-side helpers can wrap this lookup, for example:

    llm_supported(api_name) -> bool

which internally calls `get_api_capabilities` and returns whether the
given API name maps to 1.

Authentication (token) support
------------------------------
    --backend-key, --backend-key-file, --backend-auth-header,
    --backend-auth-scheme, --backend-extra-headers

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


# ----------------------------------------------------------------------
# Frozen-executable detection and help-text invocation helpers
#
# The proxy can be launched in two ways:
#   1. From source:    python llm_proxy.py [OPTIONS]
#   2. As a frozen exe: llm_proxy.exe [OPTIONS]
#
# The `--help` output adapts its usage line and examples accordingly so
# the user always sees the correct command for the current packaging.
# ----------------------------------------------------------------------
def is_frozen_exe() -> bool:
    """
    Return True if this process is running from a frozen executable.

    Detects PyInstaller (one-file or one-dir) and Nuitka by checking
    both `sys.frozen` and `sys._MEIPASS`. This mirrors the detection
    used by llm_service.py, llm_test.py, mcp_api_tool.py and mcp_api_proxy.py
    in the same project.
    """
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')


def get_invocation_name() -> str:
    """
    Return the program name shown at the top of `--help` (the `prog=`
    value).

    - Frozen exe: the exe filename, e.g. "llm_proxy.exe".
    - Script:     the script filename, e.g. "llm_proxy.py".
    """
    if is_frozen_exe():
        return os.path.basename(sys.executable)
    return os.path.basename(os.path.abspath(__file__))


def get_example_invocation() -> str:
    """
    Return the full command prefix used in the `--help` examples.

    - Frozen exe: "llm_proxy.exe"
    - Script:     "python llm_proxy.py"
    """
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
DEFAULT_MAX_SESSIONS = 1024
DEFAULT_SESSION_TIMEOUT = 1800

DEFAULT_LOG_LEVEL = "INFO"

# Options keys accepted from clients and forwarded to the backend.
# Anything else is dropped and (at DEBUG level) logged.
_FORWARDED_OPTION_KEYS = frozenset((
    "max_tokens", "temperature", "top_p", "top_k", "repeat_penalty",
))


# ----------------------------------------------------------------------
# API capability matrix
#
# Keys are the full set of APIs that an LLM server in this ecosystem
# may expose. Values are integers:
#
#     1  = supported by THIS server kind (llm_proxy)
#     0  = NOT supported by this server kind (belongs to llm_service)
#
# Clients should call the `get_api_capabilities` Call API (or read the
# `api_capabilities` field of `health`) to discover this dictionary at
# runtime, instead of hard-coding it.
#
# Rationale for each 0/1 value:
#   * generate, create_session, close_session, cancel_session,
#     list_sessions, health
#       -> forwarded transparently to the backend, supported.
#   * set_system_message
#       -> llm_service-only feature. The proxy is a stateless forwarder;
#          changing the system message of an existing session would
#          require re-processing the whole history on the backend side.
#   * llm_stream
#       -> Notify API used for streaming chunks; identical semantics in
#          both server kinds.
# ----------------------------------------------------------------------
API_CAPABILITIES: Dict[str, int] = {
    # ---- Call APIs (llm_service v3.0 exposed set) ----
    "generate":           1,   # forwarded to backend
    "create_session":     1,   # session registry is owned by the proxy
    "close_session":      1,   # session registry is owned by the proxy
    "cancel_session":     1,   # cancels the in-flight backend stream
    "list_sessions":      1,   # session registry is owned by the proxy
    "set_system_message": 0,   # llm_service-only (stateful history)
    "health":             1,   # proxy reports its own status

    # ---- Notify API (streaming chunks back to the client) ----
    "llm_stream":         1,   # same semantics as in llm_service
}

# Identifies which server kind is answering. Included in the
# `get_api_capabilities` and `health` responses so that clients can
# branch on it if they need to.
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
logger = logging.getLogger("llm_proxy")


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
class ProxyConfig:
    def __init__(self) -> None:
        self.endpoint: str = DEFAULT_ENDPOINT
        self.app_name: str = DEFAULT_APP_NAME
        self.notify_api: str = DEFAULT_NOTIFY_API

        self.backend_url: str = DEFAULT_BACKEND_URL
        self.backend_model: str = DEFAULT_BACKEND_MODEL
        self.backend_key: str = DEFAULT_BACKEND_KEY
        self.backend_key_file: str = DEFAULT_BACKEND_KEY_FILE
        self.backend_auth_header: str = DEFAULT_BACKEND_AUTH_HEADER
        self.backend_auth_scheme: str = DEFAULT_BACKEND_AUTH_SCHEME
        self.backend_extra_headers: Dict[str, str] = {}
        self.backend_timeout: int = DEFAULT_BACKEND_TIMEOUT

        self.max_history: int = DEFAULT_MAX_HISTORY
        self.max_sessions: int = DEFAULT_MAX_SESSIONS
        self.session_timeout: int = DEFAULT_SESSION_TIMEOUT

        self.log_level: str = DEFAULT_LOG_LEVEL


CONFIG = ProxyConfig()


# ----------------------------------------------------------------------
# JSON helper
# ----------------------------------------------------------------------
def jdump(obj: Any) -> bytes:
    """
    Serialize to UTF-8 bytes with literal Unicode characters.

    ensure_ascii=False guarantees that Chinese, emoji and other
    non-ASCII content is emitted as-is, never as \\uXXXX escapes.
    """
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


# ----------------------------------------------------------------------
# Header helpers
# ----------------------------------------------------------------------
def _parse_extra_headers(raw: str) -> Dict[str, str]:
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
    def __init__(self, session_id: str, client_name: str,
                 system_message: str = "") -> None:
        self.session_id = session_id
        self.client_name = client_name
        # The system message is captured at session creation and never
        # changes for the lifetime of the session. See the module
        # docstring for why set_system_message is unsupported here.
        self.system_message = system_message
        self.messages: List[Dict[str, str]] = []
        self.created_at = time.time()
        self.last_active = self.created_at
        self.cancel_event: Optional[threading.Event] = None
        self.running: bool = False
        self.lock = threading.Lock()

    def add_user(self, content: str) -> None:
        with self.lock:
            self.messages.append({"role": "user", "content": content})
            self._trim_locked()

    def add_assistant(self, content: str) -> None:
        with self.lock:
            self.messages.append({"role": "assistant", "content": content})
            self._trim_locked()

    def _trim_locked(self) -> None:
        if len(self.messages) > CONFIG.max_history:
            excess = len(self.messages) - CONFIG.max_history
            del self.messages[:excess]

    def snapshot(self) -> List[Dict[str, str]]:
        with self.lock:
            return [dict(m) for m in self.messages]

    def touch(self) -> None:
        with self.lock:
            self.last_active = time.time()

    def begin_run(self) -> threading.Event:
        with self.lock:
            ev = threading.Event()
            self.cancel_event = ev
            self.running = True
            return ev

    def end_run(self) -> None:
        with self.lock:
            self.cancel_event = None
            self.running = False
            self.last_active = time.time()

    def request_cancel(self) -> bool:
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
    HTTP+SSE client using Python's standard-library http.client.

    Why http.client instead of requests:
        requests / urllib3 buffer the SSE response at the socket layer
        in ways that no iter_content / iter_lines / Accept-Encoding
        configuration can disable. HTTPResponse from http.client wraps
        the raw socket in a BufferedReader, and iterating over the
        response yields a line the moment its terminating newline
        arrives.
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
                headers[self.auth_header] = f"{self.auth_scheme} {self.api_key}"
            else:
                headers[self.auth_header] = self.api_key
        headers.update(self.extra_headers)
        return headers

    def list_models(self) -> List[str]:
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
        messages: List[Dict[str, str]],
        options: Dict[str, Any],
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[Dict[str, str]]:
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers("text/event-stream")

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        for key in ("max_tokens", "temperature", "top_p",
                    "top_k", "repeat_penalty"):
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

        logger.info("Backend request: url=%s model=%s msgs=%d",
                    url, model, len(messages))

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
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
            logger.info("Backend response: status=%d content_type=%r",
                        resp.status, resp.getheader("Content-Type"))

            if resp.status >= 400:
                try:
                    detail = resp.read().decode("utf-8",
                                                errors="replace")[:500]
                except Exception:
                    detail = ""
                raise RuntimeError(
                    f"Backend HTTP {resp.status}: {detail}")

            # Iterating the HTTPResponse yields a line the moment its
            # terminating newline arrives; there is no intermediate
            # buffer beyond the underlying BufferedReader.
            for raw_line in resp:
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("Backend stream cancelled by client")
                    return

                line = raw_line.decode(
                    "utf-8", errors="replace").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    return

                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                delta = self._extract_delta(obj)
                if delta:
                    yield delta

        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _extract_delta(obj: Dict[str, Any]) -> Optional[Dict[str, str]]:
        choices = obj.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        delta = choice.get("delta") or {}
        out: Dict[str, str] = {}
        content = delta.get("content")
        reasoning = delta.get("reasoning_content")
        if isinstance(content, str) and content:
            out["content"] = content
        if isinstance(reasoning, str) and reasoning:
            out["reasoning_content"] = reasoning
        return out or None


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
class LLMProxyService:
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

        self.server = Server(
            CONFIG.app_name,
            "LingoFuse LLM Proxy - forwards to an OpenAI-compatible backend")
        self._register_apis()

    def resolve_model(self) -> str:
        if self._resolved_model:
            return self._resolved_model
        ids = self._backend.list_models()
        if ids:
            self._resolved_model = ids[0]
            logger.info("Auto-selected backend model: %s", self._resolved_model)
        else:
            self._resolved_model = "unknown"
            logger.warning(
                "Could not auto-discover backend model; "
                "set LLM_PROXY_BACKEND_MODEL or --backend-model")
        return self._resolved_model

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

    def _count_sessions(self) -> int:
        with self._sessions_lock:
            return len(self._sessions)

    def _lookup(self, session_id: str) -> Optional[SessionState]:
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def _create(self, client_name: str,
                system_message: str = "") -> SessionState:
        sid = str(uuid.uuid4())
        sess = SessionState(sid, client_name, system_message)
        with self._sessions_lock:
            self._sessions[sid] = sess
        return sess

    def _drop(self, session_id: str) -> Optional[SessionState]:
        with self._sessions_lock:
            return self._sessions.pop(session_id, None)

    def _handle_generate(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"code": -1, "error": "generate expects a JSON object"}

        content = data.get("content", "") or ""
        prompt = data.get("prompt", "") or ""
        client_name = data.get("client_name")
        session_id = data.get("session_id")
        options_raw = data.get("options", {}) or {}

        if not content and not prompt:
            return {"code": -1, "error": "Missing content or prompt"}
        if not isinstance(options_raw, dict):
            return {"code": -1, "error": "options must be a JSON object"}
        if session_id is not None and not isinstance(session_id, str):
            return {"code": -1, "error": "session_id must be a string"}

        options = self._sanitize_options(options_raw)

        mode: str
        if session_id:
            sess = self._lookup(session_id)
            if sess is None:
                return {"code": -1,
                        "error": f"Session not found: {session_id}"}
            if sess.running:
                return {"code": -1,
                        "error": f"Session already running: {session_id}"}
            if client_name and client_name != sess.client_name:
                return {"code": -1,
                        "error": "client_name does not match session owner"}
            mode = "continue"
        else:
            if not client_name or not isinstance(client_name, str):
                return {"code": -1,
                        "error": "Missing client_name for new session"}
            if self._count_sessions() >= CONFIG.max_sessions:
                return {"code": -1,
                        "error": f"Session limit reached "
                                 f"({CONFIG.max_sessions})"}
            # New sessions start with an empty system message. The
            # client is expected to provide one through create_session
            # if it needs a custom prompt.
            sess = self._create(client_name)
            mode = "new"

        task_id = str(uuid.uuid4())
        sess.touch()

        t = threading.Thread(
            target=self._run_generation,
            args=(sess, task_id, content, prompt, options),
            name=f"llm-proxy-{task_id[:8]}",
            daemon=True,
        )
        t.start()

        logger.info("generate queued: mode=%s session=%s task=%s",
                    mode, sess.session_id, task_id)
        return {
            "code": 0,
            "session_id": sess.session_id,
            "task_id": task_id,
            "mode": mode,
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
        if self._count_sessions() >= CONFIG.max_sessions:
            return {"code": -1,
                    "error": f"Session limit reached ({CONFIG.max_sessions})"}
        sess = self._create(client_name, system_message)
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
            return {"code": -1, "error": f"Session not found: {session_id}"}
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
            return {"code": -1, "error": f"Session not found: {session_id}"}
        ok = sess.request_cancel()
        logger.info("Cancel requested for session %s (running=%s)",
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

        The proxy is a stateless forwarder: each session captures its
        system_message at creation and rebuilds the messages array
        before every backend call. Changing the system message of an
        existing session would require reprocessing the entire history
        from the backend's perspective, which cannot be done safely
        without invalidating the model's KV cache.

        This handler returns a deterministic unsupported response for
        every invocation, whether or not the request is well-formed.
        The message explains the recommended replacement workflow.
        """
        logger.info("set_system_message rejected: not supported by "
                    "llm_proxy (stateless forwarder)")
        return {
            "code": -1,
            "status": "unsupported",
            "error": (
                "set_system_message is not supported by llm_proxy. \n"
                "The system message is fixed at session creation. \n"
                "To change it, close the current session and create \n"
                "a new one with the desired system_message.\n"
            ),
        }

    def _handle_get_api_capabilities(self, data: Any) -> Dict[str, Any]:
        """
        Return the API capability matrix for this server kind.

        Response shape:
            {
              "code": 0,
              "server_kind": "proxy",
              "capabilities": {
                  "<api_name>": 0 | 1,
                  ...
              }
            }

        A value of 1 means the API is supported by this server,
        0 means it is not (it belongs to the sibling server kind,
        llm_service). Clients should call this API at startup or
        before invoking any feature that may be server-kind specific,
        for example set_system_message.
        """
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

        return {
            "code": 0,
            "status": "ok",
            "server_kind": SERVER_KIND,
            "backend_url": CONFIG.backend_url,
            "backend_model": self._resolved_model or CONFIG.backend_model,
            "backend_auth_header": CONFIG.backend_auth_header,
            "backend_auth_scheme": CONFIG.backend_auth_scheme,
            "backend_auth_configured": auth_configured,
            "backend_extra_headers": list(CONFIG.backend_extra_headers.keys()),
            "notify_api": CONFIG.notify_api,
            "set_system_message_supported": False,
            "sessions_total": len(sessions),
            "sessions_idle": idle,
            "sessions_running": running,
            "session_limit": CONFIG.max_sessions,
            "session_timeout": CONFIG.session_timeout,
            # The capability matrix is included in health so that a
            # single call is enough for a client to learn everything it
            # needs about this server kind.
            "api_capabilities": dict(API_CAPABILITIES),
        }

    @staticmethod
    def _sanitize_options(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Keep only the option keys that this proxy forwards to the
        backend. Everything else is dropped and, at DEBUG level, its
        key is logged so that operators can see what was ignored.
        """
        out: Dict[str, Any] = {}

        if logger.isEnabledFor(logging.DEBUG):
            unsupported = [k for k in raw.keys()
                           if k not in _FORWARDED_OPTION_KEYS]
            if unsupported:
                logger.debug(
                    "Options keys not supported by the proxy and ignored: %s",
                    ", ".join(unsupported))

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
        return out

    def _run_generation(self, sess: SessionState, task_id: str,
                        content: str, prompt: str,
                        options: Dict[str, Any]) -> None:
        cancel_event = sess.begin_run()
        user_text = content + ("\n\n" + prompt if prompt else "")

        history = sess.snapshot()
        messages: List[Dict[str, str]] = []
        if sess.system_message:
            messages.append({"role": "system",
                             "content": sess.system_message})
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        model = self._resolved_model or CONFIG.backend_model
        if not model:
            model = self.resolve_model()

        answer_pieces: List[str] = []
        think_pieces: List[str] = []
        error_message: Optional[str] = None

        try:
            for delta in self._backend.stream_chat(
                    model, messages, options, cancel_event=cancel_event):
                if cancel_event.is_set():
                    break
                # reasoning_content -> think event
                if "reasoning_content" in delta:
                    text = delta["reasoning_content"]
                    think_pieces.append(text)
                    self._emit(sess, {"type": "think",
                                      "session_id": sess.session_id,
                                      "text": text})
                # content -> chunk event
                if "content" in delta:
                    text = delta["content"]
                    answer_pieces.append(text)
                    self._emit(sess, {"type": "chunk",
                                      "session_id": sess.session_id,
                                      "text": text})
        except Exception as e:
            error_message = str(e)
            logger.error("Task %s backend error: %s", task_id, error_message)
            self._emit(sess, {"type": "error",
                              "session_id": sess.session_id,
                              "message": error_message})

        if error_message is None:
            sess.add_user(user_text)
            sess.add_assistant("".join(answer_pieces))

        if cancel_event.is_set():
            self._emit(sess, {"type": "finish",
                              "session_id": sess.session_id,
                              "reason": "cancelled"})
        elif error_message is not None:
            self._emit(sess, {"type": "finish",
                              "session_id": sess.session_id,
                              "reason": "error"})
        else:
            self._emit(sess, {"type": "finish",
                              "session_id": sess.session_id,
                              "reason": "stop"})

        sess.end_run()
        logger.info("Task %s finished: session=%s chars=%d think_chars=%d "
                    "cancelled=%s error=%s",
                    task_id, sess.session_id, len("".join(answer_pieces)),
                    len("".join(think_pieces)), cancel_event.is_set(),
                    error_message is not None)

    def _emit(self, sess: SessionState, payload: Dict[str, Any]) -> None:
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
            logger.warning("Notify to '%s' failed: %s",
                           sess.client_name, e)
        finally:
            if hnd is not None:
                try:
                    hnd.free()
                except Exception:
                    pass

    def _watchdog_loop(self) -> None:
        while not self._shutdown.wait(timeout=5.0):
            now = time.time()
            expired: List[str] = []
            with self._sessions_lock:
                for sid, sess in self._sessions.items():
                    if sess.running:
                        continue
                    if now - sess.last_active > CONFIG.session_timeout:
                        expired.append(sid)
                for sid in expired:
                    self._sessions.pop(sid, None)
            for sid in expired:
                logger.info("Session %s expired by idle timeout", sid)

    def start(self) -> None:
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
        threading.Thread(target=self._watchdog_loop,
                         name="llm-proxy-watchdog", daemon=True).start()
        self.server.start(CONFIG.endpoint)
        logger.info("LLM Proxy service '%s' running on %s",
                    CONFIG.app_name, CONFIG.endpoint)

    def stop(self) -> None:
        self._shutdown.set()
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        for sess in sessions:
            sess.request_cancel()
        try:
            self.server.stop(full_cleanup=True)
        except Exception as e:
            logger.warning("Server stop error: %s", e)


# ----------------------------------------------------------------------
# Banner
# ----------------------------------------------------------------------
def print_banner() -> None:
    if CONFIG.backend_auth_header and CONFIG.backend_key:
        auth_display = (
            f"{CONFIG.backend_auth_header}: "
            f"{CONFIG.backend_auth_scheme + ' ' if CONFIG.backend_auth_scheme else ''}"
            f"<redacted, {len(CONFIG.backend_key)} chars>")
    else:
        auth_display = "(disabled)"

    extra_display = (", ".join(CONFIG.backend_extra_headers.keys())
                     if CONFIG.backend_extra_headers else "(none)")

    # Build a compact, human-readable view of the capability matrix:
    # group supported APIs and unsupported APIs on two lines.
    supported = [k for k, v in API_CAPABILITIES.items() if v == 1]
    unsupported = [k for k, v in API_CAPABILITIES.items() if v == 0]

    lines = [
        "=" * 70,
        " LINGOFUSE LLM PROXY",
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
        f"  Max history per session : {CONFIG.max_history}",
        f"  Max sessions            : {CONFIG.max_sessions}",
        f"  Session idle timeout(s) : {CONFIG.session_timeout}",
        f"  set_system_message      : unsupported (llm_service-only)",
        f"  Log level               : {CONFIG.log_level}",
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

    The usage line and the examples section of `--help` adapt to the
    current packaging: when running from source they show
    "python llm_proxy.py ...", when running as a frozen exe they show
    "llm_proxy.exe ...".
    """
    invocation = get_example_invocation()

    # Build a compact capability listing for the epilog. This lets users
    # read the `--help` output to see which APIs this server supports
    # without having to start it and call get_api_capabilities.
    supported = [k for k, v in API_CAPABILITIES.items() if v == 1]
    unsupported = [k for k, v in API_CAPABILITIES.items() if v == 0]
    cap_lines = (
        f"  Supported APIs   : {', '.join(supported)}\n"
        f"  Unsupported APIs : {', '.join(unsupported) or '(none)'}\n"
        "    (call get_api_capabilities at runtime for the canonical map)\n"
    )

    epilog = (
        "Examples:\n"
        f"  {invocation}\n"
        f"  {invocation} --backend-url http://127.0.0.1:12345/v1\n"
        f"  {invocation} --backend-model qwen2.5-7b-instruct\n"
        f"  {invocation} --backend-key-file ./api_key.txt\n"
        f"  {invocation} --backend-auth-header api-key "
        f"--backend-auth-scheme \"\"\n"
        f"  {invocation} --backend-extra-headers "
        f"\"{{\\\"HTTP-Referer\\\": \\\"https://example.com\\\"}}\"\n"
        f"  {invocation} --log-level DEBUG\n"
        "\n"
        "Relationship with llm_service.py:\n"
        "  Both servers expose the SAME Call API surface except for\n"
        "  set_system_message, which is llm_service-only. Because the\n"
        "  default endpoint (ipc:llm_service) and app name (LLM_Service)\n"
        "  are identical, ONLY ONE of the two may run at any given time.\n"
        "\n"
        "API capability advertisement:\n"
        f"{cap_lines}"
        "\n"
        "Environment variables (read once at startup):\n"
        "  LLM_PROXY_ENDPOINT              - endpoint (default: ipc:llm_service)\n"
        "  LLM_PROXY_APP_NAME              - app name (default: LLM_Service)\n"
        "  LLM_PROXY_NOTIFY_API            - notify API name (default: llm_stream)\n"
        "  LLM_PROXY_BACKEND_URL           - backend base URL\n"
        "  LLM_PROXY_BACKEND_MODEL         - backend model id\n"
        "  LLM_PROXY_BACKEND_KEY           - backend API key\n"
        "  LLM_PROXY_BACKEND_KEY_FILE      - file containing the API key\n"
        "  LLM_PROXY_BACKEND_AUTH_HEADER   - auth header name\n"
        "  LLM_PROXY_BACKEND_AUTH_SCHEME   - auth scheme prefix\n"
        "  LLM_PROXY_BACKEND_EXTRA_HEADERS - extra headers as JSON\n"
        "  LLM_PROXY_BACKEND_TIMEOUT       - HTTP read timeout (seconds)\n"
        "  LLM_PROXY_MAX_HISTORY           - max messages per session\n"
        "  LLM_PROXY_MAX_SESSIONS          - max concurrent sessions\n"
        "  LLM_PROXY_SESSION_TIMEOUT       - idle timeout (seconds)\n"
        "  LLM_PROXY_LOG_LEVEL             - DEBUG/INFO/WARNING/ERROR\n"
    )

    parser = argparse.ArgumentParser(
        prog=get_invocation_name(),
        description=(
            "LingoFuse LLM Proxy.\n"
            "\n"
            "Streaming to the backend uses http.client (not requests) to\n"
            "avoid the socket-level buffering that requests/urllib3 apply\n"
            "to SSE responses.\n"
            "\n"
            "Both reasoning_content and content deltas are forwarded to\n"
            "the LingoFuse client as 'think' and 'chunk' events without\n"
            "any proxy-side policy. Whether a thinking chain appears at\n"
            "all is determined by the backend and its model.\n"
            "\n"
            "set_system_message is NOT supported by this proxy. To use a\n"
            "different system message, close the current session and\n"
            "create a new one with the desired system_message."
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

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
    parser.add_argument(
        "--max-history", type=int,
        default=int(os.environ.get("LLM_PROXY_MAX_HISTORY",
                                   DEFAULT_MAX_HISTORY)),
        metavar="N",
        help="Max (user, assistant) messages retained per session. "
             "Default: 512")
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
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LLM_PROXY_LOG_LEVEL",
                               DEFAULT_LOG_LEVEL).upper(),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity. Default: INFO")

    return parser.parse_args()


def _init_global_config(args: argparse.Namespace) -> None:
    CONFIG.endpoint = args.endpoint
    CONFIG.app_name = args.app_name
    CONFIG.notify_api = args.notify_api
    CONFIG.backend_url = args.backend_url.rstrip("/")
    CONFIG.backend_model = args.backend_model
    CONFIG.backend_key = args.backend_key
    CONFIG.backend_key_file = args.backend_key_file
    CONFIG.backend_auth_header = args.backend_auth_header
    CONFIG.backend_auth_scheme = args.backend_auth_scheme
    CONFIG.backend_timeout = args.backend_timeout
    CONFIG.max_history = args.max_history
    CONFIG.max_sessions = args.max_sessions
    CONFIG.session_timeout = args.session_timeout
    CONFIG.log_level = args.log_level

    try:
        CONFIG.backend_extra_headers = _parse_extra_headers(
            args.backend_extra_headers)
    except ValueError as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        sys.exit(1)

    if CONFIG.backend_key_file:
        try:
            CONFIG.backend_key = _load_key_from_file(CONFIG.backend_key_file)
        except ValueError as e:
            print(f"[FATAL] {e}", file=sys.stderr)
            sys.exit(1)

    logging.getLogger().setLevel(
        getattr(logging, CONFIG.log_level, logging.INFO))


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    _init_global_config(args)

    print_banner()

    service = LLMProxyService()
    atexit.register(service.stop)
    _install_signal_handlers()

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
        service.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())