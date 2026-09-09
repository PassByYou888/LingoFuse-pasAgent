#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py - MCP Server for LingoFuse Backend (v2.28)

DESCRIPTION
    This script implements a Model Context Protocol (MCP) server that acts as a
    gateway between MCP clients (e.g., LM Studio, Claude Desktop) and a
    LingoFuse backend. It dynamically exposes tools registered in the backend
    as MCP tools.

    The server supports three transport modes:
      - stdio : Standard input/output (default) – used for integration with
                local MCP clients like LM Studio.
      - http  : Streamable HTTP (official MCP recommendation) – exposes an HTTP
                endpoint for remote or web-based clients. This is the preferred
                HTTP transport for new deployments.
      - sse   : Server-Sent Events (deprecated) – legacy HTTP transport.
                Still supported but not recommended for new projects.

    The connection to the LingoFuse backend is lazy: the server starts even if
    the backend is unavailable, and will retry automatically on the first tool
    call. This allows the backend to be started later without restarting the
    MCP server.

    All runtime status messages are sent to the backend via `agent_log` with
    appropriate prefixes (`[MCP Server]` for general status, `[Agent]` for tool
    calls). File logging is disabled by default; use `--log-file` to enable it.

    Tool calls now serialize arguments with `ensure_ascii=False` to preserve
    Unicode characters in the JSON payload sent to the backend.

    Console output encoding is forced to UTF-8 on Windows, and all ANSI color
    codes are suppressed to prevent garbled text in PowerShell/cmd.

AUTO-GENERATE CONFIGURATIONS
    Set the global constant `AUTO_GENERATE_CONFIGS` to `True` (see "GLOBAL
    DEFAULTS" section) to automatically generate MCP client configuration files
    (JSON) and Markdown documentation for all supported agents (LM Studio,
    Claude Desktop, Continue.dev, Generic) each time the server starts.
    The files are written to the directory specified by `--output-dir` (default
    `./mcp_configs`) and cover stdio, HTTP (recommended), and legacy SSE transports.

DYNAMIC REFRESH (built-in)
    Auto‑refresh is enabled by default (cannot be disabled). The server polls
    the backend every `--refresh-interval` seconds (default 15) and, if a change
    is detected, restarts the MCP service process. This ensures the tool list
    stays up‑to‑date without manual restart.

    IMPORTANT: For `stdio` transport, restarting will disconnect the client.
    This feature is most useful with `http` or `sse` transports.

    When a change is detected and the server restarts, MCP clients may cache
    the old tool list. You may need to refresh or reconnect your client
    (e.g., restart LM Studio or reload the HTTP session) to see the updated list.

USAGE EXAMPLES
    # Start with default settings (stdio transport, IPC endpoint)
    python mcp_server.py

    # Start with Streamable HTTP transport on port 8080
    python mcp_server.py --transport http --port 8080

    # Enable file logging
    python mcp_server.py --log-file ./mcp_server.log

    # Legacy SSE (deprecated)
    python mcp_server.py --transport sse --port 8080

    # Use a different LingoFuse endpoint and increase timeout
    python mcp_server.py --endpoint tcp://127.0.0.1:9897 --timeout 10000

    # Override backend application names
    python mcp_server.py --tool-provider-app my_custom_provider --agent-main-api get_tools

    # Enable debug logging (already on by default)
    python mcp_server.py --debug

    # Generate configuration files (manual) and exit
    python mcp_server.py --generate-configs --output-dir ./my_configs

    # Change refresh interval (auto‑refresh is always on)
    python mcp_server.py --refresh-interval 10

COMMAND-LINE ARGUMENTS (all optional)
    --transport, -t      Transport protocol: 'stdio', 'http', or 'sse' (default: stdio)
                         'http' is the recommended Streamable HTTP; 'sse' is deprecated.
    --host               Host to bind for HTTP transports (default: 0.0.0.0)
    --port, -p           Port to bind for HTTP transports (default: 8000)

    --endpoint           LingoFuse endpoint to connect to (default: ipc:agent)
    --timeout, -T        Call timeout in milliseconds (default: 5000)
    --reg-agent-app      Application name used by this client (default: reg_agent)
    --tool-provider-app  Backend application that provides tools (default: agent_main_app)
    --agent-main-api     API name to fetch the tool list (default: agent_main)
    --agent-log-api      API name to send logs (default: agent_log)
    --debug              Enable verbose debug output (also enables debug logs to backend)

    --generate-configs   Generate MCP client configuration files and exit
    --output-dir         Output directory for generated configs (default: ./mcp_configs)

    --log-file           Path to file log (if not specified, file logging is disabled)

    --refresh-interval   Refresh interval in seconds (default: 15)
    --show-banner        Show FastMCP startup banner (default: False)

ENVIRONMENT VARIABLES (override defaults)
    LINGOFUSE_ENDPOINT              (same as --endpoint)
    LINGOFUSE_TIMEOUT_MS            (same as --timeout)
    LINGOFUSE_REG_AGENT_APP         (same as --reg-agent-app)
    LINGOFUSE_TOOL_PROVIDER_APP     (same as --tool-provider-app)
    LINGOFUSE_AGENT_MAIN_API        (same as --agent-main-api)
    LINGOFUSE_AGENT_LOG_API         (same as --agent-log-api)
    MCP_TRANSPORT                   (same as --transport)
    MCP_HOST                        (same as --host)
    MCP_PORT                        (same as --port)
    MCP_LOG_FILE                    Log file path (only used if --log-file is also given)
    MCP_REFRESH_INTERVAL           Refresh interval in seconds

NOTES
    - Auto‑refresh is **always enabled** and cannot be turned off.
    - The server registers tools by calling `agent_main` on the backend.
      The backend must respond with a JSON object containing a "tools" array.
    - Each tool definition must include: name, description, target_app,
      target_api, and parameters (JSON Schema).
    - In HTTP mode, the server listens on `/mcp` by default (FastMCP standard).
    - Log messages are sent to the backend via the `agent_log` API (if connected)
      and optionally to a local file if `--log-file` is provided.
    - The configuration generator requires `generate_agent_json.py` in the
      same directory or in PYTHONPATH.

DEPENDENCIES
    - fastmcp (>= 0.2.0) and pydantic
    - lingofuse package (must be installed or in PYTHONPATH)

AUTHOR
    PassByYou888 / LingoFuse Team
"""

# ============================================================================
# GLOBAL DEFAULTS – change these to modify default startup behavior
# ============================================================================
DEFAULT_ENDPOINT = "ipc:agent"
DEFAULT_TIMEOUT_MS = 5000
DEFAULT_REG_AGENT_APP = "reg_agent"
DEFAULT_TOOL_PROVIDER_APP = "agent_main_app"
DEFAULT_AGENT_MAIN_API = "agent_main"
DEFAULT_AGENT_LOG_API = "agent_log"
DEFAULT_TRANSPORT = "stdio"          # 'stdio', 'http', or 'sse'
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_LOG_FILE = None              # File logging disabled by default
DEFAULT_DEBUG = False                # Enable debug logging by default
DEFAULT_REFRESH_INTERVAL = 10        # seconds
DEFAULT_SHOW_BANNER = False          # suppress FastMCP startup banner by default

# Auto-generate configuration files on startup (set to True to enable)
AUTO_GENERATE_CONFIGS = False
# ============================================================================

import asyncio
import sys
import os
import logging
import traceback
import argparse
import json
import ctypes
import time
import threading
import multiprocessing
import signal
from typing import Dict, Any, List, Optional

# ============================================================================
# Fix console encoding and disable ANSI colors on Windows
# ============================================================================
def _setup_console():
    """Configure console for UTF-8 output and disable ANSI color codes."""
    if sys.platform == "win32":
        # Force UTF-8 for stdout/stderr
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            # Python < 3.7 fallback
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        # Enable virtual terminal processing (ANSI colors) if possible
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 0x0007)
        except Exception:
            pass
        # Set environment variables to disable colors in logs
        os.environ["UVICORN_LOGGING_COLOR"] = "0"
        os.environ["FORCE_COLOR"] = "0"
        os.environ["NO_COLOR"] = "1"
        os.environ["PYTHONIOENCODING"] = "utf-8"
    else:
        # For non-Windows, ensure UTF-8
        os.environ["PYTHONIOENCODING"] = "utf-8"

_setup_console()

# ============================================================================
# Suppress FastMCP startup banner via environment variable (default quiet)
# ============================================================================
os.environ["FASTMCP_QUIET"] = "1"    # will be overridden if banner is requested
os.environ["MCP_LOGGING"] = "ERROR"

# ============================================================================
# Detect if running as a frozen executable (PyInstaller / Nuitka)
# ============================================================================
def is_frozen_exe() -> bool:
    """
    Return True if the application is packaged as a standalone executable
    (e.g., PyInstaller one-file mode). In such environments, sys.executable
    points to the .exe, while __file__ is a temporary .py script path.
    """
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')

def get_server_script_path() -> str:
    """
    Return the appropriate path to be used as the server command in generated
    configs. When running as a frozen executable, use sys.executable (the .exe),
    otherwise use the current script's __file__.
    """
    if is_frozen_exe():
        return sys.executable
    else:
        return os.path.abspath(__file__)

# ============================================================================
# Import generate_agent_json module (optional)
# ============================================================================
try:
    from generate_agent_json import generate_configs
    _HAS_GENERATOR = True
except ImportError:
    _HAS_GENERATOR = False
    generate_configs = None

# ============================================================================
# Logging configuration (controlled by environment variables and --log-file)
# ============================================================================
_LOG_FILE = None   # will be set from args
_LOGGER = None
_DEBUG = False

def _init_logger(log_file_path: Optional[str], debug: bool = False):
    """
    Initialize the file logger. If log_file_path is None, file logging is disabled.
    """
    global _LOGGER, _LOG_FILE, _DEBUG
    _LOG_FILE = log_file_path
    _DEBUG = debug

    _LOGGER = logging.getLogger("mcp_server")
    # Remove any existing handlers to avoid duplicates
    _LOGGER.handlers.clear()
    if _LOG_FILE:
        # Ensure the directory exists
        log_dir = os.path.dirname(_LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        _LOGGER.setLevel(logging.DEBUG if debug else logging.INFO)
        handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _LOGGER.addHandler(handler)
        _LOGGER.propagate = False
        _LOGGER.info(f"Log file enabled: {_LOG_FILE}")
    else:
        # Null handler to suppress "No handlers could be found" warning
        _LOGGER.addHandler(logging.NullHandler())
        _LOGGER.propagate = False

# ============================================================================
# Import other modules
# ============================================================================
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

try:
    from language_middleware import (
        LanguageMiddleware, LanguageConnectionError,
        set_debug_mode, get_logs, clear_logs, DEBUG_MODE
    )
except ImportError as e:
    if _LOGGER:
        _LOGGER.error(f"Failed to import language_middleware: {e}")
    print(f"[FATAL] Failed to import language_middleware: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from fastmcp import FastMCP
except ImportError as e:
    if _LOGGER:
        _LOGGER.error(f"fastmcp not installed: {e}")
    print(f"[FATAL] fastmcp not installed: {e}", file=sys.stderr)
    print("[FATAL] Please run: pip install fastmcp pydantic", file=sys.stderr)
    sys.exit(1)

# ============================================================================
# LingoFuse native functions and helpers
# ============================================================================
from lingofuse._lf_native import (
    DataHnd,
    LF_CreateData,
    LF_FreeData,
    LF_WriteBuffer,
    LF_ReadBuffer,
    LF_GetPos,
    LF_SetPos,
    LF_GetSize,
    LF_GetBuffer,
    LF_Call,
    LF_FreeData,
)

def _write_string(hnd: DataHnd, s: bytes):
    """Write bytes to a DataHandle with a null terminator."""
    if len(s) > 0:
        LF_WriteBuffer(hnd, s, len(s))
    null = b'\x00'
    LF_WriteBuffer(hnd, null, 1)

def _read_string(hnd: DataHnd) -> bytes:
    """
    Read a null-terminated UTF-8 string from a DataHandle.
    If no null is found, returns empty bytes (fault-tolerant).
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
    if end == size:
        return b''
    data_len = end - pos
    if data_len == 0:
        LF_SetPos(hnd, end + 1)
        return b''
    raw = (ctypes.c_byte * data_len)()
    LF_ReadBuffer(hnd, raw, data_len)
    LF_SetPos(hnd, end + 1)
    return bytes(raw)

# ============================================================================
# Global middleware instance (used by log functions)
# ============================================================================
middleware: Optional[LanguageMiddleware] = None

# ============================================================================
# Log functions (file + backend sync)
# ============================================================================
def _send_to_backend(level: str, msg: str):
    """Send a log message to the backend via agent_log, with a consistent prefix."""
    global middleware
    prefix = "[MCP Server]"
    full_msg = f"{prefix} {msg}"
    if middleware and middleware.is_connected():
        try:
            middleware.log(full_msg)
        except Exception:
            pass

def log_info(msg):
    if _LOGGER:
        _LOGGER.info(msg)
    _send_to_backend("INFO", msg)

def log_error(msg):
    if _LOGGER:
        _LOGGER.error(msg)
    _send_to_backend("ERROR", msg)

def log_debug(msg):
    if _LOGGER and _DEBUG:
        _LOGGER.debug(msg)
    if _DEBUG:
        _send_to_backend("DEBUG", msg)

def log_warning(msg):
    if _LOGGER:
        _LOGGER.warning(msg)
    _send_to_backend("WARNING", msg)

# ============================================================================
# Core tool calling (direct LingoFuse calls with ensure_ascii=False)
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

    # Log to backend with [Agent] prefix
    agent_msg = f"[Agent] API call request: {tool_name} args={arguments}"
    if _LOGGER and _DEBUG:
        _LOGGER.debug(agent_msg)
    if middleware and middleware.is_connected():
        try:
            middleware.log(agent_msg)
        except Exception:
            pass

    try:
        if not middleware._ensure_connected():
            raise ConnectionError("Backend not connected")

        tool = middleware._tools.get(tool_name)
        if not tool:
            raise LanguageMiddleware.LanguageCallError(f"Tool '{tool_name}' not registered")

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
            raise LanguageMiddleware.LanguageCallError(f"LF_Call returned null handle for tool '{tool_name}'")

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
# Tool registration (following FastMCP official specification)
# ============================================================================
def register_dynamic_tools(mcp: FastMCP):
    tools = get_tools_from_middleware()
    log_info(f"Registering {len(tools)} tools")
    # Log the names of all tools being registered (for debugging)
    tool_names = [t.get('name', '') for t in tools]
    log_debug(f"Tool names registered: {tool_names}")

    for tool_meta in tools:
        name = tool_meta["name"]
        desc = tool_meta.get("description", "")
        schema = tool_meta.get("parameters", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])
        param_names = list(props.keys())

        param_parts = []
        for p in param_names:
            p_schema = props.get(p, {})
            p_type = p_schema.get("type", "string")
            type_map = {
                "integer": "int",
                "number": "float",
                "string": "str",
                "boolean": "bool",
                "array": "list",
                "object": "dict"
            }
            py_type = type_map.get(p_type, "Any")
            is_required = p in required
            if is_required:
                param_parts.append(f"{p}: {py_type}")
            else:
                default = p_schema.get("default")
                if default is not None:
                    param_parts.append(f"{p}: {py_type} = {repr(default)}")
                else:
                    param_parts.append(f"{p}: {py_type} | None = None")

        params_str = ", ".join(param_parts) if param_parts else ""

        if param_names:
            collect_args = "args = {" + ", ".join([f"'{p}': {p}" for p in param_names]) + "}"
            func_code = f"""
async def {name}({params_str}) -> Any:
    \"\"\"{desc}\"\"\"
    {collect_args}
    return await call_tool('{name}', args)
"""
        else:
            func_code = f"""
async def {name}() -> Any:
    \"\"\"{desc}\"\"\"
    return await call_tool('{name}', {{}})
"""

        namespace = {
            "call_tool": call_tool,
            "Any": Any,
            "__builtins__": __builtins__
        }
        exec(func_code, namespace)
        tool_func = namespace[name]

        mcp.tool()(tool_func)
        log_info(f"Registered tool: {name} parameters: {param_names}")

# ============================================================================
# FastMCP runner function (to be executed in a subprocess)
# ============================================================================
def run_fastmcp(args: argparse.Namespace, show_banner: bool):
    """
    Create a FastMCP instance, register tools, and run it with the given transport.
    This function is designed to run in a separate process.
    """
    # Re-initialize logger for the subprocess (file log will be shared)
    _init_logger(args.log_file, args.debug)
    # Create a new middleware instance for this subprocess
    mw = LanguageMiddleware.get_instance(
        endpoint=args.endpoint,
        timeout_ms=args.timeout,
        reg_agent_app_name=args.reg_agent_app,
        tool_provider_app=args.tool_provider_app,
        agent_main_api=args.agent_main_api,
        agent_log_api=args.agent_log_api
    )
    # Ensure connection (lazy)
    mw._ensure_connected()
    # Register the middleware globally for log functions
    global middleware
    middleware = mw

    # Create FastMCP instance
    mcp = FastMCP(
        name="BackendGateway",
        instructions="Dynamically registered backend tools"
    )
    # Register tools
    register_dynamic_tools(mcp)

    # Run the server - capture KeyboardInterrupt and CancelledError gracefully
    try:
        if args.transport == "stdio":
            log_info("Starting stdio server")
            mcp.run(transport="stdio", show_banner=show_banner)
        elif args.transport == "http":
            log_info(f"Starting Streamable HTTP server on http://{args.host}:{args.port}")
            mcp.run(transport="http", host=args.host, port=args.port, show_banner=show_banner)
        else:  # sse (deprecated)
            log_warning("SSE transport is deprecated. Please migrate to 'http' (Streamable HTTP).")
            log_info(f"Starting SSE server (deprecated) on http://{args.host}:{args.port}")
            mcp.run(transport="sse", host=args.host, port=args.port, show_banner=show_banner)
    except KeyboardInterrupt:
        # This is expected when the parent terminates the process
        log_info("FastMCP subprocess received KeyboardInterrupt, exiting gracefully")
    except asyncio.CancelledError:
        log_info("FastMCP subprocess received CancelledError, exiting gracefully")
    except Exception as e:
        log_error(f"FastMCP runtime exception: {e}")
        traceback.print_exc(file=sys.stderr)
    finally:
        # Clean up middleware
        mw.shutdown()
        log_info("FastMCP subprocess exiting")

# ============================================================================
# Server lifecycle and refresh monitor
# ============================================================================
def tools_are_different(old: List[Dict], new: List[Dict]) -> bool:
    """Compare two tool lists by sorting and JSON serializing."""
    def key_func(t):
        return t.get('name', '')
    old_sorted = sorted(old, key=key_func)
    new_sorted = sorted(new, key=key_func)
    old_json = json.dumps(old_sorted, sort_keys=True, ensure_ascii=False)
    new_json = json.dumps(new_sorted, sort_keys=True, ensure_ascii=False)
    return old_json != new_json

def refresh_monitor(interval: int, args: argparse.Namespace):
    """
    Background thread function: periodically fetch tools from the backend
    and compare. If a change is detected, signal the main process to restart
    the MCP server.

    CRITICAL: This function calls _fetch_tools_from_backend() on each iteration
    to ensure it sees tools added via register_agent (which runs in the
    FastMCP subprocess with its own middleware instance).
    """
    global middleware
    log_info(f"Refresh monitor started (interval={interval}s)")
    last_tools = []
    first_run = True

    while True:
        try:
            time.sleep(interval)

            if middleware is None:
                log_warning("Refresh monitor: middleware not initialized, skipping")
                continue

            # Ensure connection to backend
            if not middleware._ensure_connected():
                log_warning("Refresh monitor: backend not connected, skipping refresh")
                continue

            # CRITICAL FIX: Force refresh from backend to pick up tools added
            # via register_agent (which runs in the FastMCP subprocess).
            # _fetch_tools_from_backend() updates middleware._tools internally.
            log_debug("Refresh monitor: calling _fetch_tools_from_backend() to refresh from backend")
            middleware._fetch_tools_from_backend()

            # Now get the refreshed tool list
            new_tools = middleware.get_tools()

            if first_run:
                last_tools = new_tools
                first_run = False
                log_info(f"Refresh monitor: initial tool list fetched ({len(new_tools)} tools)")
                if _DEBUG:
                    names = [t.get('name', '') for t in new_tools]
                    log_debug(f"Initial tools: {names}")
                continue

            # Log current tool names for debugging
            current_names = [t.get('name', '') for t in new_tools]
            log_debug(f"Refresh monitor: current tool names: {current_names}")

            if tools_are_different(last_tools, new_tools):
                # Determine added and removed tools
                old_names = set(t.get('name', '') for t in last_tools)
                new_names = set(t.get('name', '') for t in new_tools)
                added = new_names - old_names
                removed = old_names - new_names
                log_info(f"Tool list changed (old={len(last_tools)}, new={len(new_tools)}) – triggering restart")
                if added:
                    log_info(f"Added tools: {list(added)}")
                if removed:
                    log_info(f"Removed tools: {list(removed)}")
                last_tools = new_tools
                global _need_restart
                _need_restart = True
                # After restart, client may need to refresh its cache
                log_info("Server restart triggered. MCP clients may need to reconnect or refresh their tool list.")
            else:
                log_debug("Refresh monitor: no change detected")

        except Exception as e:
            log_error(f"Refresh monitor error: {e}")
            # Continue running after error

# Global flag for restart signal
_need_restart = False

# ============================================================================
# Signal handlers for clean shutdown
# ============================================================================
def shutdown_server():
    global running
    log_info("Shutting down server...")
    running = False
    if middleware:
        middleware.shutdown()
    log_info("Server stopped")
    sys.exit(0)

def signal_handler(sig, frame):
    log_info(f"Received signal {sig}, shutting down...")
    shutdown_server()

# ============================================================================
# Main entry point
# ============================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="MCP Server for LingoFuse backend",
        epilog="""
Environment variables:
  LINGOFUSE_ENDPOINT              - Default endpoint (default: {})
  LINGOFUSE_TIMEOUT_MS            - Default timeout in ms (default: {})
  MCP_TRANSPORT                   - Transport: stdio, http, or sse (default: {})
  MCP_HOST                        - Host for HTTP transports (default: {})
  MCP_PORT                        - Port for HTTP transports (default: {})
  MCP_LOG_FILE                    - Log file path (only used if --log-file is given)
  MCP_REFRESH_INTERVAL           - Refresh interval in seconds
        """.format(
            DEFAULT_ENDPOINT, DEFAULT_TIMEOUT_MS,
            DEFAULT_TRANSPORT, DEFAULT_HOST, DEFAULT_PORT
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
        help="Enable debug mode (more verbose logs) (default: {})".format(DEFAULT_DEBUG)
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
        default=os.environ.get("MCP_LOG_FILE"),
        help="Path to file log (if not specified, file logging is disabled)"
    )

    parser.add_argument(
        "--refresh-interval",
        type=int,
        default=int(os.environ.get("MCP_REFRESH_INTERVAL", str(DEFAULT_REFRESH_INTERVAL))),
        help="Refresh interval in seconds (default: {})".format(DEFAULT_REFRESH_INTERVAL)
    )

    parser.add_argument(
        "--show-banner",
        action="store_true",
        default=os.environ.get("MCP_SHOW_BANNER", "0").lower() in ("1", "true", "yes"),
        help="Show FastMCP startup banner (default: False)"
    )

    return parser.parse_args()

def main():
    global middleware, mcp_app, running, _need_restart

    args = parse_args()

    _init_logger(args.log_file, args.debug)

    server_path = get_server_script_path()
    frozen = is_frozen_exe()

    if args.generate_configs:
        if not _HAS_GENERATOR:
            print("[ERROR] generate_agent_json module not found. Ensure it is in the same directory or PYTHONPATH.", file=sys.stderr)
            sys.exit(1)
        generate_configs(
            server_script_path=server_path,
            endpoint=args.endpoint,
            timeout_ms=args.timeout,
            reg_agent_app=args.reg_agent_app,
            tool_provider_app=args.tool_provider_app,
            agent_main_api=args.agent_main_api,
            agent_log_api=args.agent_log_api,
            debug=args.debug,
            host=args.host,
            port=args.port,
            output_dir=args.output_dir,
            python_exe=sys.executable,
            is_exe=frozen,
        )
        sys.exit(0)

    if args.debug:
        set_debug_mode(True)
        log_info("Debug mode enabled")

    log_info(f"Starting MCP server with transport={args.transport}")

    # Initialize middleware (main process)
    try:
        middleware = LanguageMiddleware.get_instance(
            endpoint=args.endpoint,
            timeout_ms=args.timeout,
            reg_agent_app_name=args.reg_agent_app,
            tool_provider_app=args.tool_provider_app,
            agent_main_api=args.agent_main_api,
            agent_log_api=args.agent_log_api
        )
        if not middleware._ensure_connected():
            log_info("Backend not connected – will retry on first tool call")
        else:
            log_info("LanguageMiddleware initialized and connected")
    except Exception as e:
        log_error(f"Failed to initialize LanguageMiddleware: {e}")
        if middleware is None:
            sys.exit(1)

    # Generate configs if auto-generate is enabled
    if AUTO_GENERATE_CONFIGS:
        if _HAS_GENERATOR:
            try:
                log_info("Auto-generating MCP client configurations...")
                generate_configs(
                    server_script_path=server_path,
                    endpoint=args.endpoint,
                    timeout_ms=args.timeout,
                    reg_agent_app=args.reg_agent_app,
                    tool_provider_app=args.tool_provider_app,
                    agent_main_api=args.agent_main_api,
                    agent_log_api=args.agent_log_api,
                    debug=args.debug,
                    host=args.host,
                    port=args.port,
                    output_dir=args.output_dir,
                    python_exe=sys.executable,
                    is_exe=frozen,
                )
                log_info("Auto-generation completed successfully.")
            except Exception as e:
                log_error(f"Auto-generation failed: {e}")
        else:
            log_error("Auto-generation requested but generate_agent_json module not found. Skipping.")

    # Set up signal handlers
    running = True
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Determine whether to show banner
    show_banner = args.show_banner
    if not show_banner:
        os.environ["FASTMCP_QUIET"] = "1"
    else:
        os.environ.pop("FASTMCP_QUIET", None)

    # Auto-refresh is always enabled
    if args.transport == "stdio":
        log_warning("Auto-refresh is enabled with stdio transport. Restart will disconnect the client.")
    log_info(f"Auto-refresh is ENABLED with interval={args.refresh_interval}s")
    refresh_thread = threading.Thread(
        target=refresh_monitor,
        args=(args.refresh_interval, args),
        daemon=True
    )
    refresh_thread.start()
    log_info("Refresh monitor thread started.")

    # Main loop: start and restart FastMCP subprocess when needed
    mcp_process = None
    try:
        while running:
            # Start the FastMCP subprocess
            log_info("Starting FastMCP subprocess...")
            mcp_process = multiprocessing.Process(
                target=run_fastmcp,
                args=(args, show_banner),
                daemon=False   # Not daemon so we can wait for it cleanly
            )
            mcp_process.start()
            log_info(f"FastMCP subprocess PID={mcp_process.pid}")

            # Wait for the subprocess to finish or for a restart signal
            while running and mcp_process.is_alive():
                # Check if restart is needed (set by refresh_monitor)
                if _need_restart:
                    log_info("Restart signal received, terminating FastMCP subprocess...")
                    mcp_process.terminate()
                    mcp_process.join(timeout=5)
                    if mcp_process.is_alive():
                        mcp_process.kill()
                        mcp_process.join()
                    _need_restart = False
                    break  # exit inner loop to restart
                # Sleep a bit to avoid busy loop
                time.sleep(0.5)

            # If the subprocess died unexpectedly and we didn't request restart,
            # we should also restart it.
            if running and not _need_restart and mcp_process and not mcp_process.is_alive():
                log_warning("FastMCP subprocess died unexpectedly, restarting...")
                # allow a short delay before restart
                time.sleep(1)

            # If we are still running, the loop will restart the subprocess
    except KeyboardInterrupt:
        log_info("Main process received KeyboardInterrupt, shutting down...")
    except Exception as e:
        log_error(f"Main loop exception: {e}")
        traceback.print_exc(file=sys.stderr)
    finally:
        log_info("Shutting down main process...")
        if mcp_process and mcp_process.is_alive():
            log_info("Terminating FastMCP subprocess...")
            mcp_process.terminate()
            mcp_process.join(timeout=5)
            if mcp_process.is_alive():
                mcp_process.kill()
                mcp_process.join()
        if middleware:
            middleware.shutdown()
        log_info("Main process stopped")

if __name__ == "__main__":
    # Required for multiprocessing on Windows
    multiprocessing.freeze_support()
    main()