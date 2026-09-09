#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_agent_json.py - MCP Client Configuration Generator

This module generates JSON configuration files and Markdown documentation
for various MCP clients (LM Studio, Claude Desktop, Continue.dev, Jan, Generic,
and DeepSeek) supporting stdio (direct and proxy), Streamable HTTP (recommended),
and legacy SSE transports.

It is designed to be imported and called by mcp_server.py, but can also
run standalone.

It automatically detects whether the server script is a Python source file
(.py) or a packaged executable (.exe on Windows, or executable file on Unix)
and generates appropriate command lines.

Optionally, it can generate a stdio configuration that uses mcp_proxy as an
intermediary to log all communication (useful for debugging and integration
verification).

Generated stdio configurations automatically include `--log-file` to enable
file logging. HTTP and SSE configurations rely on the `MCP_LOG_FILE` environment
variable for file logging.

DEPENDENCIES
    - Python 3.7+
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


def generate_configs(
    server_script_path: str,
    endpoint: str = "ipc:agent",
    timeout_ms: int = 5000,
    reg_agent_app: str = "reg_agent",
    tool_provider_app: str = "agent_main_app",
    agent_main_api: str = "agent_main",
    agent_log_api: str = "agent_log",
    debug: bool = False,
    host: str = "0.0.0.0",
    port: int = 8000,
    output_dir: str = "./mcp_configs",
    python_exe: Optional[str] = None,
    is_exe: Optional[bool] = None,
    proxy_path: Optional[str] = None,
) -> None:
    """
    Generate MCP client configuration files and Markdown docs.

    Args:
        server_script_path: Path to mcp_server.py (or the executable)
        endpoint: LingoFuse endpoint
        timeout_ms: Call timeout in milliseconds
        reg_agent_app: Registration agent app name
        tool_provider_app: Tool provider app name
        agent_main_api: API to fetch tool list
        agent_log_api: API to send logs
        debug: Enable debug mode
        host: Host for HTTP transport
        port: Port for HTTP transport
        output_dir: Output directory for generated files
        python_exe: Python executable path (defaults to sys.executable)
        is_exe: Force treat server_script_path as executable (if None, auto-detect)
        proxy_path: Path to mcp_proxy executable (if provided, generates proxy stdio configs)
    """
    if python_exe is None:
        python_exe = sys.executable

    # Auto-detect if server_script_path is a Python script or an executable
    if is_exe is None:
        # Consider .py or .pyw files as scripts; everything else as executable
        lower_path = server_script_path.lower()
        if lower_path.endswith(('.py', '.pyw')):
            is_exe = False
        else:
            is_exe = True

    # Validate proxy_path if provided
    use_proxy = False
    if proxy_path:
        proxy_path = os.path.abspath(proxy_path)
        if os.path.isfile(proxy_path):
            use_proxy = True
            print(f"[Generator] Proxy executable found: {proxy_path}")
        else:
            print(f"[Generator] WARNING: proxy_path '{proxy_path}' does not exist. Proxy configs will be skipped.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"[Generator] Output directory: {output_path.absolute()}")

    # Absolute path for the log file, to ensure it is written in the config directory
    log_file_path = str((output_path / "mcp_server.log").resolve())

    # Build base command arguments (without --transport, --host, --port)
    base_args = [
        "--endpoint", endpoint,
        "--timeout", str(timeout_ms),
        "--reg-agent-app", reg_agent_app,
        "--tool-provider-app", tool_provider_app,
        "--agent-main-api", agent_main_api,
        "--agent-log-api", agent_log_api,
    ]
    if debug:
        base_args.append("--debug")

    # stdio configuration args (add transport and log-file)
    stdio_args = base_args + ["--transport", "stdio", "--log-file", log_file_path]
    # HTTP configuration args (add transport, host, port)
    http_args = base_args + ["--transport", "http", "--host", host, "--port", str(port)]
    # Legacy SSE configuration args (still supported but deprecated)
    sse_args = base_args + ["--transport", "sse", "--host", host, "--port", str(port)]

    # Environment variables (same for all)
    env_vars = {
        "LINGOFUSE_ENDPOINT": endpoint,
        "MCP_LOG_ENABLED": "true",
        "MCP_LOG_FILE": log_file_path,
    }

    # Determine command and args for stdio (depending on script vs exe)
    if is_exe:
        # For executable: command is the executable itself, args are only the flags
        stdio_command = server_script_path
        stdio_args_full = stdio_args
        http_command = server_script_path
        http_args_full = http_args
        sse_command = server_script_path
        sse_args_full = sse_args
    else:
        # For Python script: command is python interpreter, first arg is script
        stdio_command = python_exe
        stdio_args_full = [server_script_path] + stdio_args
        http_command = python_exe
        http_args_full = [server_script_path] + http_args
        sse_command = python_exe
        sse_args_full = [server_script_path] + sse_args

    # If proxy is enabled, prepare proxy-specific command and args
    if use_proxy:
        # For proxy: command is the proxy executable
        # Args: server_script_path + stdio_args (the proxy passes these to the real server)
        proxy_stdio_command = proxy_path
        proxy_stdio_args_full = [server_script_path] + stdio_args
        print("[Generator] Proxy stdio configs will be generated.")

    # ----- Define agent templates -----
    # The 'http' transport uses the official Streamable HTTP endpoint '/mcp'.
    # The 'sse' endpoint '/sse' is deprecated but still supported for legacy clients.
    agents = {
        "lmstudio": {
            "name": "LM Studio",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_command": stdio_command,
            "stdio_args": stdio_args_full,
            "http_command": http_command,
            "http_args": http_args_full,
            "sse_command": sse_command,
            "sse_args": sse_args_full,
            "http_url": f"http://{host}:{port}/mcp",
            "sse_url": f"http://{host}:{port}/sse",
        },
        "claude": {
            "name": "Claude Desktop",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_command": stdio_command,
            "stdio_args": stdio_args_full,
            "http_command": http_command,
            "http_args": http_args_full,
            "sse_command": sse_command,
            "sse_args": sse_args_full,
            "http_url": f"http://{host}:{port}/mcp",
            "sse_url": f"http://{host}:{port}/sse",
        },
        "continue": {
            "name": "Continue.dev",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_command": stdio_command,
            "stdio_args": stdio_args_full,
            "http_command": http_command,
            "http_args": http_args_full,
            "sse_command": sse_command,
            "sse_args": sse_args_full,
            "http_url": f"http://{host}:{port}/mcp",
            "sse_url": f"http://{host}:{port}/sse",
        },
        "jan": {
            "name": "Jan AI",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_command": stdio_command,
            "stdio_args": stdio_args_full,
            "http_command": http_command,
            "http_args": http_args_full,
            "sse_command": sse_command,
            "sse_args": sse_args_full,
            "http_url": f"http://{host}:{port}/mcp",
            "sse_url": f"http://{host}:{port}/sse",
        },
        "deepseek": {
            "name": "DeepSeek",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_command": stdio_command,
            "stdio_args": stdio_args_full,
            "http_command": http_command,
            "http_args": http_args_full,
            "sse_command": sse_command,
            "sse_args": sse_args_full,
            "http_url": f"http://{host}:{port}/mcp",
            "sse_url": f"http://{host}:{port}/sse",
        },
        "generic": {
            "name": "Generic MCP Client",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_command": stdio_command,
            "stdio_args": stdio_args_full,
            "http_command": http_command,
            "http_args": http_args_full,
            "sse_command": sse_command,
            "sse_args": sse_args_full,
            "http_url": f"http://{host}:{port}/mcp",
            "sse_url": f"http://{host}:{port}/sse",
        },
    }

    # Generate for each agent
    for agent_id, agent in agents.items():
        # ---- stdio config (direct) ----
        stdio_config = {
            agent["config_key"]: {
                agent["server_key"]: {
                    "command": agent["stdio_command"],
                    "args": agent["stdio_args"],
                    "env": env_vars,
                }
            }
        }
        stdio_file = output_path / f"{agent_id}_stdio.json"
        with open(stdio_file, "w", encoding="utf-8") as f:
            json.dump(stdio_config, f, indent=2, ensure_ascii=False)
        print(f"[Generator] Wrote: {stdio_file}")

        # ---- stdio config (via proxy) ----
        if use_proxy:
            proxy_stdio_config = {
                agent["config_key"]: {
                    agent["server_key"]: {
                        "command": proxy_stdio_command,
                        "args": proxy_stdio_args_full,
                        "env": env_vars,
                    }
                }
            }
            proxy_stdio_file = output_path / f"{agent_id}_stdio_proxy.json"
            with open(proxy_stdio_file, "w", encoding="utf-8") as f:
                json.dump(proxy_stdio_config, f, indent=2, ensure_ascii=False)
            print(f"[Generator] Wrote: {proxy_stdio_file}")

        # ---- HTTP (Streamable) config ----
        # Uses the '/mcp' endpoint (official recommendation)
        http_config = {
            agent["config_key"]: {
                agent["server_key"]: {
                    "url": agent["http_url"],
                    "env": env_vars,
                }
            }
        }
        http_file = output_path / f"{agent_id}_http.json"
        with open(http_file, "w", encoding="utf-8") as f:
            json.dump(http_config, f, indent=2, ensure_ascii=False)
        print(f"[Generator] Wrote: {http_file}")

        # ---- Legacy SSE config (deprecated) ----
        # Kept for backward compatibility; clients should migrate to '/mcp'
        sse_config = {
            agent["config_key"]: {
                agent["server_key"]: {
                    "url": agent["sse_url"],
                    "env": env_vars,
                }
            }
        }
        sse_file = output_path / f"{agent_id}_sse.json"
        with open(sse_file, "w", encoding="utf-8") as f:
            json.dump(sse_config, f, indent=2, ensure_ascii=False)
        print(f"[Generator] Wrote: {sse_file}")

        # ---- Markdown documentation ----
        md_file = output_path / f"{agent_id}_README.md"
        # Determine the invocation description based on script vs exe
        if is_exe:
            server_invocation = f"`{server_script_path}` (executable)"
            stdio_cmd_example = f"{server_script_path} --transport stdio --log-file {log_file_path}"
            proxy_cmd_example = f"{proxy_path} {server_script_path} --transport stdio --log-file {log_file_path}" if use_proxy else "(proxy not available)"
            http_cmd_example = f"{server_script_path} --transport http --host {host} --port {port}"
            sse_cmd_example = f"{server_script_path} --transport sse --host {host} --port {port}"
        else:
            server_invocation = f"`{python_exe} {server_script_path}` (Python script)"
            stdio_cmd_example = f"{python_exe} {server_script_path} --transport stdio --log-file {log_file_path}"
            proxy_cmd_example = f"{proxy_path} {python_exe} {server_script_path} --transport stdio --log-file {log_file_path}" if use_proxy else "(proxy not available)"
            http_cmd_example = f"{python_exe} {server_script_path} --transport http --host {host} --port {port}"
            sse_cmd_example = f"{python_exe} {server_script_path} --transport sse --host {host} --port {port}"

        # Build proxy section text if enabled
        proxy_section = ""
        if use_proxy:
            proxy_section = f"""
- **`{agent_id}_stdio_proxy.json`**: Use this for stdio transport **with the proxy** (logs all communication via mcp_proxy).
  The proxy command is `{proxy_path}` and it forwards to the real server.
"""

        # Determine the proxy status text for the heading
        proxy_heading_suffix = " (if proxy is enabled)" if use_proxy else " (not enabled)"

        # Build the JSON display for proxy config (or placeholder)
        if use_proxy:
            proxy_json_display = json.dumps(proxy_stdio_config, indent=2, ensure_ascii=False)
            proxy_extra = f"```json\n{proxy_json_display}\n```"
        else:
            proxy_extra = "*Proxy support is not enabled in this build.*"

        with open(md_file, "w", encoding="utf-8") as f:
            f.write(f"""# {agent['name']} MCP Configuration

This document explains how to configure **{agent['name']}** to use the **LingoFuse Backend MCP Server**.

The server can be run as:
- **{server_invocation}**

## Transport Options

The server supports three transport modes:

1. **stdio** (default) – best for local clients.
   - Two variants are provided: direct (default) and proxy (for debugging).
2. **http** (recommended) – Streamable HTTP (official MCP standard) for remote/web clients.
   - Uses endpoint: `{agent['http_url']}`
3. **sse** (deprecated) – Legacy Server-Sent Events transport. Still supported but not recommended for new deployments.
   - Uses endpoint: `{agent['sse_url']}`

---

## Configuration Files

Four JSON files are provided (three if proxy is not enabled):

- **`{agent_id}_stdio.json`**: Use this for stdio transport (direct).
{proxy_section}
- **`{agent_id}_http.json`**: Use this for Streamable HTTP (recommended).
- **`{agent_id}_sse.json`**: Use this for legacy SSE (deprecated).

### stdio Configuration (Direct)

```json
{json.dumps(stdio_config, indent=2, ensure_ascii=False)}
```

### stdio Configuration (via Proxy){proxy_heading_suffix}

{proxy_extra}

### HTTP (Streamable) Configuration

```json
{json.dumps(http_config, indent=2, ensure_ascii=False)}
```

### SSE Configuration (Deprecated)

```json
{json.dumps(sse_config, indent=2, ensure_ascii=False)}
```

---

## How to Use

### For LM Studio / Claude Desktop / Jan / DeepSeek

1. Locate your MCP configuration file (usually `~/.lmstudio/mcp.json` or similar).
2. Merge the contents of the desired JSON file into the `"mcpServers"` section.
3. Restart the client.

> **Note:** 
> - If your client supports Streamable HTTP (recommended), use the `_http.json` file.
> - If you need to debug or monitor the stdio communication, use the `_stdio_proxy.json` file (if available). This wraps the server with `mcp_proxy` which logs all messages to `proxy.log` and stderr.
> - If you only need stdio without proxy, use `_stdio.json`.

### For Continue.dev

Continue uses a similar `mcpServers` structure in its config. Merge accordingly.

### For Generic MCP Clients

Use the `generic_stdio.json`, `generic_stdio_proxy.json` (if available), `generic_http.json`, or `generic_sse.json` as a template and adapt to your client's expected format.

---

## Manual Server Invocation (for testing)

To start the server manually in stdio mode (direct):

```
{stdio_cmd_example}
```

To start the server manually in stdio mode **via proxy** (if proxy is available):

```
{proxy_cmd_example}
```

To start the server in Streamable HTTP mode (recommended for remote clients):

```
{http_cmd_example}
```

To start the server in legacy SSE mode (deprecated):

```
{sse_cmd_example}
```

## Notes

- The **stdio** server will start automatically when the client launches.
- The **HTTP** server must be started manually **before** the client connects.
- The **SSE** server (deprecated) must also be started manually, but migration to HTTP is strongly encouraged.
- The **proxy** stdio mode is useful for debugging – all JSON-RPC messages will be logged to `proxy.log` and stderr.
- File logging is enabled by default for stdio configurations (via `--log-file`). For HTTP/SSE, file logging is controlled by the `MCP_LOG_FILE` environment variable.
- Ensure the `LINGOFUSE_ENDPOINT` environment variable (or `--endpoint`) matches your LingoFuse backend.

## Migration from SSE to HTTP

If you were previously using SSE, update your configuration to use the `_http.json` file and change the URL from `/sse` to `/mcp`. Also update the server command to use `--transport http` instead of `--transport sse`.

## Generated Files

All configurations were generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Server command: `{server_script_path if is_exe else python_exe + ' ' + server_script_path}`
""")
        print(f"[Generator] Wrote: {md_file}")

    print("\n[Generator] All configurations generated successfully.")


# ============================================================================
# Command-line entry point (standalone)
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="Generate MCP client configurations")
    parser.add_argument(
        "--server-script",
        required=True,
        help="Path to mcp_server.py (or the executable)"
    )
    parser.add_argument(
        "--endpoint",
        default="ipc:agent",
        help="LingoFuse endpoint (default: ipc:agent)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5000,
        help="Call timeout in ms (default: 5000)"
    )
    parser.add_argument(
        "--reg-agent-app",
        default="reg_agent",
        help="Registration agent app name (default: reg_agent)"
    )
    parser.add_argument(
        "--tool-provider-app",
        default="agent_main_app",
        help="Tool provider app name (default: agent_main_app)"
    )
    parser.add_argument(
        "--agent-main-api",
        default="agent_main",
        help="API for agent_main (default: agent_main)"
    )
    parser.add_argument(
        "--agent-log-api",
        default="agent_log",
        help="API for agent_log (default: agent_log)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP transport (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)"
    )
    parser.add_argument(
        "--output-dir",
        default="./mcp_configs",
        help="Output directory (default: ./mcp_configs)"
    )
    parser.add_argument(
        "--python-exe",
        default=sys.executable,
        help="Python executable (default: current interpreter)"
    )
    parser.add_argument(
        "--is-exe",
        action="store_true",
        help="Force treat server-script as an executable (not a Python script)"
    )
    parser.add_argument(
        "--proxy-path",
        default=None,
        help="Path to mcp_proxy executable (if provided, generates stdio proxy configs)"
    )
    args = parser.parse_args()

    generate_configs(
        server_script_path=args.server_script,
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
        python_exe=args.python_exe,
        is_exe=args.is_exe,
        proxy_path=args.proxy_path,
    )


if __name__ == "__main__":
    main()
