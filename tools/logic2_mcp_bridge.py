#!/usr/bin/env python3
"""
Saleae Logic 2 MCP Stdio-to-HTTP Bridge for Antigravity AI Agent
Bridges standard stdio MCP protocol (stdin/stdout) to Saleae Logic 2's HTTP MCP Server (http://127.0.0.1:10530/).
Zero external dependencies, works with standard Python 3.
"""

import sys
import json
import urllib.request
import urllib.error

LOGIC2_MCP_URL = "http://127.0.0.1:10530/"

def main():
    # Force UTF-8 on Windows
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    sys.stderr.write(f"[Logic2-MCP-Bridge] Started, forwarding to {LOGIC2_MCP_URL}\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip().lstrip('\ufeff')
        if not line:
            continue

        try:
            payload = json.loads(line)
        except Exception as e:
            sys.stderr.write(f"[Logic2-MCP-Bridge] Invalid JSON: {e}\n")
            continue

        is_notification = ("id" not in payload) or (payload.get("id") is None)
        req_id = payload.get("id")

        is_wait_capture = False
        if payload.get("method") == "tools/call" and payload.get("params", {}).get("name") == "wait_capture":
            is_wait_capture = True

        call_timeout = 600 if is_wait_capture else 45

        try:
            req_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                LOGIC2_MCP_URL,
                data=req_bytes,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=call_timeout) as resp:
                resp_bytes = resp.read()
                if not is_notification:
                    resp_str = resp_bytes.decode("utf-8").strip()
                    if resp_str:
                        sys.stdout.write(resp_str + "\n")
                        sys.stdout.flush()
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            sys.stderr.write(f"[Logic2-MCP-Bridge] HTTP Error {he.code}: {err_body}\n")
            if not is_notification:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": f"Logic 2 MCP HTTP {he.code}: {err_body or he.reason}"
                    }
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
        except Exception as ex:
            sys.stderr.write(f"[Logic2-MCP-Bridge] Connection error: {ex}\n")
            if not is_notification:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": f"Logic 2 MCP connection failed: {ex}. Ensure Logic 2 is running and MCP Server is enabled."
                    }
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()

if __name__ == "__main__":
    main()
