# -*- coding: utf-8 -*-
"""MCP stdio probe for quark-nd-mcp.
Usage: python mcp_probe.py [tool_name] [json_args]
Example: python mcp_probe.py list_files "{\"path\": \"/\"}"
"""
import json
import subprocess
import sys
import time

TARGET = r"C:\creategame\AI学\tools\quark-nd-mcp\bin\quark-nd-mcp.exe"


def send(proc, obj):
    line = json.dumps(obj, ensure_ascii=False)
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def read_response(proc, req_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print("[non-json line]", line[:200], file=sys.stderr)
            continue
        if msg.get("method") == "notifications/message":
            print("[server msg]", msg.get("params", {}).get("message"), file=sys.stderr)
            continue
        if msg.get("id") == req_id:
            return msg
    return {"error": {"message": "response timeout"}}

def main():
    tool = sys.argv[1] if len(sys.argv) > 1 else "list_files"
    args_raw = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        args = json.loads(args_raw) if args_raw.strip() else {"path": "/"}
    except json.JSONDecodeError:
        # tolerate shell quoting mangling: fall back to defaults
        args = {"path": "/"}
        print("[warn] args parse failed, using defaults", file=sys.stderr)

    proc = subprocess.Popen(
        [TARGET],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    send(proc, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hana-probe", "version": "1.0"},
        },
    })
    init = read_response(proc, 1)
    print("[initialize]", json.dumps(init, ensure_ascii=False)[:500])

    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    send(proc, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    })
    result = read_response(proc, 2)
    print("[result]", json.dumps(result, ensure_ascii=False)[:3000])

    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

if __name__ == "__main__":
    main()