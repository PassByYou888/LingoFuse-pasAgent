#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_proxy.py - Transparently forward stdio communication between LM Studio and mcp_server.py

Usage: python mcp_proxy.py <real_command_and_arguments>
Example: python mcp_proxy.py python D:/mcp_tool/mcp_server.py

All communication will be logged to proxy.log and stderr (visible in LM Studio logs).
"""
import sys
import os
import subprocess
import threading
import time
import signal
from datetime import datetime

LOG_FILE = "proxy.log"

def log(msg):
    """Log message: output to stderr and file simultaneously"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    # Print to stderr (LM Studio will capture it)
    print(line, file=sys.stderr, flush=True)
    # Write to file
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def pipe_reader(source, target, direction):
    """Read data from one stream and write to another, logging each byte"""
    try:
        while True:
            data = source.read(1)  # Read byte by byte to ensure immediate forwarding
            if not data:
                break
            # Log (show in printable form)
            log(f"{direction} -> {repr(data)}")
            target.write(data)
            target.flush()
    except Exception as e:
        log(f"{direction} pipe error: {e}")
    finally:
        log(f"{direction} pipe closed")

def main():
    if len(sys.argv) < 2:
        log("Usage: mcp_proxy.py <command> [args...]")
        sys.exit(1)

    real_cmd = sys.argv[1:]
    log(f"Starting real command: {real_cmd}")

    # Launch child process with pipes
    proc = subprocess.Popen(
        real_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )

    # Start three bidirectional pipe threads
    t1 = threading.Thread(target=pipe_reader, args=(sys.stdin.buffer, proc.stdin, "LM->Server"))
    t2 = threading.Thread(target=pipe_reader, args=(proc.stdout, sys.stdout.buffer, "Server->LM"))
    t3 = threading.Thread(target=pipe_reader, args=(proc.stderr, sys.stderr.buffer, "Server-ERR"))

    t1.daemon = True
    t2.daemon = True
    t3.daemon = True
    t1.start()
    t2.start()
    t3.start()

    # Wait for child process to exit
    try:
        rc = proc.wait()
        log(f"Real process exited with code {rc}")
    except KeyboardInterrupt:
        log("Proxy interrupted, terminating child...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    # Register signal handler to ensure clean exit
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    main()