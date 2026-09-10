#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_proxy.py - Transparent stdio forwarder for MCP debugging (v2.5)

Usage:
    python mcp_proxy.py <real_command> [args...]
Example:
    python mcp_proxy.py python mcp_server.py --transport stdio

The proxy launches the real command as a child process and forwards stdin,
stdout and stderr between the MCP client and the child. Every block of data
is logged to `proxy.log` (placed next to this script) and to stderr.

CHANGELOG (v2.5)
    * Removed the top-level `signal.signal(SIGINT, ...)` handler.
      Reason: the handler called `sys.exit(0)`, which raises SystemExit.
      SystemExit bypasses the `except KeyboardInterrupt` block in
      `main()`, so pressing Ctrl+C never triggered the graceful child
      shutdown path (terminate -> wait -> kill). Instead, the child
      process relied on the OS closing the pipe, which worked but was
      not deterministic. Letting KeyboardInterrupt propagate naturally
      into `main()` restores the intended cleanup logic.

CHANGELOG (v2.4)
    * `_script_dir()` now uses `_is_frozen()`, which checks both
      `sys.frozen` and `sys._MEIPASS` (PyInstaller one-file mode).
      This matches the frozen detection used by mcp_server.py.
    * Added `_setup_console()` to force UTF-8 encoding for stdout and
      stderr on Windows. Without this, log lines containing non-ASCII
      characters (e.g. Windows paths with Chinese characters) could be
      garbled when the console code page is GBK.

CHANGELOG (v2.3)
    * CRITICAL FIX: removed `bufsize=0` from subprocess.Popen.
      Reason: `bufsize=0` makes the child's stdin/stdout/stderr
      unbuffered `io.FileIO` objects, which on Windows are effectively
      non-blocking. FastMCP 4.x wraps stdin with anyio for async reads;
      a non-blocking stdin causes it to see immediate EOF, and the
      server exits about 20 ms after starting. Using the default
      bufsize (-1, buffered) restores normal blocking pipe semantics.
    * Tightened JSON-RPC line filter: only lines starting with '{' are
      considered JSON-RPC messages. MCP does not use JSON-RPC batch
      arrays, so lines starting with '[' (e.g. `[INFO] ...` diagnostic
      output) are also dropped from the client stream.

CHANGELOG (v2.2)
    * Uses `read1()` instead of `read()` so the reader thread returns
      as soon as any data is available.

CHANGELOG (v2.1)
    * Server->LM channel is line-filtered: only JSON-RPC lines are
      forwarded; other lines are dropped but still logged.
"""

import os
import sys
import subprocess
import threading
from datetime import datetime


# ---------------------------------------------------------------------------
# Console setup (must run before anything writes to stdout or stderr)
# ---------------------------------------------------------------------------
def _setup_console() -> None:
    """
    Force UTF-8 encoding for stdout and stderr on Windows.

    Without this, log lines that contain non-ASCII characters (for
    example Windows paths with Chinese characters) can be garbled when
    the default console code page is GBK. On non-Windows platforms this
    function does nothing.
    """
    if sys.platform != "win32":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


_setup_console()


# ---------------------------------------------------------------------------
# Frozen-executable detection
# ---------------------------------------------------------------------------
def _is_frozen() -> bool:
    """
    Return True if the process is running from a frozen executable
    (PyInstaller one-dir or one-file, or Nuitka). Matches the logic
    used by mcp_server.py.
    """
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')


def _script_dir() -> str:
    """
    Return the directory where this script (or the frozen executable)
    lives. Used to place `proxy.log` next to the script.
    """
    if _is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


LOG_FILE = os.path.join(_script_dir(), "proxy.log")

BLOCK_SIZE = 4096
LOG_PREVIEW_BYTES = 128


def log(msg: str) -> None:
    """Write a timestamped line to stderr and to LOG_FILE."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _format_block(data: bytes) -> str:
    """Return a compact, log-friendly representation of a data block."""
    n = len(data)
    if n <= LOG_PREVIEW_BYTES:
        return f"[{n}B] {data!r}"
    return f"[{n}B] {data[:LOG_PREVIEW_BYTES]!r}... (truncated)"


def _is_json_rpc_line(line: bytes) -> bool:
    """
    Return True if the line looks like a JSON-RPC message.

    A JSON-RPC message is a JSON object, so it starts with '{'.
    Leading whitespace (spaces, tabs, CR) is skipped before the check.

    MCP does not use JSON-RPC batch arrays (which would start with '['),
    so we deliberately do NOT accept '[' as a marker. This prevents
    diagnostic lines like `[INFO] ...` from being mistaken for
    JSON-RPC messages.
    """
    stripped = line.lstrip(b' \t\r')
    if not stripped:
        return False
    return stripped[0:1] == b'{'


def _safe_read(source, size: int) -> bytes:
    """
    Read up to `size` bytes from a binary stream, returning as soon as
    any data is available.

    Uses `read1` when available (io.BufferedReader, io.FileIO, etc.),
    falling back to `os.read` on the underlying file descriptor. This
    avoids the classic `read(n)` blocking semantics that would stall a
    proxy when one side sends small messages (e.g. an MCP initialize
    handshake of a few hundred bytes).
    """
    read1 = getattr(source, 'read1', None)
    if read1 is not None:
        return read1(size)
    try:
        fd = source.fileno()
    except Exception:
        return source.read(size)
    try:
        return os.read(fd, size)
    except OSError:
        return b''


def pipe_reader(source, target, direction: str, json_filter: bool = False) -> None:
    """
    Forward data from `source` to `target`, logging each line.

    If `json_filter` is True, only lines that look like JSON-RPC
    messages are forwarded to `target`. Other lines are dropped from
    the forwarded stream but still logged.

    Broken pipes are treated as normal termination.
    """
    line_buffer = bytearray()

    def forward_line(line: bytes) -> None:
        if json_filter:
            if _is_json_rpc_line(line):
                log(f"{direction} -> {_format_block(line)}")
                try:
                    target.write(line)
                    target.flush()
                except BrokenPipeError:
                    raise
            else:
                log(f"{direction} (dropped, not JSON-RPC) -> {_format_block(line)}")
        else:
            log(f"{direction} -> {_format_block(line)}")
            try:
                target.write(line)
                target.flush()
            except BrokenPipeError:
                raise

    def flush_complete_lines() -> None:
        while True:
            nl = line_buffer.find(b'\n')
            if nl < 0:
                break
            line = bytes(line_buffer[:nl + 1])
            del line_buffer[:nl + 1]
            forward_line(line)

    try:
        while True:
            data = _safe_read(source, BLOCK_SIZE)
            if not data:
                break
            line_buffer.extend(data)
            flush_complete_lines()

        # Flush any trailing partial line (no trailing newline seen).
        if line_buffer:
            forward_line(bytes(line_buffer))
            line_buffer.clear()

    except BrokenPipeError:
        log(f"{direction} pipe closed by child")
    except Exception as e:
        log(f"{direction} pipe error: {e}")
    finally:
        log(f"{direction} pipe closed")


def main() -> None:
    if len(sys.argv) < 2:
        log("Usage: mcp_proxy.py <command> [args...]")
        sys.exit(1)

    real_cmd = sys.argv[1:]
    log(f"Starting real command: {' '.join(real_cmd)}")

    try:
        # NOTE: bufsize intentionally NOT set to 0 (see CHANGELOG v2.3).
        proc = subprocess.Popen(
            real_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            ),
        )
    except Exception as e:
        log(f"Failed to start child process: {e}")
        sys.exit(1)

    # LM->Server: client requests, always pure JSON-RPC. No filter.
    t1 = threading.Thread(
        target=pipe_reader,
        args=(sys.stdin.buffer, proc.stdin, "LM->Server", False),
        daemon=True,
    )
    # Server->LM: mcp_server stdout, contains JSON-RPC plus C-level
    # pollution from the LingoFuse native library. Enable filter.
    t2 = threading.Thread(
        target=pipe_reader,
        args=(proc.stdout, sys.stdout.buffer, "Server->LM", True),
        daemon=True,
    )
    # Server-ERR: diagnostics, forwarded unchanged.
    t3 = threading.Thread(
        target=pipe_reader,
        args=(proc.stderr, sys.stderr.buffer, "Server-ERR", False),
        daemon=True,
    )
    t1.start()
    t2.start()
    t3.start()

    try:
        rc = proc.wait()
        log(f"Real process exited with code {rc}")
    except KeyboardInterrupt:
        log("Proxy interrupted, terminating child...")
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass


if __name__ == "__main__":
    main()