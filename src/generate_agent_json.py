#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_agent_json.py - MCP Client Configuration Generator

This module generates JSON configuration files and Markdown documentation
for various MCP clients (LM Studio, Claude Desktop, Continue.dev, Jan, Generic)
supporting both stdio and SSE transports.

It is designed to be imported and called by mcp_server.py, but can also
run standalone.

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
    endpoint: str = "ipc:cross",
    timeout_ms: int = 5000,
    reg_agent_app: str = "reg_agent",
    tool_provider_app: str = "my_tool_provider",
    agent_main_api: str = "agent_main",
    agent_log_api: str = "agent_log",
    debug: bool = False,
    host: str = "0.0.0.0",
    port: int = 8000,
    output_dir: str = "./mcp_configs",
    python_exe: Optional[str] = None,
) -> None:
    """
    Generate MCP client configuration files and Markdown docs.

    Args:
        server_script_path: Path to mcp_server.py (used in command line)
        endpoint: LingoFuse endpoint
        timeout_ms: Call timeout in milliseconds
        reg_agent_app: Registration agent app name
        tool_provider_app: Tool provider app name
        agent_main_api: API to fetch tool list
        agent_log_api: API to send logs
        debug: Enable debug mode
        host: Host for SSE transport
        port: Port for SSE transport
        output_dir: Output directory for generated files
        python_exe: Python executable path (defaults to sys.executable)
    """
    if python_exe is None:
        python_exe = sys.executable

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"[Generator] Output directory: {output_path.absolute()}")

    # Build base command arguments (without --transport, --host, --port)
    # NOTE: args list does NOT include the interpreter; that goes in "command"
    base_args = [
        server_script_path,
        "--endpoint", endpoint,
        "--timeout", str(timeout_ms),
        "--reg-agent-app", reg_agent_app,
        "--tool-provider-app", tool_provider_app,
        "--agent-main-api", agent_main_api,
        "--agent-log-api", agent_log_api,
    ]
    if debug:
        base_args.append("--debug")

    # stdio configuration args (add transport)
    stdio_args = base_args + ["--transport", "stdio"]
    # sse configuration args (add transport, host, port)
    sse_args = base_args + ["--transport", "sse", "--host", host, "--port", str(port)]

    # Environment variables (same for all)
    env_vars = {
        "LINGOFUSE_ENDPOINT": endpoint,
        "MCP_LOG_ENABLED": "true",
        "MCP_LOG_FILE": str(output_path / "mcp_server.log"),
    }

    # ----- Define agent templates -----
    agents = {
        "lmstudio": {
            "name": "LM Studio",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_args": stdio_args,
            "sse_url": f"http://{host}:{port}/sse",
        },
        "claude": {
            "name": "Claude Desktop",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_args": stdio_args,
            "sse_url": f"http://{host}:{port}/sse",
        },
        "continue": {
            "name": "Continue.dev",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_args": stdio_args,
            "sse_url": f"http://{host}:{port}/sse",
        },
        "jan": {
            "name": "Jan AI",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_args": stdio_args,
            "sse_url": f"http://{host}:{port}/sse",
        },
        "generic": {
            "name": "Generic MCP Client",
            "config_key": "mcpServers",
            "server_key": "pascal-backend",
            "stdio_args": stdio_args,
            "sse_url": f"http://{host}:{port}/sse",
        },
    }

    # Generate for each agent
    for agent_id, agent in agents.items():
        # ---- stdio config ----
        stdio_config = {
            agent["config_key"]: {
                agent["server_key"]: {
                    "command": python_exe,
                    "args": agent["stdio_args"],
                    "env": env_vars,
                }
            }
        }
        stdio_file = output_path / f"{agent_id}_stdio.json"
        with open(stdio_file, "w", encoding="utf-8") as f:
            json.dump(stdio_config, f, indent=2, ensure_ascii=False)
        print(f"[Generator] Wrote: {stdio_file}")

        # ---- sse config ----
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
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(f"""# {agent['name']} MCP Configuration

This document explains how to configure **{agent['name']}** to use the **LingoFuse Backend MCP Server**.

## Transport Options

The server supports two transports:

1. **stdio** (default) – best for local clients.
2. **sse** (HTTP) – best for remote or web-based clients.

---

## Configuration Files

Two JSON files are provided:

- **`{agent_id}_stdio.json`**: Use this for stdio transport.
- **`{agent_id}_sse.json`**: Use this for SSE transport.

### stdio Configuration

```json
{json.dumps(stdio_config, indent=2, ensure_ascii=False)}
```

### sse Configuration

```json
{json.dumps(sse_config, indent=2, ensure_ascii=False)}
```

---

## How to Use

### For LM Studio / Claude Desktop / Jan

1. Locate your MCP configuration file (usually `~/.lmstudio/mcp.json` or similar).
2. Merge the contents of the desired JSON file into the `"mcpServers"` section.
3. Restart the client.

### For Continue.dev

Continue uses a similar `mcpServers` structure in its config. Merge accordingly.

### For Generic MCP Clients

Use the `generic_stdio.json` or `generic_sse.json` as a template and adapt to your client's expected format.

---

## Notes

- The **stdio** server will start automatically when the client launches.
- The **sse** server must be started manually **before** the client connects.
- Ensure the `LINGOFUSE_ENDPOINT` environment variable (or `--endpoint`) matches your LingoFuse backend.

## Generated Files

All configurations were generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Server command: `{python_exe} {server_script_path}`
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
        help="Path to mcp_server.py (used in the generated command line)"
    )
    parser.add_argument(
        "--endpoint",
        default="ipc:cross",
        help="LingoFuse endpoint (default: ipc:cross)"
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
        default="my_tool_provider",
        help="Tool provider app name (default: my_tool_provider)"
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
        help="Host for SSE (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE (default: 8000)"
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
    )


if __name__ == "__main__":
    main()