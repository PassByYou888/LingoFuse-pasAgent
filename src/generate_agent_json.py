#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_agent_json.py - MCP Client Configuration Generator (v2.5)

This module generates JSON configuration files and Markdown documentation
for various MCP clients (LM Studio, Claude Desktop, Continue.dev, Jan,
Generic, DeepSeek). It supports:

    * stdio (direct)
    * stdio (via mcp_proxy, for debugging)
    * Streamable HTTP (recommended)
    * legacy SSE (deprecated)

The module is designed to be imported and called by mcp_server.py, but can
also be used standalone from the command line.

Project layout assumption
-------------------------
This project ships the proxy and the server side by side, mirroring their
type:

    * Source mode:   mcp_server.py + mcp_proxy.py
    * Packaged mode: mcp_server.exe + mcp_proxy.exe

The generator therefore derives the proxy launch command from the *server
type* (is_exe), not from the file extension of the proxy alone. This makes
the two modes consistent:

    * If server is a Python script:
          command = python_exe
          args    = [mcp_proxy.py, python_exe, mcp_server.py, ...]

    * If server is a native executable:
          command = mcp_proxy.exe
          args    = [mcp_server.exe, ...]

Generated stdio configurations always include `--log-file` so that the
server writes a log next to the generated configs.

CHANGELOG (v2.5)
    * Removed unused `Dict` and `Any` imports from `typing`.
    * Merged the parallel `agent_ids` list and `agent_names` dict into a
      single `agents_meta` dict, so adding a new client only requires
      editing one place.
    * Removed a dead `proxy_cmd_example = None` assignment in the
      non-proxy branch (the variable is only ever read when
      `use_proxy` is True).

CHANGELOG (v2.4)
    * When proxy is NOT enabled, the "Manual Server Invocation" section
      no longer prints an empty "via proxy" block with
      "(proxy not available)". The enabling instructions already
      appear under "Configuration Files".
    * The proxy manual command is only constructed when proxy is
      enabled.
    * The `--output-dir` hint now uses the raw user-supplied path
      instead of an absolute resolved path, so the printed command is
      copy-paste ready.

DEPENDENCIES
    - Python 3.7+
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional


# ============================================================================
# Helper: build the command that the MCP client will actually execute.
# ============================================================================
def _build_launch_command(
    program_path: str,
    program_args: list,
    is_exe: bool,
    python_exe: str,
):
    """
    Return (command, args) that a client should use to launch `program_path`.

    If `is_exe` is True, the program is treated as a native executable:
        command = program_path
        args    = program_args

    If `is_exe` is False, the program is treated as a Python script:
        command = python_exe
        args    = [program_path] + program_args
    """
    if is_exe:
        return program_path, list(program_args)
    return python_exe, [program_path] + list(program_args)


# ============================================================================
# Main config generation
# ============================================================================
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
        server_script_path: Path to mcp_server.py (or the executable).
        endpoint: LingoFuse endpoint.
        timeout_ms: Call timeout in milliseconds.
        reg_agent_app: Registration agent app name.
        tool_provider_app: Tool provider app name.
        agent_main_api: API used to fetch the tool list.
        agent_log_api: API used to send logs.
        debug: Enable debug mode.
        host: Host for HTTP transport.
        port: Port for HTTP transport.
        output_dir: Output directory for generated files.
        python_exe: Python executable (defaults to sys.executable).
        is_exe: Force treat server_script_path as an executable. If None,
                auto-detect based on the file extension.
        proxy_path: Path to mcp_proxy (script or exe). If provided and valid,
                    `_stdio_proxy.json` files will be generated.
    """
    if python_exe is None:
        python_exe = sys.executable

    # ----- Determine whether the server is a script or an exe -----
    if is_exe is None:
        lower = server_script_path.lower()
        is_exe = not lower.endswith(('.py', '.pyw'))

    # ----- Validate proxy path if provided -----
    use_proxy = False
    if proxy_path:
        proxy_path = os.path.abspath(proxy_path)
        if os.path.isfile(proxy_path):
            use_proxy = True
            print(f"[Generator] Proxy file found: {proxy_path}")
        else:
            print(f"[Generator] WARNING: proxy_path '{proxy_path}' does not exist. "
                  "Proxy configs will be skipped.")

    # ----- Prepare output directory -----
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"[Generator] Output directory: {output_path.absolute()}")

    # Absolute path for the server log file (placed next to the configs)
    log_file_path = str((output_path / "mcp_server.log").resolve())

    # ----- Base args common to all transports -----
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

    stdio_args = base_args + ["--transport", "stdio", "--log-file", log_file_path]
    http_args  = base_args + ["--transport", "http", "--host", host, "--port", str(port)]
    sse_args   = base_args + ["--transport", "sse",  "--host", host, "--port", str(port)]

    # ----- Environment variables shared by all configs -----
    env_vars = {
        "LINGOFUSE_ENDPOINT": endpoint,
        "MCP_LOG_ENABLED": "true",
        "MCP_LOG_FILE": log_file_path,
    }

    # ----- Server launch command (direct stdio) -----
    stdio_command, stdio_args_full = _build_launch_command(
        server_script_path, stdio_args, is_exe, python_exe
    )
    http_command, http_args_full = _build_launch_command(
        server_script_path, http_args, is_exe, python_exe
    )
    sse_command, sse_args_full = _build_launch_command(
        server_script_path, sse_args, is_exe, python_exe
    )

    # ----- Proxy launch command (optional) -----
    #
    # The proxy is a thin stdio wrapper that launches the real server as a
    # child process and logs every byte exchanged. Its own launch command
    # mirrors the server type, because the project ships them as a matched
    # pair (mcp_server.py + mcp_proxy.py, or mcp_server.exe + mcp_proxy.exe).
    #
    proxy_stdio_command = None
    proxy_stdio_args_full = None
    if use_proxy:
        # The proxy receives the *full launch command of the real server* as
        # its own arguments.
        if is_exe:
            child_cmd = [server_script_path] + stdio_args
        else:
            child_cmd = [python_exe, server_script_path] + stdio_args

        # Determine how to launch the proxy itself.
        proxy_lower = proxy_path.lower()
        if proxy_lower.endswith(('.py', '.pyw')):
            # Proxy is a Python script.
            proxy_stdio_command = python_exe
            proxy_stdio_args_full = [proxy_path] + child_cmd
        else:
            # Proxy is a native executable.
            proxy_stdio_command = proxy_path
            proxy_stdio_args_full = child_cmd

        print(f"[Generator] Proxy launcher : {proxy_stdio_command}")
        print(f"[Generator] Proxy args     : {proxy_stdio_args_full}")
        print("[Generator] Proxy stdio configs will be generated.")
    else:
        print("[Generator] Proxy stdio configs will NOT be generated "
              "(no valid --proxy-path).")

    # ----- Agent templates -----
    #
    # All supported clients use the same "mcpServers" structure and the
    # same HTTP/SSE URLs. Adding a new client only requires a new entry
    # in this dict.
    #
    agents_meta = {
        "lmstudio": "LM Studio",
        "claude":   "Claude Desktop",
        "continue": "Continue.dev",
        "jan":      "Jan AI",
        "deepseek": "DeepSeek",
        "generic":  "Generic MCP Client",
    }
    config_key = "mcpServers"
    server_key = "pascal-backend"
    http_url = f"http://{host}:{port}/mcp"
    sse_url  = f"http://{host}:{port}/sse"

    # ----- Loop over agents and write every file -----
    for agent_id, agent_name in agents_meta.items():
        # ---- 1. stdio (direct) ----
        stdio_config = {
            config_key: {
                server_key: {
                    "command": stdio_command,
                    "args": stdio_args_full,
                    "env": env_vars,
                }
            }
        }
        stdio_file = output_path / f"{agent_id}_stdio.json"
        with open(stdio_file, "w", encoding="utf-8") as f:
            json.dump(stdio_config, f, indent=2, ensure_ascii=False)
        print(f"[Generator] Wrote: {stdio_file}")

        # ---- 2. stdio (via proxy, optional) ----
        proxy_stdio_config = None
        if use_proxy:
            proxy_stdio_config = {
                config_key: {
                    server_key: {
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

        # ---- 3. HTTP (Streamable) ----
        http_config = {
            config_key: {
                server_key: {
                    "url": http_url,
                    "env": env_vars,
                }
            }
        }
        http_file = output_path / f"{agent_id}_http.json"
        with open(http_file, "w", encoding="utf-8") as f:
            json.dump(http_config, f, indent=2, ensure_ascii=False)
        print(f"[Generator] Wrote: {http_file}")

        # ---- 4. SSE (legacy) ----
        sse_config = {
            config_key: {
                server_key: {
                    "url": sse_url,
                    "env": env_vars,
                }
            }
        }
        sse_file = output_path / f"{agent_id}_sse.json"
        with open(sse_file, "w", encoding="utf-8") as f:
            json.dump(sse_config, f, indent=2, ensure_ascii=False)
        print(f"[Generator] Wrote: {sse_file}")

        # ---- 5. Markdown documentation ----
        md_file = output_path / f"{agent_id}_README.md"

        # Human-readable server invocation
        if is_exe:
            server_invocation = f"`{server_script_path}` (executable)"
            expected_proxy_name = "mcp_proxy.exe"
        else:
            server_invocation = (
                f"`{python_exe} {server_script_path}` (Python script)"
            )
            expected_proxy_name = "mcp_proxy.py"

        # Manual invocation examples
        stdio_cmd_example = " ".join([stdio_command] + stdio_args_full)
        http_cmd_example  = " ".join([http_command]  + http_args_full)
        sse_cmd_example   = " ".join([sse_command]   + sse_args_full)

        # ---- Proxy section in "Configuration Files" ----
        if use_proxy:
            proxy_cmd_example = " ".join(
                [proxy_stdio_command] + proxy_stdio_args_full
            )
            proxy_section = f"""
- **`{agent_id}_stdio_proxy.json`** — stdio transport **via mcp_proxy**.

  This is the recommended configuration when you need to debug the MCP
  handshake or tool calls. Every byte exchanged between the MCP client
  and `mcp_server` is written to `proxy.log` (and also forwarded to the
  MCP client's stderr, where it is typically captured in its logs).

  The proxy is launched as:
  ```
  {proxy_cmd_example}
  ```
"""
            proxy_heading_suffix = " (proxy enabled)"
            proxy_json_display = json.dumps(
                proxy_stdio_config, indent=2, ensure_ascii=False
            )
            proxy_extra = f"```json\n{proxy_json_display}\n```"

            # Extra paragraph in the "Manual Server Invocation" section
            proxy_manual_section = f"""To start the server manually in stdio mode **via proxy**:

```
{proxy_cmd_example}
```

"""
        else:
            proxy_section = f"""
- **`{agent_id}_stdio_proxy.json`** — *not generated in this run*.

  The proxy is an optional stdio wrapper that forwards every byte between
  the MCP client and `mcp_server`, writing everything to `proxy.log` and
  to stderr. It is very useful for debugging MCP handshakes or tool calls.

  **To enable the proxy variant:**

  1. Ensure `{expected_proxy_name}` exists in the same directory as the
     server (next to `mcp_server.py` in source mode, or next to
     `mcp_server.exe` in packaged mode).
  2. Re-run the config generator, for example:
     ```
     python mcp_server.py --generate-configs --output-dir {output_dir}
     ```
     Or specify the proxy path explicitly:
     ```
     python mcp_server.py --generate-configs --proxy-path /path/to/{expected_proxy_name}
     ```
  3. A new `{agent_id}_stdio_proxy.json` file will appear in this directory.
"""
            proxy_heading_suffix = " (proxy not enabled)"
            proxy_extra = (
                "*Proxy config not generated because mcp_proxy was not found. "
                "See the instructions above to enable it.*"
            )

            # No "via proxy" manual invocation block when proxy is absent.
            proxy_manual_section = ""

        # ---- Write the Markdown file ----
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(f"""# {agent_name} — MCP Configuration

This document explains how to configure **{agent_name}** to use the
**LingoFuse Backend MCP Server**.

The server can be run as:
- **{server_invocation}**

## Transport Options

The server supports three transport modes:

1. **stdio** (default) — best for local clients.
   - Two variants are provided: direct (default) and proxy (for debugging).
2. **http** (recommended) — Streamable HTTP (official MCP standard) for
   remote or web clients.
   - Uses endpoint: `{http_url}`
3. **sse** (deprecated) — Legacy Server-Sent Events transport.
   - Uses endpoint: `{sse_url}`

---

## Configuration Files

- **`{agent_id}_stdio.json`** — stdio transport, direct.
{proxy_section}
- **`{agent_id}_http.json`** — Streamable HTTP (recommended).
- **`{agent_id}_sse.json`** — legacy SSE (deprecated).

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

1. Locate your MCP configuration file
   (usually `~/.lmstudio/mcp.json` or similar).
2. Merge the contents of the desired JSON file into the
   `"mcpServers"` section.
3. Restart the client.

> **Note:**
> - If your client supports Streamable HTTP (recommended), use the
>   `_http.json` file.
> - If you need to debug or monitor the stdio communication, use the
>   `_stdio_proxy.json` file (if available). This wraps the server with
>   `mcp_proxy`, which logs all messages to `proxy.log` and stderr.
> - If you only need stdio without proxy, use `_stdio.json`.

### For Continue.dev

Continue uses a similar `mcpServers` structure in its config. Merge
accordingly.

### For Generic MCP Clients

Use the `generic_stdio.json`, `generic_stdio_proxy.json` (if available),
`generic_http.json`, or `generic_sse.json` as a template and adapt to
your client's expected format.

---

## Manual Server Invocation (for testing)

To start the server manually in stdio mode (direct):

```
{stdio_cmd_example}
```

{proxy_manual_section}To start the server in Streamable HTTP mode (recommended for remote clients):

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
- The **SSE** server (deprecated) must also be started manually, but
  migration to HTTP is strongly encouraged.
- The **proxy** stdio mode is useful for debugging — all JSON-RPC messages
  will be logged to `proxy.log` and stderr.
- File logging is enabled by default for stdio configurations
  (via `--log-file`). For HTTP/SSE, file logging is controlled by the
  `MCP_LOG_FILE` environment variable.
- Ensure the `LINGOFUSE_ENDPOINT` environment variable (or `--endpoint`)
  matches your LingoFuse backend.

## Migration from SSE to HTTP

If you were previously using SSE, update your configuration to use the
`_http.json` file and change the URL from `/sse` to `/mcp`. Also update
the server command to use `--transport http` instead of `--transport sse`.

## Generated Files

All configurations were generated on:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Server command: `{server_script_path if is_exe else python_exe + ' ' + server_script_path}`
""")
        print(f"[Generator] Wrote: {md_file}")

    print("\n[Generator] All configurations generated successfully.")


# ============================================================================
# Standalone CLI entry point
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Generate MCP client configuration files and docs"
    )
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
        help="Path to mcp_proxy script or executable "
             "(enables stdio proxy configs)"
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
