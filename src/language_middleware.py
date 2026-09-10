# -*- coding: utf-8 -*-
"""
language_middleware.py - v7.3 (LingoFuse Native Multi-Language Middleware)

DESCRIPTION
    This module provides a language-agnostic middleware for LingoFuse,
    designed to act as a bridge between MCP (Model Context Protocol)
    servers (like mcp_server.py) and a backend tool provider implemented
    in any language (Pascal, Python, etc.). It handles:

        - Lazy connection to a LingoFuse endpoint (IPC or TCP).
        - Dynamic retrieval of tool definitions from the backend via
          `agent_main`.
        - Log forwarding to the backend via `agent_log`.
        - Invocation of tools via `call_tool` by name.
        - Optional dynamic tool registration via the `register_agent`
          API.

    The middleware uses direct ctypes calls to the LingoFuse dynamic
    library and is fully thread-safe. It implements a singleton pattern
    to share the same connection across multiple components.

CHANGELOG (v7.3)
    * `_read_string` now mirrors Pascal's LF_ReadString behavior: when
      no null terminator is found, it returns the entire remaining
      buffer instead of an empty bytes object. This is important for
      inputs that were not null-terminated (e.g. raw JSON from an HTTP
      bridge).
    * `call_tool` serializes arguments with `ensure_ascii=False` so
      that non-ASCII characters (e.g. Chinese) reach the backend
      unescaped.
    * `_reg_tool_callback` now reads the "name" field (matching the
      Pascal side's `do_register_agent`) instead of the non-existent
      "tool_name". Previously, every registration attempt failed with
      "Missing tool_name".
    * Removed unused native imports to keep the module self-consistent
      with the API actually exercised at runtime.

CONFIGURATION (defaults can be overridden by environment variables or
              passed to get_instance())
    LINGOFUSE_ENDPOINT              - LingoFuse endpoint (default: ipc:agent)
    LINGOFUSE_TIMEOUT_MS            - Call timeout in ms (default: 5000)
    LINGOFUSE_REG_AGENT_APP         - Local app name used by this client
                                      (default: reg_agent)
    LINGOFUSE_TOOL_PROVIDER_APP     - Backend app that provides tools
                                      (default: agent_main_app)
    LINGOFUSE_AGENT_MAIN_API        - API to fetch tool list
                                      (default: agent_main)
    LINGOFUSE_AGENT_LOG_API         - API to send logs (default: agent_log)
    LINGOFUSE_REGISTER_AGENT_API    - API for dynamic registration
                                      (default: register_agent)

USAGE EXAMPLE (Python)
    from language_middleware import LanguageMiddleware, set_debug_mode

    mw = LanguageMiddleware.get_instance(endpoint='ipc:custom')

    tools = mw.get_tools()
    for t in tools:
        print(t['name'], t['description'])

    result = mw.call_tool('add', {'a': 5, 'b': 7})

    mw.log('Hello from Python')

    set_debug_mode(True)

NOTES
    - Connection is lazy: the middleware does not connect on
      instantiation. It attempts to connect on the first call to
      get_tools(), call_tool() or log().
    - If the backend is unavailable, the middleware logs errors and
      returns empty tool lists or None for log(), but does not raise
      exceptions except when explicitly calling call_tool() (which
      will raise LanguageCallError if the tool is not found or the
      call fails).
    - Dynamic tool registration via `register_agent` does NOT modify
      the local tool cache (`self._tools`). The tool list is entirely
      sourced from the backend's `agent_main` response. This ensures
      consistency and avoids stale entries.

DEPENDENCIES
    - lingofuse package (must be installed or in PYTHONPATH)
    - Python 3.7+

AUTHOR
    PassByYou888 / LingoFuse Team
"""

import os
import sys
import json
import threading
import atexit
import ctypes
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

# ============================================================================
# Configuration (using LINGOFUSE_ prefix)
# ============================================================================
DEFAULT_ENDPOINT = os.environ.get("LINGOFUSE_ENDPOINT", "ipc:agent")
DEFAULT_TIMEOUT_MS = int(os.environ.get("LINGOFUSE_TIMEOUT_MS", "5000"))
DEFAULT_REG_AGENT_APP_NAME = os.environ.get("LINGOFUSE_REG_AGENT_APP", "reg_agent")
DEFAULT_TOOL_PROVIDER_APP = os.environ.get("LINGOFUSE_TOOL_PROVIDER_APP", "agent_main_app")
DEFAULT_AGENT_MAIN_API = os.environ.get("LINGOFUSE_AGENT_MAIN_API", "agent_main")
DEFAULT_AGENT_LOG_API = os.environ.get("LINGOFUSE_AGENT_LOG_API", "agent_log")
DEFAULT_REGISTER_AGENT_API = os.environ.get("LINGOFUSE_REGISTER_AGENT_API", "register_agent")

# ========================================================================
# Add lingofuse package path
# ========================================================================
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from lingofuse._lf_native import (
    DataHnd, AppHnd,
    LF_CreateData,
    LF_FreeData,
    LF_CreateApp,
    LF_FreeApp,
    LF_RegisterCall,
    LF_WriteBuffer,
    LF_ReadBuffer,
    LF_GetPos,
    LF_SetPos,
    LF_GetSize,
    LF_GetBuffer,
    LF_PrepareClient,
    LF_ResetPrepare,
    LF_PrepareDone,
    LF_ExitMainThread,
    LF_Shutdown,
    LF_Call,
    LF_SetOption,
    LF_CheckMainThread,
    LFCallFunc,
)

# ============================================================================
# Debug mode and log buffer (global)
# ============================================================================
DEBUG_MODE = False
_LOG_BUFFER = deque(maxlen=100)
_LOG_LOCK = threading.Lock()


def set_debug_mode(mode: bool):
    """Enable or disable verbose debug output."""
    global DEBUG_MODE
    DEBUG_MODE = mode
    sys.stderr.write(f"[DEBUG] Mode switched to {'ON' if mode else 'OFF'}\n")
    sys.stderr.flush()


def get_logs() -> List[str]:
    """Return a copy of the internal debug log buffer."""
    with _LOG_LOCK:
        return list(_LOG_BUFFER)


def clear_logs():
    """Clear the internal debug log buffer."""
    with _LOG_LOCK:
        _LOG_BUFFER.clear()


def _log_entry(entry: str):
    """Append one entry to the internal debug log buffer."""
    with _LOG_LOCK:
        _LOG_BUFFER.append(entry)


# ============================================================================
# Manual string read/write helpers (using LF_ functions)
# ============================================================================
def _write_string(hnd: DataHnd, s: bytes):
    """Write bytes to a DataHandle with a null terminator."""
    if len(s) > 0:
        LF_WriteBuffer(hnd, s, len(s))
    null = b'\x00'
    LF_WriteBuffer(hnd, null, 1)


def _read_string(hnd: DataHnd) -> bytes:
    """
    Read a UTF-8 string from a DataHandle.

    Behavior mirrors Pascal's LF_ReadString:
      * Scan forward for a null byte (\\0).
      * If found, return bytes up to (but not including) the null, and
        advance the position past the null.
      * If NOT found, return the entire remaining buffer and move the
        position to the end.

    This makes the function tolerant of inputs that were not
    null-terminated (e.g. raw JSON from an HTTP bridge).
    """
    pos = LF_GetPos(hnd)
    size = LF_GetSize(hnd)
    if pos >= size:
        return b''

    ptr = LF_GetBuffer(hnd)
    if not ptr:
        return b''

    cptr = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_byte))
    end = pos
    while end < size and cptr[end] != 0:
        end += 1

    if end < size:
        # Null terminator found.
        data_len = end - pos
        if data_len == 0:
            LF_SetPos(hnd, end + 1)
            return b''
        raw = (ctypes.c_byte * data_len)()
        LF_ReadBuffer(hnd, raw, data_len)
        LF_SetPos(hnd, end + 1)
        return bytes(raw)
    else:
        # No null terminator: consume everything that remains.
        data_len = size - pos
        if data_len == 0:
            return b''
        raw = (ctypes.c_byte * data_len)()
        LF_ReadBuffer(hnd, raw, data_len)
        LF_SetPos(hnd, size)
        return bytes(raw)


# ============================================================================
# Exceptions
# ============================================================================
class LanguageMiddlewareError(Exception):
    """Base exception for all middleware-related errors."""
    pass


class LanguageConnectionError(LanguageMiddlewareError):
    """Raised when the middleware cannot connect to the backend."""
    pass


class LanguageCallError(LanguageMiddlewareError):
    """Raised when a tool invocation fails."""
    pass


# ============================================================================
# Callback for register_agent (only used if the API is enabled)
# ============================================================================
_mw_instance = None


@LFCallFunc
def _reg_tool_callback(trigger: DataHnd, inp: DataHnd, out: DataHnd):
    """
    Callback for the `register_agent` API.

    Input JSON (matching Pascal's `do_register_agent`):
        {
            "name":        "tool_name",
            "description": "...",
            "target_app":  "backend_app",
            "target_api":  "backend_api",
            "parameters":  { ... JSON Schema ... }
        }

    The middleware deliberately does NOT modify its local tool cache
    here. The authoritative tool list is always fetched from
    `agent_main`. This callback only logs the event.
    """
    global _mw_instance
    if _mw_instance is None:
        sys.stderr.write("[reg_tool] Middleware instance not available\n")
        sys.stderr.flush()
        return

    try:
        LF_SetPos(inp, 0)
        raw = _read_string(inp)
        if not raw:
            raise ValueError("Empty input")

        req = json.loads(raw.decode('utf-8'))

        # Field names must match the Pascal producer (do_register_agent).
        name = req.get('name')
        if not name:
            raise ValueError('Missing "name" field')

        description = req.get('description', '')

        target_app = req.get('target_app')
        if not target_app:
            raise ValueError('Missing "target_app" field')

        target_api = req.get('target_api')
        if not target_api:
            raise ValueError('Missing "target_api" field')

        # Log the registration event. Do NOT touch self._tools here.
        _mw_instance._register_tool(name, description, target_app, target_api)

        resp = json.dumps(
            {"status": "ok",
             "message": f"Tool '{name}' registered successfully"},
            ensure_ascii=False,
        )
        _write_string(out, resp.encode('utf-8'))
        sys.stderr.write(
            f"[reg_tool] Registered tool: {name} -> {target_app}.{target_api}\n"
        )
        sys.stderr.flush()

    except Exception as e:
        err_msg = json.dumps(
            {"status": "error", "message": str(e)},
            ensure_ascii=False,
        )
        _write_string(out, err_msg.encode('utf-8'))
        sys.stderr.write(f"[reg_tool] Error: {e}\n")
        sys.stderr.flush()


# ============================================================================
# Core singleton class
# ============================================================================
class LanguageMiddleware:
    """
    Singleton class that manages the LingoFuse connection and tool
    registry.
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 endpoint: str = DEFAULT_ENDPOINT,
                 timeout_ms: int = DEFAULT_TIMEOUT_MS,
                 reg_agent_app_name: str = DEFAULT_REG_AGENT_APP_NAME,
                 tool_provider_app: str = DEFAULT_TOOL_PROVIDER_APP,
                 agent_main_api: str = DEFAULT_AGENT_MAIN_API,
                 agent_log_api: str = DEFAULT_AGENT_LOG_API,
                 register_agent_api: str = DEFAULT_REGISTER_AGENT_API):
        """
        Initialize the middleware with the given parameters.
        The connection is not established until first use.
        """
        if LanguageMiddleware._initialized:
            self._update_config(endpoint, timeout_ms, reg_agent_app_name,
                                tool_provider_app, agent_main_api,
                                agent_log_api, register_agent_api)
            return
        with LanguageMiddleware._lock:
            if LanguageMiddleware._initialized:
                return
            self._endpoint = endpoint
            self._timeout_ms = timeout_ms
            self._reg_agent_app_name = reg_agent_app_name
            self._tool_provider_app = tool_provider_app
            self._agent_main_api = agent_main_api
            self._agent_log_api = agent_log_api
            self._register_agent_api = register_agent_api
            self._app_hnd = None
            self._tools: Dict[str, Dict] = {}
            self._shutdown_hook_registered = False
            self._started = False
            self._connection_attempted = False
            self._connect_lock = threading.Lock()

            # Global LingoFuse options
            LF_SetOption(b"Wait_Connection_ReadyOk", b"True")
            LF_SetOption(b"Wait_TimeOut", str(timeout_ms).encode('utf-8'))

            # Local app that hosts register_agent.
            self._app_hnd = LF_CreateApp(
                self._reg_agent_app_name.encode('utf-8'),
                b"Registration Agent for tool discovery"
            )
            if not self._app_hnd:
                raise LanguageConnectionError("Failed to create App")

            if self._register_agent_api:
                ret = LF_RegisterCall(
                    self._app_hnd,
                    self._register_agent_api.encode('utf-8'),
                    b"Register a new agent tool",
                    None,
                    _reg_tool_callback
                )
                if ret != 1:
                    sys.stderr.write(
                        "[LanguageMiddleware] Warning: Failed to register "
                        "reg_tool; registration API will not work.\n"
                    )
                else:
                    sys.stderr.write("[LanguageMiddleware] Registered reg_tool API.\n")

            global _mw_instance
            _mw_instance = self

            self._started = False
            self._connection_attempted = False

            if not self._shutdown_hook_registered:
                atexit.register(self._cleanup)
                self._shutdown_hook_registered = True

            LanguageMiddleware._initialized = True
            sys.stderr.write("[LanguageMiddleware] Initialized (lazy connection mode).\n")
            sys.stderr.flush()

    def _update_config(self, endpoint, timeout_ms, reg_agent_app_name,
                       tool_provider_app, agent_main_api,
                       agent_log_api, register_agent_api):
        """Update configuration and force reconnect if already started."""
        if endpoint is not None:
            self._endpoint = endpoint
        if timeout_ms is not None:
            self._timeout_ms = timeout_ms
        if reg_agent_app_name is not None:
            self._reg_agent_app_name = reg_agent_app_name
        if tool_provider_app is not None:
            self._tool_provider_app = tool_provider_app
        if agent_main_api is not None:
            self._agent_main_api = agent_main_api
        if agent_log_api is not None:
            self._agent_log_api = agent_log_api
        if register_agent_api is not None:
            self._register_agent_api = register_agent_api
        if self._started:
            self._disconnect()
        self._started = False
        self._connection_attempted = False
        sys.stderr.write("[LanguageMiddleware] Configuration updated.\n")
        sys.stderr.flush()

    def _connect(self) -> bool:
        """Establish a connection to the LingoFuse endpoint and fetch tools."""
        with self._connect_lock:
            if self._started:
                return True
            if self._connection_attempted:
                return False
            self._connection_attempted = True
            try:
                sys.stderr.write(
                    f"[LanguageMiddleware] Connecting to {self._endpoint}...\n"
                )
                LF_ResetPrepare()
                LF_PrepareClient(self._endpoint.encode('utf-8'), self._app_hnd)

                if LF_PrepareDone() != 1:
                    raise LanguageConnectionError(
                        f"LF_PrepareDone failed for {self._endpoint}"
                    )

                self._started = True
                sys.stderr.write(
                    f"[LanguageMiddleware] Connected to {self._endpoint}\n"
                )
                self._fetch_tools_from_backend()
                return True
            except Exception as e:
                sys.stderr.write(f"[LanguageMiddleware] Connection failed: {e}\n")
                self._started = False
                return False

    def _disconnect(self):
        """Disconnect from the backend and reset state."""
        if self._started:
            try:
                LF_ExitMainThread()
                LF_Shutdown()
                sys.stderr.write("[LanguageMiddleware] Disconnected.\n")
            except Exception as e:
                sys.stderr.write(
                    f"[LanguageMiddleware] Error during disconnect: {e}\n"
                )
            self._started = False
            self._connection_attempted = False

    def _ensure_connected(self) -> bool:
        """Ensure a connection exists; if not, attempt to connect."""
        if self._started:
            return True
        return self._connect()

    def _fetch_tools_from_backend(self):
        """
        Call the backend's agent_main API to retrieve the list of tools.
        Populates the internal _tools dictionary.
        """
        try:
            req = LF_CreateData(self._agent_main_api.encode('utf-8'))
            resp = LF_Call(self._tool_provider_app.encode('utf-8'),
                           req, self._timeout_ms)
            LF_FreeData(req)

            if not resp:
                sys.stderr.write(
                    "[LanguageMiddleware] Failed to get tool info: no response\n"
                )
                return

            LF_SetPos(resp, 0)
            raw = _read_string(resp)
            LF_FreeData(resp)

            if not raw:
                sys.stderr.write(
                    "[LanguageMiddleware] Failed to get tool info: empty response\n"
                )
                return

            data = json.loads(raw.decode('utf-8'))

            if DEBUG_MODE:
                formatted = json.dumps(data, indent=2, ensure_ascii=False)
                sys.stderr.write(
                    f"\n[LanguageMiddleware] Received tool info JSON:\n{formatted}\n\n"
                )

            tools = data.get('tools', [])
            # Replace the entire tool dictionary with the fresh list.
            self._tools.clear()
            for t in tools:
                name = t.get('name')
                if not name:
                    continue
                self._tools[name] = {
                    'name': name,
                    'description': t.get('description', ''),
                    'target_app': t.get('target_app', self._tool_provider_app),
                    'target_api': t.get('target_api', name),
                    'parameters': t.get('parameters', {}),
                }

            sys.stderr.write(
                f"\n[LanguageMiddleware] Retrieved {len(tools)} tools from backend:\n"
            )
            for name, info in self._tools.items():
                sys.stderr.write(
                    f"  - {name}: {info['description']} "
                    f"-> {info['target_app']}.{info['target_api']}\n"
                )
            sys.stderr.write("\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(
                f"\n[LanguageMiddleware] Exception while fetching tools: {e}\n"
            )
            sys.stderr.flush()

    def _register_tool(self, tool_name: str, description: str,
                       target_app: str, target_api: str):
        """
        Record a tool registration event. This method does NOT modify
        the local tool cache. It only logs the event. The cache is
        exclusively updated by _fetch_tools_from_backend().
        """
        sys.stderr.write(
            f"[LanguageMiddleware] Tool registered (not cached): "
            f"{tool_name} -> {target_app}.{target_api}\n"
        )
        sys.stderr.flush()

    def _cleanup(self):
        """Clean up LingoFuse resources when the interpreter exits."""
        if self._started:
            try:
                LF_ExitMainThread()
                LF_Shutdown()
                self._started = False
                sys.stderr.write("[LanguageMiddleware] Resources cleaned up.\n")
                sys.stderr.flush()
            except Exception as e:
                sys.stderr.write(
                    f"[LanguageMiddleware] Exception during cleanup: {e}\n"
                )
                sys.stderr.flush()
        if self._app_hnd:
            LF_FreeApp(self._app_hnd)
            self._app_hnd = None
        LanguageMiddleware._initialized = False

    def shutdown(self):
        """Explicitly shut down the middleware and release resources."""
        self._cleanup()

    def get_tools(self) -> List[Dict[str, Any]]:
        """
        Return the list of available tools.

        If not connected, attempts to connect and fetch tools.
        Returns an empty list if the connection fails.
        """
        if not self._ensure_connected():
            sys.stderr.write(
                "[LanguageMiddleware] Not connected, returning empty tool list.\n"
            )
            return []
        return list(self._tools.values())

    def log(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Send a log message to the backend via agent_log.

        Returns the backend's JSON response (dict) on success, None on
        failure.
        """
        if not self._ensure_connected():
            sys.stderr.write("[log] Not connected, log message dropped.\n")
            return None
        try:
            req = LF_CreateData(self._agent_log_api.encode('utf-8'))
            payload = json.dumps({"message": message},
                                 ensure_ascii=False).encode('utf-8')
            _write_string(req, payload)

            resp = LF_Call(self._tool_provider_app.encode('utf-8'),
                           req, self._timeout_ms)
            LF_FreeData(req)

            if not resp:
                sys.stderr.write("[log] No response from backend.\n")
                return None

            LF_SetPos(resp, 0)
            raw = _read_string(resp)
            LF_FreeData(resp)

            if not raw:
                sys.stderr.write("[log] Empty response from backend.\n")
                return None

            return json.loads(raw.decode('utf-8'))
        except Exception as e:
            sys.stderr.write(f"[log] Failed to send log: {e}\n")
            sys.stderr.flush()
            return None

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Invoke a tool by name with the given arguments.

        Raises:
            LanguageConnectionError if not connected.
            LanguageCallError if the tool is not registered or the call
            fails.
        Returns the parsed response (usually a dict) from the backend.
        """
        if not self._ensure_connected():
            raise LanguageConnectionError("Not connected to backend")

        tool = self._tools.get(tool_name)
        if not tool:
            error_msg = f"Tool '{tool_name}' not registered"
            sys.stderr.write(f"[call_tool] {error_msg}\n")
            raise LanguageCallError(error_msg)

        target_app = tool['target_app']
        target_api = tool['target_api']

        # Build the request with the arguments as JSON.
        # ensure_ascii=False keeps non-ASCII characters (e.g. Chinese)
        # intact.
        req = LF_CreateData(target_api.encode('utf-8'))
        payload = json.dumps(arguments, ensure_ascii=False).encode('utf-8')
        _write_string(req, payload)

        resp = LF_Call(target_app.encode('utf-8'), req, self._timeout_ms)
        LF_FreeData(req)

        if not resp:
            error_msg = f"LF_Call returned null handle for tool '{tool_name}'"
            sys.stderr.write(f"[call_tool] {error_msg}\n")
            if DEBUG_MODE:
                _log_entry(f"[ERROR] {tool_name}: {error_msg}")
            raise LanguageCallError(error_msg)

        LF_SetPos(resp, 0)
        raw = _read_string(resp)
        LF_FreeData(resp)

        # Parse JSON if possible; otherwise return the raw bytes.
        result = None
        try:
            if raw:
                result = json.loads(raw.decode('utf-8'))
            else:
                result = None
        except Exception:
            result = raw

        if DEBUG_MODE:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            entry = (
                f"[{timestamp}] {tool_name}\n"
                f"  args: {json.dumps(arguments, ensure_ascii=False)}\n"
                f"  raw response: {raw!r}\n"
                f"  result: {json.dumps(result, ensure_ascii=False, default=str) if result is not None else 'None'}"
            )
            _log_entry(entry)
            sys.stderr.write(
                f"[call_tool] {tool_name} called, response logged.\n"
            )

        return result

    def is_connected(self) -> bool:
        """Return True if the middleware is currently connected."""
        if not self._started:
            return False
        try:
            return LF_CheckMainThread() != 0
        except Exception:
            return False

    def reconnect(self):
        """Force a reconnection attempt, discarding the current connection."""
        self._disconnect()
        return self._connect()

    @classmethod
    def get_instance(cls,
                     endpoint: str = None,
                     timeout_ms: int = None,
                     reg_agent_app_name: str = None,
                     tool_provider_app: str = None,
                     agent_main_api: str = None,
                     agent_log_api: str = None,
                     register_agent_api: str = None) -> "LanguageMiddleware":
        """
        Get the singleton instance, optionally updating its
        configuration. Any parameter provided will override the current
        default value.
        """
        instance = cls.__new__(cls)
        if not LanguageMiddleware._initialized:
            instance.__init__(
                endpoint=endpoint or DEFAULT_ENDPOINT,
                timeout_ms=timeout_ms or DEFAULT_TIMEOUT_MS,
                reg_agent_app_name=reg_agent_app_name or DEFAULT_REG_AGENT_APP_NAME,
                tool_provider_app=tool_provider_app or DEFAULT_TOOL_PROVIDER_APP,
                agent_main_api=agent_main_api or DEFAULT_AGENT_MAIN_API,
                agent_log_api=agent_log_api or DEFAULT_AGENT_LOG_API,
                register_agent_api=register_agent_api or DEFAULT_REGISTER_AGENT_API,
            )
        else:
            if (endpoint is not None or timeout_ms is not None or
                    reg_agent_app_name is not None or tool_provider_app is not None or
                    agent_main_api is not None or agent_log_api is not None or
                    register_agent_api is not None):
                instance._update_config(
                    endpoint, timeout_ms, reg_agent_app_name,
                    tool_provider_app, agent_main_api,
                    agent_log_api, register_agent_api,
                )
        return instance


_default_middleware = None


def get_default_middleware() -> LanguageMiddleware:
    """Get the default global middleware instance."""
    global _default_middleware
    if _default_middleware is None:
        _default_middleware = LanguageMiddleware.get_instance()
    return _default_middleware


if __name__ == "__main__":
    print("=== LanguageMiddleware Self-test (v7.3, lazy connect) ===")
    try:
        mw = LanguageMiddleware.get_instance()
        mw._ensure_connected()
        print(f"Connected: {mw.is_connected()}")
        tools = mw.get_tools()
        print(f"Registered tools: {len(tools)}")
        for t in tools:
            print(f"  - {t['name']}: {t.get('description', '')} "
                  f"-> {t.get('target_app')}.{t.get('target_api')}")
            print(f"    parameters: {t.get('parameters', {})}")
        print("\nSelf-test passed. Press Enter to exit...")
        input()
    except Exception as e:
        print(f"\nSelf-test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if '_default_middleware' in globals() and _default_middleware is not None:
            _default_middleware.shutdown()