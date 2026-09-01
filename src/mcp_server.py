#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py - MCP Server for LingoFuse Backend (v2.17)

DESCRIPTION
    This script implements a Model Context Protocol (MCP) server that acts as a
    gateway between MCP clients (e.g., LM Studio, Claude Desktop) and a
    LingoFuse backend. It dynamically exposes tools registered in the backend
    as MCP tools.

    The server supports two transport modes:
      - stdio  : Standard input/output (default) – used for integration with
                 local MCP clients like LM Studio.
      - sse    : Server‑Sent Events (HTTP) – exposes an HTTP endpoint for
                 remote or web‑based clients.

    The connection to the LingoFuse backend is lazy: the server starts even if
    the backend is unavailable, and will retry automatically on the first tool
    call. This allows the backend to be started later without restarting the
    MCP server.

AUTO‑GENERATE CONFIGURATIONS
    Set the global constant `AUTO_GENERATE_CONFIGS` to `True` (see "GLOBAL
    DEFAULTS" section) to automatically generate MCP client configuration files
    (JSON) and Markdown documentation for all supported agents (LM Studio,
    Claude Desktop, Continue.dev, Generic) each time the server starts.
    The files are written to the directory specified by `--output-dir` (default
    `./mcp_configs`) and cover both stdio and SSE transports.

    This feature is useful for development, testing, or when you need to
    distribute configuration files to clients without manually running the
    generator.

USAGE EXAMPLES
    # Start with default settings (stdio transport, IPC endpoint)
    python mcp_server.py

    # Start with SSE (HTTP) transport on port 8080
    python mcp_server.py --transport sse --port 8080

    # Use a different LingoFuse endpoint and increase timeout
    python mcp_server.py --endpoint tcp://127.0.0.1:9897 --timeout 10000

    # Override backend application names
    python mcp_server.py --tool-provider-app my_custom_provider --agent-main-api get_tools

    # Enable debug logging
    python mcp_server.py --debug

    # Generate configuration files (manual) and exit
    python mcp_server.py --generate-configs --output-dir ./my_configs

COMMAND‑LINE ARGUMENTS (all optional)
    --transport, -t      Transport protocol: 'stdio' or 'sse' (default: stdio)
    --host               Host to bind for SSE (default: 0.0.0.0)
    --port, -p           Port to bind for SSE (default: 8000)

    --endpoint           LingoFuse endpoint to connect to (default: ipc:cross)
    --timeout, -T        Call timeout in milliseconds (default: 5000)
    --reg-agent-app      Application name used by this client (default: reg_agent)
    --tool-provider-app  Backend application that provides tools (default: my_tool_provider)
    --agent-main-api     API name to fetch the tool list (default: agent_main)
    --agent-log-api      API name to send logs (default: agent_log)
    --debug              Enable verbose debug output

    --generate-configs   Generate MCP client configuration files and exit
    --output-dir         Output directory for generated configs (default: ./mcp_configs)

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
    MCP_LOG_ENABLED                 Enable/disable file logging (default: true)
    MCP_LOG_FILE                    Log file name (default: mcp_server.log)

NOTES
    - The server registers tools by calling `agent_main` on the backend.
      The backend must respond with a JSON object containing a "tools" array.
    - Each tool definition must include: name, description, target_app,
      target_api, and parameters (JSON Schema).
    - In SSE mode, the server listens on /sse by default (FastMCP standard).
    - Log messages are written to both the file (mcp_server.log) and the
      backend via the `agent_log` API (if connected).
    - The configuration generator requires `generate_agent_json.py` in the
      same directory or in PYTHONPATH.

DEPENDENCIES
    - fastmcp (>= 0.1) and pydantic
    - lingofuse package (must be installed or in PYTHONPATH)

AUTHOR
    PassByYou888 / LingoFuse Team
"""

# ============================================================================
# GLOBAL DEFAULTS – change these to modify default startup behavior
# ============================================================================
DEFAULT_ENDPOINT = "ipc:cross"
DEFAULT_TIMEOUT_MS = 5000
DEFAULT_REG_AGENT_APP = "reg_agent"
DEFAULT_TOOL_PROVIDER_APP = "my_tool_provider"
DEFAULT_AGENT_MAIN_API = "agent_main"
DEFAULT_AGENT_LOG_API = "agent_log"
DEFAULT_TRANSPORT = "stdio"          # 'stdio' or 'sse'
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_LOG_ENABLED = True
DEFAULT_LOG_FILE = "mcp_server.log"

# Auto‑generate configuration files on startup (set to True to enable)
AUTO_GENERATE_CONFIGS = False
# ============================================================================

import asyncio
import sys
import os
import logging
import traceback
import argparse
from typing import Dict, Any, List, Optional

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
# Logging configuration (controlled by environment variables)
# ============================================================================
_LOG_ENABLED = os.environ.get("MCP_LOG_ENABLED", str(DEFAULT_LOG_ENABLED)).lower() not in ("false", "0", "off", "no")
_LOG_FILE = os.environ.get("MCP_LOG_FILE", DEFAULT_LOG_FILE)
_LOGGER = None

def _init_logger():
    global _LOGGER
    if _LOG_ENABLED:
        _LOGGER = logging.getLogger("mcp_server")
        _LOGGER.setLevel(logging.DEBUG)
        handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _LOGGER.addHandler(handler)
        _LOGGER.propagate = False
        _LOGGER.info("Log file enabled: %s", _LOG_FILE)
    else:
        _LOGGER = logging.getLogger("mcp_server")
        _LOGGER.addHandler(logging.NullHandler())

_init_logger()

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
# Global middleware instance (used by log functions)
# ============================================================================
middleware: Optional[LanguageMiddleware] = None

# ============================================================================
# Log functions (file + backend sync)
# ============================================================================
def _send_to_backend(level: str, msg: str):
    global middleware
    if middleware and middleware.is_connected():
        try:
            middleware.log(f"[{level}] {msg}")
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
    if _LOGGER:
        _LOGGER.debug(msg)
    _send_to_backend("DEBUG", msg)

# ============================================================================
# Global state
# ============================================================================
running = True
mcp_app: Optional[FastMCP] = None

# ============================================================================
# Core tool calling
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

    log_debug(f"API call request: {tool_name} args={arguments}")

    try:
        # Ensure connection is established (will retry if needed)
        if not middleware._ensure_connected():
            # If still not connected, raise an error
            raise ConnectionError("Backend not connected")
        result = await asyncio.to_thread(middleware.call_tool, tool_name, arguments)
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
# Server lifecycle
# ============================================================================

def shutdown_server():
    global running, mcp_app, middleware
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
  LINGOFUSE_ENDPOINT         - Default endpoint (default: {})
  LINGOFUSE_TIMEOUT_MS       - Default timeout in ms (default: {})
  MCP_TRANSPORT              - Transport: stdio or sse (default: {})
  MCP_HOST                   - Host for sse transport (default: {})
  MCP_PORT                   - Port for sse transport (default: {})
  MCP_LOG_ENABLED            - Enable/disable logging (default: {})
  MCP_LOG_FILE               - Log file name (default: {})
        """.format(
            DEFAULT_ENDPOINT, DEFAULT_TIMEOUT_MS,
            DEFAULT_TRANSPORT, DEFAULT_HOST, DEFAULT_PORT,
            str(DEFAULT_LOG_ENABLED), DEFAULT_LOG_FILE
        )
    )
    # Transport options
    parser.add_argument(
        "--transport", "-t",
        choices=["stdio", "sse"],
        default=os.environ.get("MCP_TRANSPORT", DEFAULT_TRANSPORT),
        help="Transport protocol: stdio (default) or sse (HTTP)"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", DEFAULT_HOST),
        help="Host to bind when using sse transport (default: {})".format(DEFAULT_HOST)
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=int(os.environ.get("MCP_PORT", str(DEFAULT_PORT))),
        help="Port to bind when using sse transport (default: {})".format(DEFAULT_PORT)
    )

    # Middleware configuration
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
        help="Enable debug mode (more verbose logs)"
    )

    # Config generator options
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

    return parser.parse_args()

def main():
    global middleware, mcp_app

    args = parse_args()

    # If generate-configs is requested, call the generator and exit
    if args.generate_configs:
        if not _HAS_GENERATOR:
            print("[ERROR] generate_agent_json module not found. Ensure it is in the same directory or PYTHONPATH.", file=sys.stderr)
            sys.exit(1)
        generate_configs(
            server_script_path=os.path.abspath(__file__),
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
        )
        sys.exit(0)

    if args.debug:
        set_debug_mode(True)
        log_info("Debug mode enabled")

    log_info(f"Starting MCP server with transport={args.transport}")

    # Initialize LanguageMiddleware with provided parameters
    try:
        middleware = LanguageMiddleware.get_instance(
            endpoint=args.endpoint,
            timeout_ms=args.timeout,
            reg_agent_app_name=args.reg_agent_app,   # <-- FIXED: parameter name
            tool_provider_app=args.tool_provider_app,
            agent_main_api=args.agent_main_api,
            agent_log_api=args.agent_log_api
        )
        # Attempt connection but don't fail if unavailable
        if not middleware._ensure_connected():
            log_info("Backend not connected – will retry on first tool call")
        else:
            log_info("LanguageMiddleware initialized and connected")
    except Exception as e:
        log_error(f"Failed to initialize LanguageMiddleware: {e}")
        # We continue anyway; middleware might connect later
        if middleware is None:
            # If no middleware object, we cannot proceed
            sys.exit(1)

    # Create FastMCP app
    mcp_app = FastMCP(
        name="BackendGateway",
        instructions="Dynamically registered backend tools"
    )

    register_dynamic_tools(mcp_app)

    # ========================================================================
    # AUTO‑GENERATE CONFIGURATIONS (if enabled)
    # ========================================================================
    if AUTO_GENERATE_CONFIGS:
        if _HAS_GENERATOR:
            try:
                log_info("Auto‑generating MCP client configurations...")
                generate_configs(
                    server_script_path=os.path.abspath(__file__),
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
                )
                log_info("Auto‑generation completed successfully.")
            except Exception as e:
                log_error(f"Auto‑generation failed: {e}")
                # Non‑fatal – continue starting the server
        else:
            log_error("Auto‑generation requested but generate_agent_json module not found. Skipping.")

    # Register signal handlers
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run with selected transport
    try:
        if args.transport == "stdio":
            mcp_app.run(transport="stdio")
        else:  # sse
            log_info(f"Starting SSE server on http://{args.host}:{args.port}")
            mcp_app.run(transport="sse", host=args.host, port=args.port)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log_error(f"Runtime exception: {e}")
        traceback.print_exc(file=sys.stderr)
    finally:
        shutdown_server()

if __name__ == "__main__":
    main()