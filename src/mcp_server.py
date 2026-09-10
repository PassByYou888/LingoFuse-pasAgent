#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py - MCP Server for LingoFuse Backend (v2.42)

DESCRIPTION
    MCP gateway between MCP clients and a LingoFuse backend.

CHANGELOG (v2.42)
    * `signal_handler` now raises KeyboardInterrupt instead of calling
      `sys.exit(0)`. Reason: `sys.exit(0)` raises SystemExit, which is
      not caught by the `except KeyboardInterrupt` branch in `main()`.
      As a result, in http/sse mode the FastMCP subprocess was never
      terminated on Ctrl+C and remained orphaned. Raising
      KeyboardInterrupt lets the existing cleanup path run:
      `mcp_process.terminate()` / `.kill()` and the final log line.

CHANGELOG (v2.41)
    * `_ensure_language_middleware_loaded()` catches import errors and
      leaves the cached symbols as None; the caller reports a friendly
      error via `log_error`.

CHANGELOG (v2.40)
    * Generated tool functions are emitted with type annotations again
      (`a: int`, `b: str`, ...). The v2.35 refactor dropped them, which
      caused FastMCP to advertise empty parameter schemas and LM Studio
      to send `{}` for every argument.

CHANGELOG (v2.39)
    * stdio mode runs FastMCP in the main process (no multiprocessing).
      On Windows, multiprocessing uses spawn, which restarts the
      interpreter, re-imports the LingoFuse native library and
      re-connects to the backend, doubling startup time and exceeding
      the MCP client's initialize timeout.

CHANGELOG (v2.38)
    * In stdio mode, LingoFuse native console output is suppressed
      before any other LingoFuse API is used (ConsoleOutput=False,
      Quiet=True).

USAGE EXAMPLES
    python mcp_server.py
    python mcp_server.py --transport http --host 0.0.0.0 --port 8000
    python mcp_server.py --log-file ./mcp_server.log
    python mcp_server.py --generate-configs --output-dir ./my_configs

DEPENDENCIES
    - fastmcp (>= 0.2.0) and pydantic
    - lingofuse package (must be installed or in PYTHONPATH)
"""

# ============================================================================
# GLOBAL DEFAULTS
# ============================================================================
DEFAULT_ENDPOINT = "ipc:agent"
DEFAULT_TIMEOUT_MS = 5000
DEFAULT_REG_AGENT_APP = "reg_agent"
DEFAULT_TOOL_PROVIDER_APP = "agent_main_app"
DEFAULT_AGENT_MAIN_API = "agent_main"
DEFAULT_AGENT_LOG_API = "agent_log"
DEFAULT_TRANSPORT = "stdio"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_LOG_FILE = None
DEFAULT_DEBUG = False
DEFAULT_SHOW_BANNER = False
DEFAULT_PROXY_PATH = None

# ============================================================================
# GLOBAL CONFIGURATION VARIABLES
# ============================================================================
ENDPOINT = DEFAULT_ENDPOINT
TIMEOUT_MS = DEFAULT_TIMEOUT_MS
REG_AGENT_APP = DEFAULT_REG_AGENT_APP
TOOL_PROVIDER_APP = DEFAULT_TOOL_PROVIDER_APP
AGENT_MAIN_API = DEFAULT_AGENT_MAIN_API
AGENT_LOG_API = DEFAULT_AGENT_LOG_API
TRANSPORT = DEFAULT_TRANSPORT
HOST = DEFAULT_HOST
PORT = DEFAULT_PORT
LOG_FILE = DEFAULT_LOG_FILE
DEBUG = DEFAULT_DEBUG
SHOW_BANNER = DEFAULT_SHOW_BANNER
PROXY_PATH = DEFAULT_PROXY_PATH

# ============================================================================
# STANDARD IMPORTS
# ============================================================================
import asyncio
import sys
import os
import io
import logging
import traceback
import argparse
import json
import ctypes
import keyword
import multiprocessing
import signal
from typing import Dict, Any, List, Optional

# ============================================================================
# Console setup
# ============================================================================
def _setup_console():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        try:
            import ctypes as _ct
            kernel32 = _ct.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 0x0007)
        except Exception:
            pass
        os.environ["UVICORN_LOGGING_COLOR"] = "0"
        os.environ["FORCE_COLOR"] = "0"
        os.environ["NO_COLOR"] = "1"
        os.environ["PYTHONIOENCODING"] = "utf-8"
    else:
        os.environ["PYTHONIOENCODING"] = "utf-8"

_setup_console()

# FastMCP banner suppression
os.environ["FASTMCP_SHOW_SERVER_BANNER"] = "false"
os.environ["FASTMCP_BANNER"] = "none"

# ============================================================================
# Frozen-executable detection
# ============================================================================
def is_frozen_exe() -> bool:
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')

def get_server_script_path() -> str:
    if is_frozen_exe():
        return sys.executable
    return os.path.abspath(__file__)

def _server_dir() -> str:
    if is_frozen_exe():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def get_default_proxy_path() -> Optional[str]:
    server_dir = _server_dir()
    candidates = ["mcp_proxy.exe"] if is_frozen_exe() else ["mcp_proxy.py"]
    for name in candidates:
        p = os.path.join(server_dir, name)
        if os.path.isfile(p):
            return p
    return None

# ============================================================================
# Optional config generator
# ============================================================================
try:
    from generate_agent_json import generate_configs
    _HAS_GENERATOR = True
except ImportError:
    _HAS_GENERATOR = False
    generate_configs = None

# ============================================================================
# Logging
# ============================================================================
_LOGGER: Optional[logging.Logger] = None

def _init_logger():
    global _LOGGER
    _LOGGER = logging.getLogger("mcp_server")
    _LOGGER.handlers.clear()
    if LOG_FILE:
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        _LOGGER.setLevel(logging.DEBUG if DEBUG else logging.INFO)
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _LOGGER.addHandler(handler)
        _LOGGER.propagate = False
    else:
        _LOGGER.addHandler(logging.NullHandler())
        _LOGGER.propagate = False

# ============================================================================
# FastMCP
# ============================================================================
try:
    from fastmcp import FastMCP
except ImportError as e:
    print(f"[FATAL] fastmcp not installed: {e}", file=sys.stderr)
    print("[FATAL] Please run: pip install fastmcp pydantic", file=sys.stderr)
    sys.exit(1)

# ============================================================================
# Lazy-loaded LingoFuse native functions
# ============================================================================
LF_CreateData = None
LF_FreeData = None
LF_WriteBuffer = None
LF_ReadBuffer = None
LF_GetPos = None
LF_SetPos = None
LF_GetSize = None
LF_GetBuffer = None
LF_Call = None
LF_SetOption = None

def _ensure_native_loaded():
    global LF_CreateData, LF_FreeData, LF_WriteBuffer, LF_ReadBuffer
    global LF_GetPos, LF_SetPos, LF_GetSize, LF_GetBuffer, LF_Call
    global LF_SetOption
    if LF_CreateData is not None:
        return
    from lingofuse._lf_native import (
        LF_CreateData as _CreateData,
        LF_FreeData as _FreeData,
        LF_WriteBuffer as _WriteBuffer,
        LF_ReadBuffer as _ReadBuffer,
        LF_GetPos as _GetPos,
        LF_SetPos as _SetPos,
        LF_GetSize as _GetSize,
        LF_GetBuffer as _GetBuffer,
        LF_Call as _Call,
        LF_SetOption as _SetOption,
    )
    LF_CreateData = _CreateData
    LF_FreeData = _FreeData
    LF_WriteBuffer = _WriteBuffer
    LF_ReadBuffer = _ReadBuffer
    LF_GetPos = _GetPos
    LF_SetPos = _SetPos
    LF_GetSize = _GetSize
    LF_GetBuffer = _GetBuffer
    LF_Call = _Call
    LF_SetOption = _SetOption

# ============================================================================
# Lazy-loaded language_middleware
# ============================================================================
LanguageMiddleware = None
LanguageConnectionError = None
LanguageCallError = None
set_debug_mode = None

def _ensure_language_middleware_loaded():
    """
    Import `language_middleware` and cache its public symbols.

    This function is idempotent. If the import fails, the global
    variables remain None; the caller is expected to check them and
    report a friendly error.
    """
    global LanguageMiddleware, LanguageConnectionError, LanguageCallError, set_debug_mode
    if LanguageMiddleware is not None:
        return
    try:
        from language_middleware import (
            LanguageMiddleware as _LM,
            LanguageConnectionError as _LCE,
            LanguageCallError as _LCalE,
            set_debug_mode as _sdm,
        )
        LanguageMiddleware = _LM
        LanguageConnectionError = _LCE
        LanguageCallError = _LCalE
        set_debug_mode = _sdm
    except Exception as e:
        # Do not raise. The caller checks for None and logs a friendly
        # error via log_error. We use stderr directly here to avoid
        # depending on _LOGGER, which may not yet be initialized.
        sys.stderr.write(
            f"[mcp_server] Failed to import language_middleware: {e}\n"
        )
        sys.stderr.flush()

# ============================================================================
# Global middleware instance
# ============================================================================
middleware = None

# ============================================================================
# DataHandle helpers
# ============================================================================
def _write_string(hnd, s: bytes):
    if len(s) > 0:
        LF_WriteBuffer(hnd, s, len(s))
    null = b'\x00'
    LF_WriteBuffer(hnd, null, 1)

def _read_string(hnd) -> bytes:
    """
    Read a UTF-8 string from a DataHandle.

    Behavior mirrors Pascal's LF_ReadString: if no null terminator is
    found, return the entire remaining buffer instead of empty bytes.
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
        data_len = end - pos
        if data_len == 0:
            LF_SetPos(hnd, end + 1)
            return b''
        raw = (ctypes.c_byte * data_len)()
        LF_ReadBuffer(hnd, raw, data_len)
        LF_SetPos(hnd, end + 1)
        return bytes(raw)
    else:
        data_len = size - pos
        if data_len == 0:
            return b''
        raw = (ctypes.c_byte * data_len)()
        LF_ReadBuffer(hnd, raw, data_len)
        LF_SetPos(hnd, size)
        return bytes(raw)

# ============================================================================
# Log functions
# ============================================================================
def _send_to_backend(msg: str):
    global middleware
    if middleware and middleware.is_connected():
        try:
            middleware.log(f"[MCP Server] {msg}")
        except Exception:
            pass

def log_info(msg):
    if _LOGGER:
        _LOGGER.info(msg)
    _send_to_backend(msg)

def log_error(msg):
    if _LOGGER:
        _LOGGER.error(msg)
    _send_to_backend(msg)

def log_debug(msg):
    if _LOGGER and DEBUG:
        _LOGGER.debug(msg)
    if DEBUG:
        _send_to_backend(msg)

def log_warning(msg):
    if _LOGGER:
        _LOGGER.warning(msg)
    _send_to_backend(msg)

# ============================================================================
# Tool invocation
# ============================================================================
def get_tools_from_middleware() -> List[Dict[str, Any]]:
    global middleware
    if middleware is None:
        raise RuntimeError("LanguageMiddleware not initialized")
    return middleware.get_tools()

async def call_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    global middleware
    if middleware is None:
        raise RuntimeError("LanguageMiddleware not initialized")

    agent_msg = f"[Agent] API call request: {tool_name} args={arguments}"
    if _LOGGER and DEBUG:
        _LOGGER.debug(agent_msg)
    if middleware and middleware.is_connected():
        try:
            middleware.log(agent_msg)
        except Exception:
            pass

    try:
        if not middleware._ensure_connected():
            raise LanguageConnectionError("Backend not connected")

        tool = middleware._tools.get(tool_name)
        if not tool:
            raise LanguageCallError(f"Tool '{tool_name}' not registered")

        target_app = tool['target_app']
        target_api = tool['target_api']

        payload = json.dumps(arguments, ensure_ascii=False).encode('utf-8')

        req = LF_CreateData(target_api.encode('utf-8'))
        if not req:
            raise RuntimeError("Failed to create request handle")
        _write_string(req, payload)

        resp = LF_Call(target_app.encode('utf-8'), req, middleware._timeout_ms)
        LF_FreeData(req)

        if not resp:
            raise LanguageCallError(
                f"LF_Call returned null handle for tool '{tool_name}'"
            )

        raw = _read_string(resp)
        LF_FreeData(resp)

        try:
            if raw:
                result = json.loads(raw.decode('utf-8'))
            else:
                result = None
        except Exception:
            result = raw

        log_debug(f"API call response: {tool_name} result={result}")
        return result
    except Exception as e:
        log_error(f"API call exception: {tool_name} error={e}")
        raise

# ============================================================================
# Helpers for dynamic tool registration
# ============================================================================
def _is_valid_py_identifier(name: str) -> bool:
    return (
        bool(name)
        and isinstance(name, str)
        and name.isidentifier()
        and not keyword.iskeyword(name)
    )

def _unique_py_identifier(preferred: str, used: set, fallback_prefix: str) -> str:
    if _is_valid_py_identifier(preferred) and preferred not in used:
        used.add(preferred)
        return preferred
    i = 0
    while True:
        candidate = f"{fallback_prefix}_{i}"
        if candidate not in used and _is_valid_py_identifier(candidate):
            used.add(candidate)
            return candidate
        i += 1

def _safe_docstring(desc: str) -> str:
    if not desc:
        return ""
    return desc.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')

def _json_type_to_python(json_type: str) -> str:
    """
    Map a JSON Schema type name to a Python type annotation.

    FastMCP introspects the Python function signature to build the JSON
    Schema it advertises to MCP clients. If a parameter has no
    annotation, the schema ends up without a "type" (or as an empty
    object), and some clients (e.g. LM Studio) send `{}` instead of a
    proper value. Adding `name: int` (etc.) to the generated signature
    fixes this.
    """
    return {
        "integer": "int",
        "number": "float",
        "string": "str",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
    }.get(json_type, "Any")

# ============================================================================
# Dynamic tool registration
# ============================================================================
def register_dynamic_tools(mcp: FastMCP, mw) -> None:
    tools = mw.get_tools()
    log_info(f"Registering {len(tools)} tools")
    tool_names = [t.get('name', '') for t in tools]
    log_debug(f"Tool names registered: {tool_names}")

    used_tool_names: set = set()

    for idx, tool_meta in enumerate(tools):
        raw_name = tool_meta["name"]
        desc = tool_meta.get("description", "")
        schema = tool_meta.get("parameters", {}) or {}
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        raw_param_names = list(props.keys())

        py_tool_name = _unique_py_identifier(
            raw_name, used_tool_names, fallback_prefix=f"tool_{idx}"
        )

        used_param_names: set = set()
        param_map: Dict[str, str] = {}
        for j, rp in enumerate(raw_param_names):
            py_param = _unique_py_identifier(
                rp, used_param_names, fallback_prefix=f"arg_{j}"
            )
            param_map[rp] = py_param

        # ----- Build the function signature WITH type annotations -----
        # Required parameters must come BEFORE optional ones (Python rule).
        required_parts: List[str] = []
        optional_parts: List[str] = []
        for rp in raw_param_names:
            py_param = param_map[rp]
            p_schema = props.get(rp, {}) or {}
            json_type = p_schema.get("type", "string")
            py_type = _json_type_to_python(json_type)

            if rp in required:
                required_parts.append(f"{py_param}: {py_type}")
            else:
                # Optional parameters default to None. FastMCP marks
                # them as not-required in the schema because of the
                # default value.
                optional_parts.append(f"{py_param}: {py_type} = None")
        params_str = ", ".join(required_parts + optional_parts)

        # ----- Build the body -----
        body_lines: List[str] = []
        if raw_param_names:
            args_pairs = ", ".join(
                f"{rp!r}: {param_map[rp]}" for rp in raw_param_names
            )
            body_lines.append(f"args = {{{args_pairs}}}")
            body_lines.append(f"return await call_tool({raw_name!r}, args)")
        else:
            body_lines.append(f"return await call_tool({raw_name!r}, {{}})")

        indented_body = "\n".join("    " + line for line in body_lines)

        safe_desc = _safe_docstring(desc)
        if safe_desc:
            func_code = (
                f"async def {py_tool_name}({params_str}) -> Any:\n"
                f"    \"\"\"{safe_desc}\"\"\"\n"
                f"{indented_body}\n"
            )
        else:
            func_code = (
                f"async def {py_tool_name}({params_str}) -> Any:\n"
                f"{indented_body}\n"
            )

        log_debug(f"Generated function source for '{raw_name}':\n{func_code}")

        namespace = {
            "call_tool": call_tool,
            "Any": Any,
            "__builtins__": __builtins__,
        }
        try:
            exec(func_code, namespace)
        except Exception as e:
            log_error(
                f"Failed to compile generated function for tool "
                f"'{raw_name}': {e}\n--- generated source ---\n{func_code}"
            )
            continue

        tool_func = namespace[py_tool_name]

        registered_name: Optional[str] = None

        try:
            mcp.tool(name=raw_name, description=desc)(tool_func)
            registered_name = raw_name
        except TypeError:
            try:
                mcp.tool()(tool_func)
                registered_name = py_tool_name

                if py_tool_name != raw_name:
                    log_warning(
                        f"Tool '{raw_name}' was registered under its Python "
                        f"name '{py_tool_name}' because FastMCP does not "
                        f"accept the name= keyword. MCP clients will see "
                        f"'{py_tool_name}' instead of '{raw_name}'."
                    )
                    if raw_name in mw._tools:
                        mw._tools[py_tool_name] = mw._tools[raw_name]
            except Exception as e:
                log_error(f"Failed to register tool '{raw_name}': {e}")
        except Exception as e:
            log_error(f"Failed to register tool '{raw_name}': {e}")

        if registered_name is not None:
            log_info(
                f"Registered tool: {raw_name} "
                f"(py={py_tool_name}, registered_as={registered_name}, "
                f"params={raw_param_names})"
            )

# ============================================================================
# FastMCP runner
# ============================================================================
def run_fastmcp(config: dict):
    """
    Initialize LingoFuse, register tools and run the FastMCP server.

    stdio transport runs this directly in the main process (no
    multiprocessing), which halves the startup time on Windows.
    http/sse still use a subprocess so the main process does not need
    to hold the LingoFuse native library open.
    """
    global ENDPOINT, TIMEOUT_MS, REG_AGENT_APP, TOOL_PROVIDER_APP
    global AGENT_MAIN_API, AGENT_LOG_API, TRANSPORT, HOST, PORT
    global LOG_FILE, DEBUG, SHOW_BANNER, middleware

    ENDPOINT = config['endpoint']
    TIMEOUT_MS = config['timeout']
    REG_AGENT_APP = config['reg_agent_app']
    TOOL_PROVIDER_APP = config['tool_provider_app']
    AGENT_MAIN_API = config['agent_main_api']
    AGENT_LOG_API = config['agent_log_api']
    TRANSPORT = config['transport']
    HOST = config['host']
    PORT = config['port']
    LOG_FILE = config['log_file']
    DEBUG = config['debug']
    SHOW_BANNER = config['show_banner']

    _init_logger()

    _ensure_native_loaded()

    # Suppress LingoFuse C-level console output in stdio mode BEFORE any
    # other LingoFuse API is used.
    if TRANSPORT == "stdio" and LF_SetOption is not None:
        try:
            LF_SetOption(b"ConsoleOutput", b"False")
            LF_SetOption(b"Quiet", b"True")
            log_info("stdio mode: LingoFuse console output suppressed "
                     "(ConsoleOutput=False, Quiet=True)")
        except Exception as e:
            log_warning(f"Failed to suppress LingoFuse console output: {e}")

    _ensure_language_middleware_loaded()

    if LanguageMiddleware is None or LanguageConnectionError is None or LanguageCallError is None:
        log_error(
            "Failed to load language_middleware (or its exception classes). "
            "Cannot start the MCP server."
        )
        return

    if DEBUG:
        set_debug_mode(True)

    log_info(
        f"Banner suppression: SHOW_BANNER={SHOW_BANNER}, "
        f"env FASTMCP_SHOW_SERVER_BANNER="
        f"{os.environ.get('FASTMCP_SHOW_SERVER_BANNER', '<unset>')}"
    )

    mw = LanguageMiddleware.get_instance(
        endpoint=ENDPOINT,
        timeout_ms=TIMEOUT_MS,
        reg_agent_app_name=REG_AGENT_APP,
        tool_provider_app=TOOL_PROVIDER_APP,
        agent_main_api=AGENT_MAIN_API,
        agent_log_api=AGENT_LOG_API
    )
    mw._ensure_connected()
    middleware = mw

    mcp = FastMCP(
        name="BackendGateway",
        instructions="Dynamically registered backend tools"
    )
    register_dynamic_tools(mcp, mw)

    try:
        if TRANSPORT == "stdio":
            log_info("Starting stdio server")
            mcp.run(transport="stdio", show_banner=SHOW_BANNER)
        elif TRANSPORT == "http":
            log_info(f"Starting Streamable HTTP server on http://{HOST}:{PORT}")
            mcp.run(transport="http", host=HOST, port=PORT, show_banner=SHOW_BANNER)
        else:
            log_warning("SSE transport is deprecated. Please migrate to 'http' (Streamable HTTP).")
            log_info(f"Starting SSE server (deprecated) on http://{HOST}:{PORT}")
            mcp.run(transport="sse", host=HOST, port=PORT, show_banner=SHOW_BANNER)
    except KeyboardInterrupt:
        log_info("FastMCP received KeyboardInterrupt, exiting gracefully")
    except asyncio.CancelledError:
        log_info("FastMCP received CancelledError, exiting gracefully")
    except Exception as e:
        log_error(f"FastMCP runtime exception: {e}")
        traceback.print_exc(file=sys.stderr)
    finally:
        mw.shutdown()
        log_info("FastMCP exiting")

# ============================================================================
# Signal handler
#
# We convert both SIGINT and SIGTERM into KeyboardInterrupt so that the
# main() dispatcher can use a single, well-tested cleanup path:
#   * stdio mode:   KeyboardInterrupt unwinds through the mcp.run() call
#                   and triggers the `finally` block inside run_fastmcp.
#   * http/sse:     KeyboardInterrupt interrupts mcp_process.join(),
#                   the `except KeyboardInterrupt` block runs, and the
#                   subprocess is terminated or killed.
#
# Using sys.exit(0) here would raise SystemExit instead, which is NOT
# caught by `except KeyboardInterrupt` and would leave the subprocess
# orphaned in http/sse mode.
# ============================================================================
def signal_handler(sig, frame):
    log_info(f"Received signal {sig}, shutting down...")
    raise KeyboardInterrupt()

# ============================================================================
# Argument parsing
# ============================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="MCP Server for LingoFuse backend",
        epilog="""
Environment variables (read once at startup):
  LINGOFUSE_ENDPOINT              - Default endpoint (default: {})
  LINGOFUSE_TIMEOUT_MS            - Default timeout in ms (default: {})
  MCP_TRANSPORT                   - Transport: stdio, http, or sse (default: {})
  MCP_HOST                        - Host for HTTP transports (default: {})
  MCP_PORT                        - Port for HTTP transports (default: {})
  MCP_LOG_FILE                    - Log file path
  MCP_DEBUG                       - Enable debug mode (default: {})
  MCP_SHOW_BANNER                 - Show FastMCP banner (default: {})
  MCP_PROXY_PATH                  - Path to mcp_proxy (auto-detected if empty)
        """.format(
            DEFAULT_ENDPOINT, DEFAULT_TIMEOUT_MS,
            DEFAULT_TRANSPORT, DEFAULT_HOST, DEFAULT_PORT,
            DEFAULT_DEBUG, DEFAULT_SHOW_BANNER
        )
    )
    parser.add_argument(
        "--transport", "-t",
        choices=["stdio", "http", "sse"],
        default=os.environ.get("MCP_TRANSPORT", DEFAULT_TRANSPORT),
        help="Transport protocol: stdio (default), http (recommended), or sse (deprecated)"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", DEFAULT_HOST),
        help="Host to bind for HTTP transports (default: {})".format(DEFAULT_HOST)
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=int(os.environ.get("MCP_PORT", str(DEFAULT_PORT))),
        help="Port to bind for HTTP transports (default: {})".format(DEFAULT_PORT)
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("LINGOFUSE_ENDPOINT", DEFAULT_ENDPOINT),
        help="LingoFuse endpoint to connect to (default: {})".format(DEFAULT_ENDPOINT)
    )
    parser.add_argument(
        "--timeout", "-T",
        type=int,
        default=int(os.environ.get("LINGOFUSE_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS))),
        help="Call timeout in milliseconds (default: {})".format(DEFAULT_TIMEOUT_MS)
    )
    parser.add_argument(
        "--reg-agent-app",
        default=os.environ.get("LINGOFUSE_REG_AGENT_APP", DEFAULT_REG_AGENT_APP),
        help="Registration agent application name (default: {})".format(DEFAULT_REG_AGENT_APP)
    )
    parser.add_argument(
        "--tool-provider-app",
        default=os.environ.get("LINGOFUSE_TOOL_PROVIDER_APP", DEFAULT_TOOL_PROVIDER_APP),
        help="Tool provider application name (default: {})".format(DEFAULT_TOOL_PROVIDER_APP)
    )
    parser.add_argument(
        "--agent-main-api",
        default=os.environ.get("LINGOFUSE_AGENT_MAIN_API", DEFAULT_AGENT_MAIN_API),
        help="API name for agent_main (default: {})".format(DEFAULT_AGENT_MAIN_API)
    )
    parser.add_argument(
        "--agent-log-api",
        default=os.environ.get("LINGOFUSE_AGENT_LOG_API", DEFAULT_AGENT_LOG_API),
        help="API name for agent_log (default: {})".format(DEFAULT_AGENT_LOG_API)
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.environ.get("MCP_DEBUG", str(DEFAULT_DEBUG)).lower() in ("1", "true", "yes"),
        help="Enable debug mode (default: {})".format(DEFAULT_DEBUG)
    )
    parser.add_argument(
        "--generate-configs",
        action="store_true",
        help="Generate MCP client configuration files and exit"
    )
    parser.add_argument(
        "--output-dir",
        default="./mcp_configs",
        help="Output directory for generated configs (default: ./mcp_configs)"
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("MCP_LOG_FILE", DEFAULT_LOG_FILE),
        help="Path to file log (if not specified, file logging is disabled)"
    )
    parser.add_argument(
        "--show-banner",
        action="store_true",
        default=os.environ.get("MCP_SHOW_BANNER", str(DEFAULT_SHOW_BANNER)).lower() in ("1", "true", "yes"),
        help="Show FastMCP startup banner (default: {})".format(DEFAULT_SHOW_BANNER)
    )
    parser.add_argument(
        "--proxy-path",
        default=os.environ.get("MCP_PROXY_PATH", DEFAULT_PROXY_PATH),
        help="Explicit path to mcp_proxy (script or exe). "
             "If not specified, the generator auto-detects it next to mcp_server "
             "(mcp_proxy.py in script mode, mcp_proxy.exe in frozen mode)."
    )
    return parser.parse_args()

# ============================================================================
# Main entry point
# ============================================================================
def main():
    global ENDPOINT, TIMEOUT_MS, REG_AGENT_APP, TOOL_PROVIDER_APP
    global AGENT_MAIN_API, AGENT_LOG_API, TRANSPORT, HOST, PORT
    global LOG_FILE, DEBUG, SHOW_BANNER, PROXY_PATH

    args = parse_args()

    ENDPOINT = args.endpoint
    TIMEOUT_MS = args.timeout
    REG_AGENT_APP = args.reg_agent_app
    TOOL_PROVIDER_APP = args.tool_provider_app
    AGENT_MAIN_API = args.agent_main_api
    AGENT_LOG_API = args.agent_log_api
    TRANSPORT = args.transport
    HOST = args.host
    PORT = args.port
    LOG_FILE = args.log_file
    DEBUG = args.debug
    SHOW_BANNER = args.show_banner
    PROXY_PATH = args.proxy_path

    _init_logger()

    server_path = get_server_script_path()
    frozen = is_frozen_exe()

    if args.generate_configs:
        if not _HAS_GENERATOR:
            print("[ERROR] generate_agent_json module not found.", file=sys.stderr)
            sys.exit(1)

        proxy_path = PROXY_PATH
        if not proxy_path:
            proxy_path = get_default_proxy_path()
            if proxy_path:
                log_info(f"Auto-detected mcp_proxy: {proxy_path}")
            else:
                expected = "mcp_proxy.exe" if frozen else "mcp_proxy.py"
                log_warning(
                    f"mcp_proxy not found next to mcp_server "
                    f"(expected '{expected}' in '{_server_dir()}'). "
                    "Proxy stdio configs will not be generated. "
                    "Use --proxy-path to specify it explicitly."
                )
        else:
            log_info(f"Using mcp_proxy from --proxy-path: {proxy_path}")

        generate_configs(
            server_script_path=server_path,
            endpoint=ENDPOINT,
            timeout_ms=TIMEOUT_MS,
            reg_agent_app=REG_AGENT_APP,
            tool_provider_app=TOOL_PROVIDER_APP,
            agent_main_api=AGENT_MAIN_API,
            agent_log_api=AGENT_LOG_API,
            debug=DEBUG,
            host=HOST,
            port=PORT,
            output_dir=args.output_dir,
            python_exe=sys.executable,
            is_exe=frozen,
            proxy_path=proxy_path,
        )
        sys.exit(0)

    log_info(f"Starting MCP server with transport={TRANSPORT}")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    config = {
        'endpoint': ENDPOINT,
        'timeout': TIMEOUT_MS,
        'reg_agent_app': REG_AGENT_APP,
        'tool_provider_app': TOOL_PROVIDER_APP,
        'agent_main_api': AGENT_MAIN_API,
        'agent_log_api': AGENT_LOG_API,
        'transport': TRANSPORT,
        'host': HOST,
        'port': PORT,
        'log_file': LOG_FILE,
        'debug': DEBUG,
        'show_banner': SHOW_BANNER,
    }

    # ---------------------------------------------------------------------
    # Dispatch:
    #   * stdio  -> run in the main process (no subprocess). On Windows,
    #               multiprocessing spawns a new interpreter, re-imports
    #               the LingoFuse native library and re-connects to the
    #               backend, doubling startup time and blowing past the
    #               MCP client's initialize timeout. Running in the main
    #               process keeps startup at ~4-5 seconds.
    #   * http/sse -> run in a subprocess, so the main process does not
    #               hold the LingoFuse native library open.
    # ---------------------------------------------------------------------
    if TRANSPORT == "stdio":
        log_info("stdio mode: running FastMCP in the main process")
        run_fastmcp(config)
    else:
        log_info("Starting FastMCP subprocess...")
        mcp_process = multiprocessing.Process(
            target=run_fastmcp,
            args=(config,),
            daemon=False
        )
        mcp_process.start()
        log_info(f"FastMCP subprocess PID={mcp_process.pid}")

        try:
            mcp_process.join()
        except KeyboardInterrupt:
            log_info("Main process received KeyboardInterrupt, shutting down...")
            if mcp_process.is_alive():
                mcp_process.terminate()
                mcp_process.join(timeout=5)
                if mcp_process.is_alive():
                    mcp_process.kill()
                    mcp_process.join()
        finally:
            log_info("Main process stopped")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()