#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LingoFuse LLM Service - Persistent multi-session streaming server (v3.2).

Architecture
------------
- All inference requests are serialized through a single worker thread.
  This is REQUIRED because llama.cpp contexts are NOT thread-safe.
- Sessions are PERSISTENT: a session survives across multiple
  `generate` calls and accumulates a full message history. Clients
  own their session IDs and are responsible for calling
  `close_session` when finished.
- A session has a stable `client_name` (fixed at creation time) that
  receives all streaming messages for that session.
- A watchdog thread reclaims sessions that are BOTH idle for longer
  than `--session-timeout` AND whose client application is no longer
  reachable on the LingoFuse network. The two-condition check avoids
  discarding a session whose client is merely temporarily disconnected
  but still expected to come back; only sessions that are truly
  abandoned are reclaimed. See `_watchdog_loop` for details.
- Streaming output uses a STRUCTURED JSON envelope with a `type` field:
      {"type": "chunk",   "session_id": "...", "text": "..."}
      {"type": "think",   "session_id": "...", "text": "..."}
      {"type": "finish",  "session_id": "...", "reason": "stop"}
      {"type": "error",   "session_id": "...", "message": "..."}
      {"type": "closed",  "session_id": "...", "reason": "client|timeout|timeout+offline|shutdown|ephemeral|error"}

Global Configuration
--------------------
At startup the service reads environment variables and command-line
arguments ONCE, merges them with the built-in defaults, and stores the
result in a process-wide `CONFIG` object. No runtime code ever re-reads
`os.environ` or `sys.argv` after that point.

Context Window
--------------
`--context-size 0` (the default) instructs the backend to use the
model's maximum supported context. The actual value chosen is reported
in the startup banner.

Chat Template
-------------
Exactly ONE chat template file is used.

Lookup order:
  1. If --chat-template / LLM_CHAT_TEMPLATE is set, that exact path is
     used. A missing file is a hard error.
  2. Otherwise the service searches for `chat_template.jinja` in:
        a) the script directory,
        b) the script's parent directory,
        c) the current working directory.
     The first existing file wins.
  3. If nothing is found, the model's built-in template is used.

The template is rendered with the following variables in scope:
    messages, add_generation_prompt, bos_token, eos_token,
    enable_thinking, truncate_history_thinking, reasoning_budget_message

`enable_thinking` is toggled per-request via `options.thinking`.
`reasoning_budget_message` is a plain string inserted by the template at
the start of the thinking section.

Exposed Call APIs
-----------------
  generate(content, prompt?, client_name?, session_id?, options?)
      -> {code, session_id, task_id, mode}
      mode = "new" | "continue" | "ephemeral"

  create_session(client_name, system_message?, options?)
      -> {code, session_id}

  close_session(session_id, cancel_running?)
      -> {code, status}

  cancel_session(session_id)
      -> {code, status}   # cancels the current generation, keeps the session

  list_sessions(client_name?)
      -> {code, sessions: [...]}

  set_system_message(content)
      -> {code, status}   # updates the global default for NEW sessions

  get_api_capabilities()
      -> {code, server_kind, capabilities: {"<api>": 0|1, ...}}

  health()
      -> {code, status, server_kind, api_capabilities, ...}

Relationship with llm_proxy.py
------------------------------
Siblings with identical Call API surface EXCEPT set_system_message:

  * llm_service.py (this file, server_kind="service")
        Owns an in-process message history and a live llama.cpp
        context. set_system_message updates the global default
        system message used for NEW sessions.

  * llm_proxy.py   (server_kind="proxy")
        Stateless forwarder to an OpenAI-compatible backend. Cannot
        support set_system_message because each session's system
        message is fixed at creation time.

Both server kinds share the SAME capability dictionary keys, differing
only in the value of set_system_message (1 here, 0 in the proxy). Both
expose the SAME default endpoint (ipc:llm_service) and app name
(LLM_Service), so ONLY ONE of the two may run at any given time.

Clients should call `get_api_capabilities` (or read `health`) to
discover which APIs the running server supports, instead of
hard-coding server-kind-specific behavior. A value of 1 means
supported, 0 means not supported. Missing entries should be treated as
unsupported.

Dependencies
------------
  Requires llama-cpp-python (preferred) or transformers + torch.
  `jinja2` is needed only when a custom chat template file is supplied.
  The LingoFuse dynamic library must be on the system PATH.
"""

import os
import sys
import json
import uuid
import queue
import time
import atexit
import signal
import argparse
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple

# Allow running from the repository root without installing the package.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, ".."))

from lingofuse import Server, App, set_option, check_app
from lingofuse.core import DataHandle
from lingofuse._lf_native import (
    LF_Sequenced_Notify,
    LF_FreeData,
    LF_CheckApp,
    LF_GetStatusCount,
    LF_GetStatus,
)


# ----------------------------------------------------------------------
# Frozen-executable detection and help-text invocation helpers
#
# The service can be launched in two ways:
#   1. From source:    python llm_service.py [OPTIONS]
#   2. As a frozen exe: llm_service.exe [OPTIONS]
#
# The `--help` output adapts its usage line and examples accordingly so
# the user always sees the correct command for the current packaging.
# ----------------------------------------------------------------------
def is_frozen_exe() -> bool:
    """
    Return True if this process is running from a frozen executable.

    Detects PyInstaller (one-file or one-dir) and Nuitka by checking
    both `sys.frozen` and `sys._MEIPASS`. This mirrors the detection
    used by llm_proxy.py, llm_test.py, mcp_server.py and mcp_proxy.py
    in the same project.
    """
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')


def get_invocation_name() -> str:
    """
    Return the program name shown at the top of `--help` (the `prog=`
    value).

    - Frozen exe: the exe filename, e.g. "llm_service_cpu.exe".
    - Script:     the script filename, e.g. "llm_service.py".
    """
    if is_frozen_exe():
        return os.path.basename(sys.executable)
    return os.path.basename(os.path.abspath(__file__))


def get_example_invocation() -> str:
    """
    Return the full command prefix used in the `--help` examples.

    - Frozen exe: "llm_service_cpu.exe"
    - Script:     "python llm_service.py"
    """
    if is_frozen_exe():
        return os.path.basename(sys.executable)
    return f"{os.path.basename(sys.executable)} {os.path.basename(os.path.abspath(__file__))}"


# ----------------------------------------------------------------------
# Backend detection
# ----------------------------------------------------------------------
try:
    import llama_cpp
    LLM_BACKEND = "llama_cpp"
except ImportError:
    LLM_BACKEND = None
    print("[WARN] llama-cpp-python not installed, trying transformers...",
          file=sys.stderr)

if LLM_BACKEND is None:
    try:
        import transformers  # noqa: F401
        import torch          # noqa: F401
        LLM_BACKEND = "transformers"
    except ImportError:
        LLM_BACKEND = None
        print("[ERROR] No LLM backend available. "
              "Install llama-cpp-python or transformers.",
              file=sys.stderr)
        sys.exit(1)


# ----------------------------------------------------------------------
# Built-in defaults
# ----------------------------------------------------------------------
DEFAULT_MODEL_PATH = "./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf"

# 0 = use the model's maximum supported context length.
DEFAULT_CONTEXT_SIZE = 0

DEFAULT_MAX_TOKENS = 4096
DEFAULT_THREADS = 6
DEFAULT_GPU_LAYERS = -1
DEFAULT_SYSTEM_MESSAGE = (
    "Before answering, briefly list your reasoning steps using numbered bullets. "
    "Then give the final answer. Do not use Markdown."
)
DEFAULT_ENDPOINT = "ipc:llm_service"
DEFAULT_APP_NAME = "LLM_Service"
DEFAULT_NOTIFY_API = "llm_stream"
DEFAULT_TIMEOUT_MS = 5000
DEFAULT_SESSION_TIMEOUT = 600          # seconds: idle timeout for sessions
DEFAULT_LOG_LEVEL = 1                  # 0=quiet, 1=normal, 2=debug
DEFAULT_QUEUE_MAX_SIZE = 256           # max queued generation tasks
DEFAULT_MAX_SESSIONS = 1024            # max concurrent sessions
MAX_CLIENT_NAME_LEN = 512              # sanity bound for client_name
MAX_HISTORY_MESSAGES = 512             # cap on messages stored per session

DEFAULT_REASONING_BUDGET_MESSAGE = "好的，我用简体中文来思考。禁止使用英文。\n"

DEFAULT_CHAT_TEMPLATE_BASENAME = "chat_template.jinja"
DEFAULT_CHAT_TEMPLATE_SEARCH_DIRS: Tuple[str, ...] = (
    _SCRIPT_DIR,
    os.path.abspath(os.path.join(_SCRIPT_DIR, "..")),
    os.getcwd(),
)

THINK_OPEN_MARKER = "<think>"
THINK_CLOSE_MARKER = "</think>"

# Reason string reported on the "closed" notification when the watchdog
# reclaims a session because it has been idle past the timeout AND its
# client application is no longer reachable.
SESSION_CLOSE_REASON_TIMEOUT_OFFLINE = "timeout+offline"


# ----------------------------------------------------------------------
# API capability matrix
#
# Keys are the full set of APIs that an LLM server in this ecosystem
# may expose. Values are integers:
#
#     1  = supported by THIS server kind (llm_service)
#     0  = NOT supported by this server kind (belongs to llm_proxy)
#
# The key set is IDENTICAL to the one published by llm_proxy.py. The
# two server kinds differ only in the value of set_system_message:
#   * llm_service (this file)  -> 1
#   * llm_proxy                -> 0
#
# Clients should call the `get_api_capabilities` Call API (or read the
# `api_capabilities` field of `health`) to discover this dictionary at
# runtime, instead of hard-coding it.
#
# Rationale for each 0/1 value:
#   * generate, create_session, close_session, cancel_session,
#     list_sessions, health
#       -> intrinsic to this server kind, supported.
#   * set_system_message
#       -> this file owns an in-process message history and a live
#          llama.cpp context, so updating the global default system
#          message is meaningful and supported. The proxy cannot
#          support this because it is a stateless forwarder.
#   * llm_stream
#       -> Notify API used for streaming chunks; identical semantics in
#          both server kinds.
# ----------------------------------------------------------------------
API_CAPABILITIES: Dict[str, int] = {
    # ---- Call APIs (llm_service v3.0 exposed set) ----
    "generate":           1,   # fully implemented in-process
    "create_session":     1,   # session registry is owned by this service
    "close_session":      1,   # session registry is owned by this service
    "cancel_session":     1,   # cancels the in-flight generation task
    "list_sessions":      1,   # session registry is owned by this service
    "set_system_message": 1,   # global default for NEW sessions
    "health":             1,   # this service reports its own status

    # ---- Notify API (streaming chunks back to the client) ----
    "llm_stream":         1,   # same semantics as in llm_proxy
}

# Identifies which server kind is answering. Included in the
# `get_api_capabilities` and `health` responses so that clients can
# branch on it if they need to.
SERVER_KIND = "service"


# ----------------------------------------------------------------------
# Global configuration
# ----------------------------------------------------------------------
class ServiceConfig:
    """
    Process-wide configuration. Populated exactly once at startup by
    `_init_global_config()`. All runtime code reads from this object.
    """

    def __init__(self) -> None:
        # ---- Model / inference ----
        self.model_path: str = DEFAULT_MODEL_PATH
        self.context_size: int = DEFAULT_CONTEXT_SIZE
        self.context_size_actual: int = 0
        self.max_tokens: int = DEFAULT_MAX_TOKENS
        self.threads: int = DEFAULT_THREADS
        self.gpu_layers: int = DEFAULT_GPU_LAYERS
        self.system_message: str = DEFAULT_SYSTEM_MESSAGE

        # ---- LingoFuse ----
        self.endpoint: str = DEFAULT_ENDPOINT
        self.app_name: str = DEFAULT_APP_NAME
        self.notify_api: str = DEFAULT_NOTIFY_API
        self.timeout_ms: int = DEFAULT_TIMEOUT_MS

        # ---- Service behaviour ----
        self.session_timeout: int = DEFAULT_SESSION_TIMEOUT
        self.queue_max_size: int = DEFAULT_QUEUE_MAX_SIZE
        self.max_sessions: int = DEFAULT_MAX_SESSIONS

        # ---- Chat template ----
        self.chat_template_path: Optional[str] = None
        self.chat_template_resolved_path: Optional[str] = None
        self.default_template: Optional[str] = None

        # ---- Reasoning ----
        self.reasoning_budget_message: str = DEFAULT_REASONING_BUDGET_MESSAGE

        # ---- Logging ----
        self.log_level: int = DEFAULT_LOG_LEVEL

    @property
    def enable_chunk_logging(self) -> bool:
        return self.log_level >= 1

    @property
    def enable_warning_logging(self) -> bool:
        return self.log_level >= 2


CONFIG = ServiceConfig()


# ----------------------------------------------------------------------
# Argument parsing
# ----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    The usage line and the examples section of `--help` adapt to the
    current packaging: when running from source they show
    "python llm_service.py ...", when running as a frozen exe they show
    "llm_service.exe ...".
    """
    invocation = get_example_invocation()

    # Build a compact capability listing for the epilog. This lets
    # users read the `--help` output to see which APIs this server
    # supports without having to start it and call
    # get_api_capabilities.
    supported = [k for k, v in API_CAPABILITIES.items() if v == 1]
    unsupported = [k for k, v in API_CAPABILITIES.items() if v == 0]
    cap_lines = (
        f"  Supported APIs   : {', '.join(supported)}\n"
        f"  Unsupported APIs : {', '.join(unsupported) or '(none)'}\n"
        "    (call get_api_capabilities at runtime for the canonical map)\n"
    )

    epilog = (
        "All options can also be set via the corresponding environment "
        "variables. The service reads environment variables and "
        "command-line arguments ONCE at startup and stores everything "
        "in a process-wide configuration object; runtime code never "
        "re-reads os.environ or sys.argv.\n"
        "\n"
        "Examples:\n"
        f"  {invocation}\n"
        f"  {invocation} --model-path ./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf\n"
        f"  {invocation} --context-size 8192 --max-tokens 2048\n"
        f"  {invocation} --gpu-layers 0 --threads 8 --quiet\n"
        f"  {invocation} --endpoint ipc:llm_service --app-name LLM_Service\n"
        f"  {invocation} --chat-template ./chat_template.jinja --debug\n"
        f"  {invocation} --session-timeout 1800 --max-sessions 64\n"
        "\n"
        "Relationship with llm_proxy.py:\n"
        "  Both server kinds expose the SAME Call API surface except for\n"
        "  set_system_message. Because the default endpoint\n"
        "  (ipc:llm_service) and app name (LLM_Service) are identical,\n"
        "  ONLY ONE of the two may run at any given time.\n"
        "    llm_service (this file) - supports set_system_message\n"
        "    llm_proxy               - does NOT support set_system_message\n"
        "\n"
        "Session watchdog:\n"
        "  A session is reclaimed only when BOTH conditions hold:\n"
        "    (a) it has been idle longer than --session-timeout, AND\n"
        "    (b) its client application is no longer reachable.\n"
        "  Sessions whose client is still online are kept even after\n"
        "  the idle timeout, so a returning client can resume.\n"
        "\n"
        "API capability advertisement:\n"
        f"{cap_lines}"
        "\n"
        "Environment variables (read once at startup):\n"
        "  LLM_MODEL_PATH              - GGUF model path\n"
        "  LLM_CONTEXT_SIZE            - context window size (0 = auto)\n"
        "  LLM_MAX_TOKENS              - default max tokens\n"
        "  LLM_THREADS                 - CPU threads\n"
        "  LLM_GPU_LAYERS              - GPU layers (-1=all, 0=CPU)\n"
        "  LLM_SYSTEM_MESSAGE          - default system message\n"
        "  LINGOFUSE_ENDPOINT          - LingoFuse endpoint\n"
        "  LINGOFUSE_APP_NAME          - service app name\n"
        "  LINGOFUSE_NOTIFY_API        - notify API name\n"
        "  LINGOFUSE_TIMEOUT_MS        - Call timeout (ms)\n"
        "  LLM_SESSION_TIMEOUT         - idle timeout (s)\n"
        "  LLM_QUEUE_MAX_SIZE          - max queued tasks\n"
        "  LLM_MAX_SESSIONS            - max concurrent sessions\n"
        "  LLM_CHAT_TEMPLATE           - explicit chat template path\n"
        "  LLM_REASONING_BUDGET_MESSAGE- reasoning guidance text\n"
        "  LLM_LOG_LEVEL               - 0=quiet, 1=normal, 2=debug\n"
        "  LLM_DEBUG / LLM_QUIET       - shortcuts for the log level\n"
    )

    parser = argparse.ArgumentParser(
        prog=get_invocation_name(),
        description=(
            "LingoFuse LLM Service - persistent multi-session streaming "
            "(v3.2)"
        ),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ---- Model ----
    parser.add_argument(
        "--model-path",
        default=os.environ.get("LLM_MODEL_PATH", DEFAULT_MODEL_PATH),
        help=f"Path to the GGUF model file (or HF model directory). "
             f"Default: {DEFAULT_MODEL_PATH}",
    )
    parser.add_argument(
        "--context-size", type=int,
        default=int(os.environ.get("LLM_CONTEXT_SIZE", DEFAULT_CONTEXT_SIZE)),
        help=(
            "Context window size in tokens. "
            "Default: 0, meaning 'use the model's maximum supported context "
            "size', determined automatically at load time."
        ),
    )
    parser.add_argument(
        "--max-tokens", type=int,
        default=int(os.environ.get("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
        help=f"Default maximum tokens to generate per request. "
             f"Default: {DEFAULT_MAX_TOKENS}",
    )
    parser.add_argument(
        "--threads", type=int,
        default=int(os.environ.get("LLM_THREADS", DEFAULT_THREADS)),
        help=f"CPU threads for llama.cpp. Default: {DEFAULT_THREADS}",
    )
    parser.add_argument(
        "--gpu-layers", type=int,
        default=int(os.environ.get("LLM_GPU_LAYERS", DEFAULT_GPU_LAYERS)),
        help=f"GPU layers to offload (-1=all, 0=CPU). Default: {DEFAULT_GPU_LAYERS}",
    )
    parser.add_argument(
        "--system-message",
        default=os.environ.get("LLM_SYSTEM_MESSAGE", DEFAULT_SYSTEM_MESSAGE),
        help="Default system message applied to NEW sessions. "
             "May also be changed at runtime via set_system_message.",
    )

    # ---- LingoFuse ----
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("LINGOFUSE_ENDPOINT", DEFAULT_ENDPOINT),
        help=f"LingoFuse endpoint (IPC or TCP). Default: {DEFAULT_ENDPOINT}",
    )
    parser.add_argument(
        "--app-name",
        default=os.environ.get("LINGOFUSE_APP_NAME", DEFAULT_APP_NAME),
        help=f"Application name to register. Default: {DEFAULT_APP_NAME}",
    )
    parser.add_argument(
        "--notify-api",
        default=os.environ.get("LINGOFUSE_NOTIFY_API", DEFAULT_NOTIFY_API),
        help=f"Notify API name for streaming chunks. Default: {DEFAULT_NOTIFY_API}",
    )
    parser.add_argument(
        "--timeout", type=int,
        default=int(os.environ.get("LINGOFUSE_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)),
        help=f"Call timeout in milliseconds. Default: {DEFAULT_TIMEOUT_MS}",
    )

    # ---- Service behaviour ----
    parser.add_argument(
        "--session-timeout", type=int,
        default=int(os.environ.get("LLM_SESSION_TIMEOUT", DEFAULT_SESSION_TIMEOUT)),
        help=f"Idle timeout (seconds) for sessions. Sessions that have not "
             f"been active for this long AND whose client application is "
             f"offline are closed by the watchdog. Default: {DEFAULT_SESSION_TIMEOUT}",
    )
    parser.add_argument(
        "--queue-max-size", type=int,
        default=int(os.environ.get("LLM_QUEUE_MAX_SIZE", DEFAULT_QUEUE_MAX_SIZE)),
        help=f"Maximum queued generation tasks before rejecting new requests. "
             f"Default: {DEFAULT_QUEUE_MAX_SIZE}",
    )
    parser.add_argument(
        "--max-sessions", type=int,
        default=int(os.environ.get("LLM_MAX_SESSIONS", DEFAULT_MAX_SESSIONS)),
        help=f"Maximum number of concurrent sessions. New sessions are "
             f"rejected when the limit is reached. Default: {DEFAULT_MAX_SESSIONS}",
    )

    # ---- Chat template & reasoning ----
    parser.add_argument(
        "--chat-template",
        default=os.environ.get("LLM_CHAT_TEMPLATE", None),
        help=(
            "Path to a Jinja2 chat template file. When omitted, the "
            "service searches for '" + DEFAULT_CHAT_TEMPLATE_BASENAME + "' "
            "in the script directory, its parent directory, and the "
            "current working directory (in that order). If no file is "
            "found, the model's built-in template is used. "
            "Environment variable: LLM_CHAT_TEMPLATE."
        ),
    )
    parser.add_argument(
        "--reasoning-budget-message",
        default=os.environ.get(
            "LLM_REASONING_BUDGET_MESSAGE", DEFAULT_REASONING_BUDGET_MESSAGE
        ),
        help=(
            "Text prepended by the chat template at the start of the "
            "thinking section. Used to steer the model's reasoning. "
            "Template accesses it via `reasoning_budget_message`. "
            "Environment variable: LLM_REASONING_BUDGET_MESSAGE."
        ),
    )

    # ---- Logging ----
    parser.add_argument(
        "--log-level", type=int, choices=[0, 1, 2],
        default=int(os.environ.get("LLM_LOG_LEVEL", DEFAULT_LOG_LEVEL)),
        help="Log verbosity: 0=quiet, 1=normal, 2=debug. "
             f"Default: {DEFAULT_LOG_LEVEL}",
    )
    parser.add_argument(
        "--debug", action="store_true",
        default=os.environ.get("LLM_DEBUG", "0").lower() in ("1", "true", "yes"),
        help="Shortcut for --log-level 2.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        default=os.environ.get("LLM_QUIET", "0").lower() in ("1", "true", "yes"),
        help="Shortcut for --log-level 0.",
    )

    return parser.parse_args()


def _init_global_config(args: argparse.Namespace) -> None:
    CONFIG.model_path = args.model_path
    CONFIG.context_size = args.context_size
    CONFIG.max_tokens = args.max_tokens
    CONFIG.threads = args.threads
    CONFIG.gpu_layers = args.gpu_layers
    CONFIG.system_message = args.system_message

    CONFIG.endpoint = args.endpoint
    CONFIG.app_name = args.app_name
    CONFIG.notify_api = args.notify_api
    CONFIG.timeout_ms = args.timeout

    CONFIG.session_timeout = args.session_timeout
    CONFIG.queue_max_size = args.queue_max_size
    CONFIG.max_sessions = args.max_sessions

    CONFIG.chat_template_path = args.chat_template
    CONFIG.reasoning_budget_message = args.reasoning_budget_message

    if args.debug:
        CONFIG.log_level = 2
    elif args.quiet:
        CONFIG.log_level = 0
    else:
        CONFIG.log_level = args.log_level


# ----------------------------------------------------------------------
# Chat template loading
# ----------------------------------------------------------------------
def load_chat_template(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[ERROR] Failed to read chat template {path}: {e}",
              file=sys.stderr)
        sys.exit(1)


def _find_default_chat_template() -> Optional[str]:
    seen = set()
    for d in DEFAULT_CHAT_TEMPLATE_SEARCH_DIRS:
        d = os.path.abspath(d)
        if d in seen:
            continue
        seen.add(d)
        candidate = os.path.join(d, DEFAULT_CHAT_TEMPLATE_BASENAME)
        if os.path.isfile(candidate):
            return candidate
    return None


def _resolve_and_load_template() -> None:
    if CONFIG.chat_template_path:
        resolved = os.path.abspath(CONFIG.chat_template_path)
        if not os.path.isfile(resolved):
            print(f"[ERROR] Chat template not found: {resolved}",
                  file=sys.stderr)
            sys.exit(1)
        CONFIG.chat_template_resolved_path = resolved
        CONFIG.default_template = load_chat_template(resolved)
        print(f"[LLM] Loaded chat template (explicit): {resolved} "
              f"({len(CONFIG.default_template)} bytes)")
        return

    found = _find_default_chat_template()
    if found:
        CONFIG.chat_template_resolved_path = found
        CONFIG.default_template = load_chat_template(found)
        print(f"[LLM] Loaded chat template (auto-discovered): {found} "
              f"({len(CONFIG.default_template)} bytes)")
    else:
        CONFIG.chat_template_resolved_path = None
        CONFIG.default_template = None
        searched = ", ".join(
            os.path.abspath(d) for d in DEFAULT_CHAT_TEMPLATE_SEARCH_DIRS
        )
        print(f"[LLM] No '{DEFAULT_CHAT_TEMPLATE_BASENAME}' found in: "
              f"{searched}")
        print("[LLM] Falling back to model built-in template")


# ----------------------------------------------------------------------
# Token estimation
# ----------------------------------------------------------------------
def estimate_tokens(llm, tokenizer, text: str) -> Optional[int]:
    if text is None:
        return 0
    if LLM_BACKEND == "llama_cpp" and hasattr(llm, "tokenize"):
        try:
            return len(llm.tokenize(text.encode("utf-8"), add_bos=False, special=True))
        except Exception:
            return None
    if LLM_BACKEND == "transformers" and tokenizer is not None:
        try:
            return len(tokenizer.encode(text, add_special_tokens=False))
        except Exception:
            return None
    return None


# ----------------------------------------------------------------------
# LLM loader
# ----------------------------------------------------------------------
def load_llm(model_path: str, context_size: int, threads: int, gpu_layers: int):
    print("[LLM] Loading model... (this may take a while)")
    print(f"[LLM] Model path: {model_path}")
    ctx_display = "auto (model maximum)" if context_size == 0 else context_size
    print(f"[LLM] Context size: {ctx_display}, threads: {threads}, GPU layers: {gpu_layers}")

    if LLM_BACKEND == "llama_cpp":
        print("[LLM] Using backend: llama-cpp-python")
        model = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=context_size,
            n_threads=threads,
            n_gpu_layers=gpu_layers,
            verbose=False,
        )
        actual_ctx = model.n_ctx()

        try:
            metadata = model.metadata
            if metadata:
                print("[LLM] Model metadata:")
                for k, v in metadata.items():
                    if k == "tokenizer.chat_template":
                        print(f"    {k}: <{len(str(v))} bytes>")
                        continue
                    print(f"    {k}: {v}")
        except AttributeError:
            pass

        return model, None, actual_ctx

    if LLM_BACKEND == "transformers":
        print("[LLM] Using backend: transformers")
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype="auto",
            device_map="auto",
            trust_remote_code=True,
        )
        actual_ctx = getattr(model.config, "max_position_embeddings", 0)
        print(f"[LLM] Model loaded with device map: "
              f"{getattr(model, 'hf_device_map', 'n/a')}")
        return model, tokenizer, actual_ctx

    raise RuntimeError("No LLM backend available")


# ----------------------------------------------------------------------
# Thinking-mode parser
# ----------------------------------------------------------------------
class ThinkingParser:
    """
    Splits a token stream into `think` and `chunk` segments based on
    `<think>` ... `</think>`. Handles markers that straddle chunk
    boundaries by buffering a small tail.

    When `initial_in_thinking` is True, the generation stream is assumed
    to start inside a thinking block (the chat template already opened
    `<think>` in the prompt).
    """

    def __init__(self, initial_in_thinking: bool = False) -> None:
        self.in_thinking = initial_in_thinking
        self.buffer = ""

    @staticmethod
    def _safe_emit_len(buf: str, marker: str) -> int:
        max_check = min(len(marker) - 1, len(buf))
        for i in range(max_check, 0, -1):
            if buf.endswith(marker[:i]):
                return len(buf) - i
        return len(buf)

    def feed(self, text: str) -> List[Tuple[str, str]]:
        self.buffer += text
        out: List[Tuple[str, str]] = []

        while True:
            if self.in_thinking:
                idx = self.buffer.find(THINK_CLOSE_MARKER)
                if idx >= 0:
                    if idx > 0:
                        out.append(("think", self.buffer[:idx]))
                    self.buffer = self.buffer[idx + len(THINK_CLOSE_MARKER):]
                    self.in_thinking = False
                    continue
                emit = self._safe_emit_len(self.buffer, THINK_CLOSE_MARKER)
                if emit > 0:
                    out.append(("think", self.buffer[:emit]))
                    self.buffer = self.buffer[emit:]
                break
            else:
                idx = self.buffer.find(THINK_OPEN_MARKER)
                if idx >= 0:
                    if idx > 0:
                        out.append(("chunk", self.buffer[:idx]))
                    self.buffer = self.buffer[idx + len(THINK_OPEN_MARKER):]
                    self.in_thinking = True
                    continue
                emit = self._safe_emit_len(self.buffer, THINK_OPEN_MARKER)
                if emit > 0:
                    out.append(("chunk", self.buffer[:emit]))
                    self.buffer = self.buffer[emit:]
                break
        return out

    def flush(self) -> List[Tuple[str, str]]:
        if not self.buffer:
            return []
        result = [("think" if self.in_thinking else "chunk", self.buffer)]
        self.buffer = ""
        return result


# ----------------------------------------------------------------------
# Session and GenerationTask
# ----------------------------------------------------------------------
class Session:
    """
    A persistent conversation session. Holds:
      - a fixed `client_name` (destination for streaming messages)
      - a fixed `system_message` (snapshotted at creation)
      - a message history that grows with each successful generation
      - status flags used by the worker and the watchdog
    """

    def __init__(
        self,
        session_id: str,
        client_name: str,
        system_message: str,
    ) -> None:
        self.session_id = session_id
        self.client_name = client_name
        self.system_message = system_message

        # History excludes the system message; it is re-prepended at
        # render time so that the current global system message is not
        # confused with the session's own snapshot.
        self.messages: List[Dict[str, Any]] = []

        self.created_at = time.monotonic()
        self.last_active_at = self.created_at
        self.status = "idle"      # idle | running | closing
        self.current_cancel_event: Optional[threading.Event] = None

        # Guards session-local state mutations.
        self.lock = threading.Lock()

    def to_summary(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "client_name": self.client_name,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "status": self.status,
            "message_count": len(self.messages),
        }


class GenerationTask:
    """
    A single generation request inside a Session. Multiple tasks may be
    queued for the same session; the worker processes them in FIFO order.
    """

    def __init__(
        self,
        task_id: str,
        session: Session,
        content: str,
        prompt: str,
        options: Dict[str, Any],
        ephemeral: bool,
    ) -> None:
        self.task_id = task_id
        self.session = session
        self.content = content
        self.prompt = prompt
        self.options = options
        self.ephemeral = ephemeral
        self.cancel_event = threading.Event()


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
class LLMService:
    """
    Main service class. All inference is funneled through a single
    worker thread because llama.cpp is not thread-safe.

    Runtime configuration is read exclusively from the global CONFIG
    object; this class never inspects environment variables or
    command-line arguments.
    """

    def __init__(self) -> None:
        self.backend = LLM_BACKEND

        # ---- Global default system message (for NEW sessions) ----
        self._system_message = CONFIG.system_message
        self._system_message_lock = threading.Lock()

        # ---- Sessions ----
        self._sessions: Dict[str, Session] = {}
        self._sessions_lock = threading.Lock()

        # ---- Serial inference queue ----
        self._request_queue: "queue.Queue[Optional[GenerationTask]]" = queue.Queue(
            maxsize=CONFIG.queue_max_size
        )
        self._shutdown_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._cleaned_up = False

        # ---- Load model ----
        print("[LLM] Loading LLM...")
        load_start = time.monotonic()
        self.llm, self.tokenizer, actual_ctx = load_llm(
            CONFIG.model_path,
            CONFIG.context_size,
            CONFIG.threads,
            CONFIG.gpu_layers,
        )
        CONFIG.context_size_actual = actual_ctx
        print(f"[LLM] Model loaded in {time.monotonic() - load_start:.2f}s")
        print(f"[LLM] Effective context size: {actual_ctx} tokens")

        # ---- Start background threads ----
        self._start_worker()
        self._start_watchdog()

        # ---- Create server and register APIs ----
        self.server = Server(
            CONFIG.app_name,
            "Local LLM Service with persistent multi-session streaming (v3.2)",
        )
        self._register_apis()
        atexit.register(self.cleanup)

    # ------------------------------------------------------------------
    # Worker / watchdog
    # ------------------------------------------------------------------
    def _start_worker(self) -> None:
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="llm-worker",
            daemon=True,
        )
        self._worker_thread.start()
        print("[Service] Inference worker thread started")

    def _start_watchdog(self) -> None:
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="llm-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()
        print(f"[Service] Watchdog started (session idle timeout: "
              f"{CONFIG.session_timeout}s; sessions are reclaimed only when "
              f"BOTH idle past the timeout AND the client is offline)")

    def _worker_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                task = self._request_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                break
            try:
                self._process_task(task)
            except Exception as e:
                print(f"[Task {task.task_id}] Worker exception: {e}")
                traceback.print_exc()
            finally:
                self._request_queue.task_done()

    def _watchdog_loop(self) -> None:
        """
        Reclaim sessions whose client has gone away AND whose idle timer
        has expired.

        Reclaim policy
        --------------
        A session is closed ONLY when BOTH of the following hold:

          (a) The session has been idle for longer than the configured
              `--session-timeout`, AND
          (b) The client application that owns this session is no
              longer reachable on the LingoFuse network.

        Why the two-condition check
        ---------------------------
        Clients occasionally disconnect and reconnect (laptop sleeps,
        network glitch, client restart). If we reclaimed every session
        the moment its idle timer expired, a client that just paused for
        longer than `session_timeout` would lose its entire conversation
        history. By also requiring the client to be offline, we give the
        client a chance to come back.

        Conversely, a client that is truly gone (process killed, machine
        powered off) will eventually fall out of the LingoFuse
        reachability cache, at which point the idle sessions it owned
        become eligible for reclamation. So the invariant we enforce is:

            "Only sessions that are BOTH idle AND orphaned are freed."

        Reachability check
        ------------------
        `check_app(client_name)` consults the same local cache that every
        other LingoFuse reachability query uses. The cache is updated by
        network broadcasts with a typical propagation delay of about 3
        seconds. The watchdog runs on a 5-second tick, which is slower
        than the cache update, so a client that has just disconnected
        will have been evicted from the cache by the time the next tick
        fires.

        Running sessions are never eligible, regardless of idle time:
        the worker thread holds the session lock while generating, and
        it may be doing so for a long time (e.g. a 30k-token completion).
        We simply skip any session whose status is not "idle".

        Close reason
        ------------
        Sessions reclaimed by this method are closed with reason
        "timeout+offline", which is distinct from "timeout" (a plain
        idle timeout, no longer produced by this version) and from
        "client" (an explicit close_session from the client). The
        distinct reason makes it easy to distinguish the two cases in
        logs or in a UI that inspects the `closed` event.
        """
        while not self._shutdown_event.wait(timeout=5.0):
            now = time.monotonic()
            to_close: List[Session] = []

            with self._sessions_lock:
                for sess in self._sessions.values():
                    # ---- Condition 0: only idle sessions are eligible ----
                    # A running session is mid-generation; leave it alone.
                    if sess.status != "idle":
                        continue

                    # ---- Condition (a): idle timer expired? ----
                    if now - sess.last_active_at <= CONFIG.session_timeout:
                        continue

                    # ---- Condition (b): client application offline? ----
                    # check_app consults the LingoFuse reachability cache.
                    # If the client is still online we keep the session,
                    # so a returning client can continue where it left off.
                    try:
                        still_online = check_app(sess.client_name)
                    except Exception as e:
                        # If the reachability check itself fails, err on
                        # the side of caution: keep the session rather
                        # than potentially reclaiming a live one.
                        print(f"[Watchdog] check_app('{sess.client_name}') "
                              f"raised {e!r}; keeping session "
                              f"{sess.session_id}")
                        continue

                    if still_online:
                        # Client is online but chose not to talk for a
                        # while. Keep the session so it can be resumed.
                        # (Logged only at debug level to avoid noise;
                        # we use enable_warning_logging as a proxy for
                        # verbose mode.)
                        if CONFIG.enable_warning_logging:
                            print(f"[Watchdog] Session {sess.session_id} "
                                  f"idle > {CONFIG.session_timeout}s but "
                                  f"client '{sess.client_name}' is still "
                                  f"online; keeping session")
                        continue

                    # Both conditions hold: idle past the timeout AND
                    # client offline. Eligible for reclamation.
                    to_close.append(sess)

            # Close outside the lock to avoid holding it during the
            # "closed" notification round-trip.
            for sess in to_close:
                idle_for = now - sess.last_active_at
                print(f"[Session {sess.session_id}] Idle for "
                      f"{idle_for:.1f}s (> {CONFIG.session_timeout}s) and "
                      f"client app '{sess.client_name}' is offline; "
                      f"reclaiming session")
                self._close_session_internal(
                    sess, reason=SESSION_CLOSE_REASON_TIMEOUT_OFFLINE
                )

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

        print("[Service] Registered APIs: generate, create_session, "
              "close_session, cancel_session, list_sessions, "
              "set_system_message, get_api_capabilities, health")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _sanitize_options(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Accept only known keys; coerce types; drop everything else."""
        out: Dict[str, Any] = {}

        out["thinking"] = bool(raw.get("thinking", False))
        out["ephemeral"] = bool(raw.get("ephemeral", False))

        for key, cast, lo, hi in (
            ("max_tokens",      int,   1, CONFIG.context_size_actual or (1 << 20)),
            ("temperature",     float, 0.0, 2.0),
            ("top_p",           float, 0.0, 1.0),
            ("top_k",           int,   0, 1000),
            ("repeat_penalty",  float, 0.0, 4.0),
        ):
            if key in raw:
                try:
                    v = cast(raw[key])
                    v = max(lo, min(hi, v))
                    out[key] = v
                except (TypeError, ValueError):
                    pass
        return out

    def _count_sessions(self) -> int:
        with self._sessions_lock:
            return len(self._sessions)

    def _create_session(
        self,
        client_name: str,
        system_message: Optional[str] = None,
    ) -> Session:
        """Create and register a new session. Caller must ensure capacity."""
        if system_message is None:
            with self._system_message_lock:
                system_message = self._system_message
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            client_name=client_name,
            system_message=system_message,
        )
        with self._sessions_lock:
            self._sessions[session_id] = session
        return session

    def _lookup_session(self, session_id: str) -> Optional[Session]:
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def _close_session_internal(self, session: Session, reason: str) -> bool:
        """
        Remove a session from the registry. Any in-flight generation for
        this session is signalled to cancel. A `closed` message is sent
        to the client so it can react accordingly.
        """
        with self._sessions_lock:
            existing = self._sessions.pop(session.session_id, None)
        if existing is None:
            return False
        # Signal cancel to any currently running task.
        with session.lock:
            session.status = "closing"
            if session.current_cancel_event is not None:
                session.current_cancel_event.set()
        # Notify the client.
        self._emit_message_raw(session, {
            "type": "closed",
            "session_id": session.session_id,
            "reason": reason,
        })
        print(f"[Session {session.session_id}] Closed (reason={reason})")
        return True

    # ------------------------------------------------------------------
    # Handlers: generate / create_session / close_session / cancel_session
    # ------------------------------------------------------------------
    def _handle_generate(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"code": -1, "error": "generate expects a JSON object payload"}

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
        ephemeral = bool(options.get("ephemeral", False))

        # ---- Resolve or create session ----
        mode: str
        if session_id:
            session = self._lookup_session(session_id)
            if session is None:
                return {"code": -1,
                        "error": f"Session not found: {session_id}"}
            if session.status == "closing":
                return {"code": -1,
                        "error": f"Session is closing: {session_id}"}
            # Allow client_name to be omitted when continuing a session.
            if client_name and client_name != session.client_name:
                return {"code": -1,
                        "error": "client_name does not match the session owner"}
            mode = "continue"
        else:
            # New session. client_name is required in this branch.
            if not client_name or not isinstance(client_name, str):
                return {"code": -1,
                        "error": "Missing client_name (required for new sessions)"}
            if len(client_name) > MAX_CLIENT_NAME_LEN:
                return {"code": -1,
                        "error": f"client_name exceeds {MAX_CLIENT_NAME_LEN} chars"}
            if self._count_sessions() >= CONFIG.max_sessions:
                return {"code": -1,
                        "error": f"Session limit reached "
                                 f"(max {CONFIG.max_sessions})"}
            session = self._create_session(client_name)
            mode = "ephemeral" if ephemeral else "new"

        # ---- Token budget check (fast; runs on callback thread) ----
        with self._system_message_lock:
            system_snapshot = session.system_message
        error = self._check_token_budget(session, content, prompt, options,
                                         system_snapshot)
        if error is not None:
            # If this was a newly created session and we cannot proceed,
            # roll it back so the client is not left with a dead session.
            if mode in ("new", "ephemeral"):
                self._close_session_internal(session, reason="error")
            return {"code": -1, "error": error}

        # ---- Enqueue task ----
        task_id = str(uuid.uuid4())
        task = GenerationTask(
            task_id=task_id,
            session=session,
            content=content,
            prompt=prompt,
            options=options,
            ephemeral=ephemeral,
        )
        with session.lock:
            session.last_active_at = time.monotonic()
        try:
            self._request_queue.put_nowait(task)
        except queue.Full:
            if mode in ("new", "ephemeral"):
                self._close_session_internal(session, reason="error")
            return {"code": -1, "error": "Server busy: request queue is full"}

        print(f"[Service] Task {task_id} queued (mode={mode}, "
              f"session={session.session_id}, client={session.client_name}, "
              f"thinking={options.get('thinking', False)})")
        return {
            "code": 0,
            "session_id": session.session_id,
            "task_id": task_id,
            "mode": mode,
        }

    def _handle_create_session(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"code": -1, "error": "create_session expects a JSON object"}
        client_name = data.get("client_name")
        if not client_name or not isinstance(client_name, str):
            return {"code": -1, "error": "Missing client_name (string required)"}
        if len(client_name) > MAX_CLIENT_NAME_LEN:
            return {"code": -1,
                    "error": f"client_name exceeds {MAX_CLIENT_NAME_LEN} chars"}
        system_message = data.get("system_message")
        if system_message is not None and not isinstance(system_message, str):
            return {"code": -1, "error": "system_message must be a string"}

        if self._count_sessions() >= CONFIG.max_sessions:
            return {"code": -1,
                    "error": f"Session limit reached (max {CONFIG.max_sessions})"}

        session = self._create_session(client_name, system_message)
        print(f"[Service] Session created: {session.session_id} "
              f"(client={client_name})")
        return {
            "code": 0,
            "session_id": session.session_id,
            "client_name": client_name,
        }

    def _handle_close_session(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {"code": -1, "error": "close_session expects a JSON object"}
        session_id = data.get("session_id")
        if not session_id or not isinstance(session_id, str):
            return {"code": -1, "error": "Missing session_id"}
        session = self._lookup_session(session_id)
        if session is None:
            return {"code": -1, "error": f"Session not found: {session_id}"}
        cancel_running = bool(data.get("cancel_running", True))
        if session.status == "running" and not cancel_running:
            return {"code": -1,
                    "error": "Session is currently running; pass "
                             "cancel_running=true to force-close"}
        self._close_session_internal(session, reason="client")
        return {"code": 0, "status": "closed"}

    def _handle_cancel_session(self, data: Any) -> Dict[str, Any]:
        """Cancel the currently running generation, keep the session alive."""
        if not isinstance(data, dict):
            return {"code": -1, "error": "cancel_session expects a JSON object"}
        session_id = data.get("session_id")
        if not session_id or not isinstance(session_id, str):
            return {"code": -1, "error": "Missing session_id"}
        session = self._lookup_session(session_id)
        if session is None:
            return {"code": -1, "error": f"Session not found: {session_id}"}
        with session.lock:
            ev = session.current_cancel_event
            if ev is None:
                return {"code": 0, "status": "no_active_task"}
            ev.set()
        print(f"[Service] Cancel requested for session {session_id}")
        return {"code": 0, "status": "cancel_requested"}

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
        Update the global default system message for NEW sessions.

        This API is fully supported by llm_service because it owns an
        in-process message history and a live llama.cpp context. The
        proxy sibling (llm_proxy.py) does NOT support it: it is a
        stateless forwarder whose sessions capture their system
        message at creation time.
        """
        if not isinstance(data, dict):
            return {"code": -1, "error": "set_system_message expects a JSON object"}
        new_msg = data.get("content")
        if new_msg is None or not isinstance(new_msg, str):
            return {"code": -1, "error": "Missing or invalid 'content' field"}
        with self._system_message_lock:
            self._system_message = new_msg
        preview = new_msg[:50] + ("..." if len(new_msg) > 50 else "")
        print(f"[Service] Global default system message updated: {preview} "
              f"(applies to NEW sessions only)")
        return {"code": 0, "status": "ok"}

    def _handle_get_api_capabilities(self, data: Any) -> Dict[str, Any]:
        """
        Return the API capability matrix for this server kind.

        Response shape (identical to llm_proxy.py):

            {
              "code": 0,
              "server_kind": "service",
              "capabilities": {
                  "<api_name>": 0 | 1,
                  ...
              }
            }

        A value of 1 means the API is supported by this server,
        0 means it is not (it belongs to the sibling server kind,
        llm_proxy). Clients should call this API at startup or
        before invoking any feature that may be server-kind specific.
        """
        return {
            "code": 0,
            "server_kind": SERVER_KIND,
            "capabilities": dict(API_CAPABILITIES),
        }

    def _handle_health(self, data: Any) -> Dict[str, Any]:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        idle = sum(1 for s in sessions if s.status == "idle")
        running = sum(1 for s in sessions if s.status == "running")
        return {
            "code": 0,
            "status": "ok",
            "server_kind": SERVER_KIND,
            "backend": self.backend,
            "model": CONFIG.model_path,
            "context_size_requested": CONFIG.context_size,
            "context_size_actual": CONFIG.context_size_actual,
            "sessions_total": len(sessions),
            "sessions_idle": idle,
            "sessions_running": running,
            "session_limit": CONFIG.max_sessions,
            "session_timeout": CONFIG.session_timeout,
            "queue_size": self._request_queue.qsize(),
            "queue_max_size": CONFIG.queue_max_size,
            "chat_template_path": CONFIG.chat_template_resolved_path,
            "chat_template_loaded": CONFIG.default_template is not None,
            # The capability matrix is included in health so that a
            # single call is enough for a client to learn everything it
            # needs about this server kind.
            "api_capabilities": dict(API_CAPABILITIES),
        }

    # ------------------------------------------------------------------
    # Token budget
    # ------------------------------------------------------------------
    def _check_token_budget(
        self,
        session: Session,
        content: str,
        prompt: str,
        options: Dict[str, Any],
        system_message: str,
    ) -> Optional[str]:
        """
        Estimate the total prompt length (system + history + new input)
        plus the requested output and check it against the effective
        context window.
        """
        max_tokens = options.get("max_tokens", CONFIG.max_tokens)
        new_input = content + "\n\n" + prompt

        # Cheap pre-check: total character count of history + system + new.
        total_chars = (
            len(system_message)
            + sum(len(str(m.get("content", ""))) for m in session.messages)
            + len(new_input)
        )
        # A conservative 1-token-per-2-chars estimate is used as a first
        # approximation; tokenize the largest single piece for calibration.
        input_tokens = estimate_tokens(self.llm, self.tokenizer, new_input)
        if input_tokens is None:
            input_tokens = len(new_input) // 2 + 1
        # Add a rough per-message overhead and the accumulated history.
        history_overhead = 8 * len(session.messages) + 32
        history_tokens = sum(
            (estimate_tokens(self.llm, self.tokenizer,
                             str(m.get("content", ""))) or
             (len(str(m.get("content", ""))) // 2 + 1))
            for m in session.messages
        )
        sys_tokens = estimate_tokens(self.llm, self.tokenizer, system_message) or (
            len(system_message) // 2 + 1
        )

        total_needed = (
            input_tokens + sys_tokens + history_tokens + history_overhead
            + max_tokens + 32
        )
        if total_needed > CONFIG.context_size_actual:
            return (
                f"Request too large: input={input_tokens} tokens, "
                f"system={sys_tokens} tokens, history={history_tokens} tokens, "
                f"max_output={max_tokens} tokens, "
                f"total={total_needed} > context={CONFIG.context_size_actual}"
            )
        return None

    # ------------------------------------------------------------------
    # Task processing (runs on worker thread)
    # ------------------------------------------------------------------
    def _process_task(self, task: GenerationTask) -> None:
        session = task.session

        # ---- Session may have been closed while task was queued ----
        with self._sessions_lock:
            if session.session_id not in self._sessions:
                print(f"[Task {task.task_id}] Session {session.session_id} "
                      f"no longer exists; dropping task")
                return

        # ---- Mark session as running and bind this task's cancel event ----
        with session.lock:
            session.status = "running"
            session.current_cancel_event = task.cancel_event

        # ---- Immediate cancel check ----
        if task.cancel_event.is_set():
            self._finalize_task(session, task, cancelled=True)
            return

        thinking = bool(task.options.get("thinking", False))
        max_tokens = task.options.get("max_tokens", CONFIG.max_tokens)
        temperature = task.options.get("temperature", 0.7)
        top_p = task.options.get("top_p", 0.95)
        top_k = task.options.get("top_k", 40)
        repeat_penalty = task.options.get("repeat_penalty", 1.1)

        print(f"[Task {task.task_id}] Generation started "
              f"(session={session.session_id}, client={session.client_name}, "
              f"thinking={thinking}, max_tokens={max_tokens}, "
              f"history={len(session.messages)})")

        # ---- Build messages (system + history + new user) ----
        with session.lock:
            history = [dict(m) for m in session.messages]
        new_user_content = task.content + "\n\n" + task.prompt
        messages = [{"role": "system", "content": session.system_message}]
        messages.extend(history)
        messages.append({"role": "user", "content": new_user_content})

        # ---- Generate ----
        try:
            if self.backend == "llama_cpp":
                think_text, answer_text = self._run_llama_cpp(
                    session, task, messages,
                    max_tokens, temperature, top_p, top_k, repeat_penalty,
                    thinking,
                )
            elif self.backend == "transformers":
                self._emit_error(
                    session,
                    "transformers backend streaming is not implemented; "
                    "please use llama-cpp-python",
                )
                self._finalize_task(session, task, error="transformers backend unsupported")
                return
            else:
                self._finalize_task(session, task, error="No LLM backend available")
                return
        except Exception as e:
            msg = str(e)
            lowered = msg.lower()
            if "out of memory" in lowered or "cuda out of memory" in lowered:
                msg = "CUDA out of memory - reduce max_tokens or use a smaller model"
            elif "context" in lowered and "length" in lowered:
                msg = (f"Context length exceeded - maximum context size "
                       f"{CONFIG.context_size_actual} tokens")
            print(f"[Task {task.task_id}] Generation error: {msg}")
            self._finalize_task(session, task, error=msg)
            return

        # ---- Success path ----
        self._finalize_task(
            session, task,
            think=think_text, answer=answer_text,
            cancelled=task.cancel_event.is_set(),
        )

    def _finalize_task(
        self,
        session: Session,
        task: GenerationTask,
        think: str = "",
        answer: str = "",
        cancelled: bool = False,
        error: Optional[str] = None,
    ) -> None:
        """
        Common end-of-task bookkeeping:
          - append user/assistant messages to history (only on success)
          - clear the running flags
          - send the appropriate terminal notification
          - if the task is ephemeral, close the session
        """
        # ---- Update session state ----
        with session.lock:
            if error is None and not cancelled:
                user_input = (task.content + "\n\n" + task.prompt)
                session.messages.append({"role": "user", "content": user_input})
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": answer,
                }
                if think:
                    assistant_msg["reasoning_content"] = think
                session.messages.append(assistant_msg)
                # Trim history if it grows too large.
                if len(session.messages) > MAX_HISTORY_MESSAGES:
                    drop = len(session.messages) - MAX_HISTORY_MESSAGES
                    session.messages = session.messages[drop:]
            session.last_active_at = time.monotonic()
            session.status = "idle"
            session.current_cancel_event = None

        # ---- Terminal notification ----
        if error is not None:
            self._emit_error(session, error)
            self._emit_finish(session, "error")
        elif cancelled:
            self._emit_finish(session, "cancelled")
        else:
            self._emit_finish(session, "stop")

        print(f"[Task {task.task_id}] Finished "
              f"(session={session.session_id}, "
              f"cancelled={cancelled}, error={bool(error)}, "
              f"history={len(session.messages)})")

        # ---- Ephemeral auto-close ----
        if task.ephemeral:
            self._close_session_internal(session, reason="ephemeral")

    def _run_llama_cpp(
        self,
        session: Session,
        task: GenerationTask,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        repeat_penalty: float,
        thinking: bool,
    ) -> Tuple[str, str]:
        """
        Drive a single streaming generation. Returns (think_text, answer_text).
        Both buffers accumulate the same text that is sent to the client
        and are used to build the assistant message stored in history.
        """
        template = CONFIG.default_template
        think_parts: List[str] = []
        answer_parts: List[str] = []

        if template:
            try:
                from jinja2 import Template
            except ImportError:
                raise RuntimeError(
                    "Chat template supplied but jinja2 is not installed"
                )
            tpl = Template(template)
            prompt_str = tpl.render(
                messages=messages,
                add_generation_prompt=True,
                bos_token="<s>",
                eos_token="</s>",
                enable_thinking=thinking,
                truncate_history_thinking=True,
                reasoning_budget_message=CONFIG.reasoning_budget_message,
            )
            stream = self.llm.create_completion(
                prompt=prompt_str,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
                stream=True,
            )
            chunk_key = "text"
            parser = ThinkingParser(initial_in_thinking=thinking) if thinking else None
        else:
            stream = self.llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
                stream=True,
            )
            chunk_key = "delta"
            parser = ThinkingParser(initial_in_thinking=False) if thinking else None

        for chunk in stream:
            if task.cancel_event.is_set():
                print(f"[Task {task.task_id}] Cancelled mid-stream")
                break
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]

            if chunk_key == "text":
                text = choice.get("text", "") or ""
            else:
                delta = choice.get("delta") or {}
                text = delta.get("content", "") or ""

            if not text:
                continue

            if parser is not None:
                for mtype, mtext in parser.feed(text):
                    if not mtext:
                        continue
                    if mtype == "think":
                        think_parts.append(mtext)
                    else:
                        answer_parts.append(mtext)
                    self._emit_message(session, mtype, mtext)
            else:
                answer_parts.append(text)
                self._emit_message(session, "chunk", text)

        if parser is not None:
            for mtype, mtext in parser.flush():
                if not mtext:
                    continue
                if mtype == "think":
                    think_parts.append(mtext)
                else:
                    answer_parts.append(mtext)
                self._emit_message(session, mtype, mtext)

        return "".join(think_parts), "".join(answer_parts)

    # ------------------------------------------------------------------
    # Message emission
    # ------------------------------------------------------------------
    def _emit_message(self, session: Session, msg_type: str, text: str) -> None:
        payload = {
            "type": msg_type,
            "session_id": session.session_id,
            "text": text,
        }
        self._send_payload(session, payload)
        if msg_type != "chunk" and CONFIG.enable_chunk_logging:
            preview = text[:120] + ("..." if len(text) > 120 else "")
            print(f"[Session {session.session_id}] {msg_type}: {preview}")

    def _emit_error(self, session: Session, message: str) -> None:
        self._emit_message_raw(session, {
            "type": "error",
            "session_id": session.session_id,
            "message": message,
        })
        print(f"[Session {session.session_id}] ERROR: {message}")

    def _emit_finish(self, session: Session, reason: str) -> None:
        self._emit_message_raw(session, {
            "type": "finish",
            "session_id": session.session_id,
            "reason": reason,
        })

    def _emit_message_raw(self, session: Session, payload: Dict[str, Any]) -> None:
        self._send_payload(session, payload)

    def _send_payload(self, session: Session, payload: Dict[str, Any]) -> None:
        hnd = None
        try:
            if CONFIG.enable_warning_logging and not check_app(session.client_name):
                print(f"[Session {session.session_id}] WARNING: "
                      f"client app '{session.client_name}' not reachable "
                      f"(cache may lag; attempting send anyway)")
            hnd = DataHandle(CONFIG.notify_api)
            hnd.write_json(payload)
            LF_Sequenced_Notify(session.client_name.encode("utf-8"), hnd.raw)
        except Exception as e:
            print(f"[Session {session.session_id}] send failed "
                  f"({payload.get('type')}): {e}")
        finally:
            if hnd is not None:
                try:
                    hnd.free()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        """Idempotent cleanup. Safe to call from atexit and finally."""
        if self._cleaned_up:
            return
        self._cleaned_up = True

        print("[Service] Cleanup: signalling threads to stop...")
        self._shutdown_event.set()

        # Close all sessions with a shutdown notice.
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        for sess in sessions:
            self._close_session_internal(sess, reason="shutdown")

        # Wake the worker with a sentinel.
        try:
            self._request_queue.put_nowait(None)
        except queue.Full:
            pass

        # Join worker.
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=15.0)
            if self._worker_thread.is_alive():
                print("[Service] WARNING: worker thread did not exit in time")

        # Watchdog uses wait(timeout=5.0), so it will exit promptly.
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=6.0)

        # Stop the LingoFuse server.
        try:
            self.server.stop()
        except Exception as e:
            print(f"[Service] Server stop error: {e}")

        # Close the model if the backend supports it.
        try:
            if hasattr(self.llm, "close"):
                self.llm.close()
        except Exception:
            pass

        print("[Service] Cleanup complete")


# ----------------------------------------------------------------------
# Startup banner
# ----------------------------------------------------------------------
def print_service_status() -> None:
    ctx_requested = ("auto (model maximum)" if CONFIG.context_size == 0
                     else str(CONFIG.context_size))

    if CONFIG.chat_template_resolved_path:
        template_display = CONFIG.chat_template_resolved_path
        template_display += (" (explicit)" if CONFIG.chat_template_path
                             else " (auto-discovered)")
    else:
        template_display = "(model built-in)"

    rbm = CONFIG.reasoning_budget_message or ""
    rbm_preview = (rbm[:40] + "...") if len(rbm) > 40 else rbm
    rbm_preview = rbm_preview.replace("\n", "\\n")

    # Build a compact, human-readable view of the capability matrix:
    # group supported APIs and unsupported APIs on two lines.
    supported = [k for k, v in API_CAPABILITIES.items() if v == 1]
    unsupported = [k for k, v in API_CAPABILITIES.items() if v == 0]

    lines = [
        "=" * 70,
        " LINGOFUSE LLM SERVICE STATUS (v3.2)",
        "=" * 70,
        f"  Server kind             : {SERVER_KIND}",
        f"  Backend                 : {LLM_BACKEND}",
        f"  Model path              : {CONFIG.model_path}",
        f"  Context size requested  : {ctx_requested}",
        f"  Context size actual     : {CONFIG.context_size_actual}",
        f"  Default max tokens      : {CONFIG.max_tokens}",
        f"  CPU threads             : {CONFIG.threads}",
        f"  GPU layers offloaded    : {CONFIG.gpu_layers}",
        f"  LingoFuse endpoint      : {CONFIG.endpoint}",
        f"  Service app name        : {CONFIG.app_name}",
        f"  Notify API name         : {CONFIG.notify_api}",
        f"  Session idle timeout(s) : {CONFIG.session_timeout}",
        f"  Queue max size          : {CONFIG.queue_max_size}",
        f"  Max sessions            : {CONFIG.max_sessions}",
        f"  Chat template           : {template_display}",
        f"  Reasoning budget msg    : \"{rbm_preview}\"",
        f"  Log level               : {CONFIG.log_level}",
        "-" * 70,
        f"  Watchdog policy         : reclaim only when idle past the timeout",
        f"                            AND the client app is offline",
        f"  Supported APIs          : {', '.join(supported)}",
        f"  Unsupported APIs        : {', '.join(unsupported) or '(none)'}",
        "=" * 70,
    ]
    print("\n".join(lines))


# ----------------------------------------------------------------------
# Signal handling
# ----------------------------------------------------------------------
_shutdown_requested = threading.Event()


def _install_signal_handlers() -> None:
    def _handler(signum, frame):
        print(f"\n[Service] Received signal {signum}; shutting down...")
        _shutdown_requested.set()

    for sig in ("SIGINT", "SIGTERM"):
        s = getattr(signal, sig, None)
        if s is None:
            continue
        try:
            signal.signal(s, _handler)
        except (ValueError, OSError):
            pass


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    _init_global_config(args)

    if CONFIG.log_level >= 2:
        print("[DEBUG] Effective configuration:", file=sys.stderr)
        for k, v in vars(CONFIG).items():
            if k == "default_template" and v is not None:
                print(f"  {k} = <{len(v)} bytes>", file=sys.stderr)
            else:
                print(f"  {k} = {v}", file=sys.stderr)

    if not os.path.exists(CONFIG.model_path):
        print(f"[ERROR] Model file not found: {CONFIG.model_path}",
              file=sys.stderr)
        sys.exit(1)

    _resolve_and_load_template()

    service: Optional[LLMService] = None
    try:
        service = LLMService()
        print_service_status()
        _install_signal_handlers()

        service.server.start(CONFIG.endpoint)
        print(f"[Service] LLM Service is running on {CONFIG.endpoint}")
        print("[Service] Press Ctrl+C to stop...")

        while not _shutdown_requested.is_set():
            if _shutdown_requested.wait(timeout=1.0):
                break

    except KeyboardInterrupt:
        print("\n[Service] Interrupted by user")
    except Exception as e:
        print(f"[FATAL] Service error: {e}", file=sys.stderr)
        traceback.print_exc()
        if service is not None:
            service.cleanup()
        sys.exit(1)
    finally:
        if service is not None:
            service.cleanup()


if __name__ == "__main__":
    main()