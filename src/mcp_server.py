#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py - Stable version v2.11
- Log file recording synchronized with Pascal agent_log: all logs are written to file and sent to Pascal console
- Log level prefixes (INFO/ERROR/DEBUG) are also sent
"""

import asyncio
import sys
import os
import logging
import traceback
from typing import Dict, Any, List, Optional

# ============================================================================
# Logging configuration (controlled by environment variables)
# ============================================================================
_LOG_ENABLED = os.environ.get("MCP_LOG_ENABLED", "true").lower() not in ("false", "0", "off", "no")
_LOG_FILE = os.environ.get("MCP_LOG_FILE", "mcp_server.log")
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

# Initialize logger before importing other modules
_init_logger()

# ============================================================================
# Import other modules
# ============================================================================
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

try:
    from language_middleware import (
        PascalMiddleware, PascalConnectionError,
        set_debug_mode, get_logs, clear_logs, DEBUG_MODE
    )
except ImportError as e:
    if _LOGGER:
        _LOGGER.error(f"Failed to import pascal_middleware: {e}")
    print(f"[FATAL] Failed to import pascal_middleware: {e}", file=sys.stderr)
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
middleware: Optional[PascalMiddleware] = None

# ============================================================================
# Log functions (file + Pascal sync)
# ============================================================================
def _send_to_pascal(level: str, msg: str):
    """Internal: send log to Pascal via agent_log"""
    global middleware
    if middleware and middleware.is_connected():
        try:
            middleware.log(f"[{level}] {msg}")
        except Exception:
            pass  # Ignore sync errors, do not affect main flow

def log_info(msg):
    if _LOGGER:
        _LOGGER.info(msg)
    _send_to_pascal("INFO", msg)

def log_error(msg):
    if _LOGGER:
        _LOGGER.error(msg)
    _send_to_pascal("ERROR", msg)

def log_debug(msg):
    if _LOGGER:
        _LOGGER.debug(msg)
    _send_to_pascal("DEBUG", msg)

# ============================================================================
# Configuration
# ============================================================================
DEFAULT_ENDPOINT = os.environ.get("LINGOFUSE_ENDPOINT", "ipc:cross")

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
        raise RuntimeError("PascalMiddleware not initialized")
    return middleware.get_tools()

async def call_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    global middleware
    if middleware is None:
        raise RuntimeError("PascalMiddleware not initialized")
    
    log_debug(f"API call request: {tool_name} args={arguments}")
    
    try:
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
    if mcp_app:
        pass
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

def main():
    global middleware, mcp_app

    log_info("Starting MCP server (stdio)...")
    
    try:
        middleware = PascalMiddleware.get_instance()
        if not middleware.is_connected():
            log_info("Warning: Pascal backend not connected")
        else:
            log_info("PascalMiddleware initialized")
    except Exception as e:
        log_error(f"Failed to initialize PascalMiddleware: {e}")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    mcp_app = FastMCP(
        name="PascalBackendGateway",
        instructions="Dynamically registered Pascal backend tools"
    )

    register_dynamic_tools(mcp_app)

    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        mcp_app.run(transport="stdio")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log_error(f"Runtime exception: {e}")
        traceback.print_exc(file=sys.stderr)
    finally:
        shutdown_server()

if __name__ == "__main__":
    main()