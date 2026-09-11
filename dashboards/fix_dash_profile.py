#!/usr/bin/env python3
"""Re-point dash-server's `starter-kit` Exasol profile at the current password.

    python3 fix_dash_profile.py

WHY THIS EXISTS. dash-server keeps its OWN copy of the mcp_readonly secret, in its
own local secret store, separate from the kit's ~/.exasol-starter-kit/credentials.
A kit reinstall rotates the database password but leaves dash-server's copy behind,
so every deploy then fails at the first step with

    Exasol profile validation failed for starter-kit.

and the underlying error is reported as error_class "tls_required" even though the
real message is "authentication failed" — which sends you chasing a TLS problem
that does not exist. This script copies the kit's current password into
dash-server's profile and re-validates.

Reads the password from the kit's credential file at run time; the secret is never
written to disk anywhere else, and is not echoed.
"""
import json
import pathlib
import sys
import urllib.request

MCP = "http://127.0.0.1:5100/mcp"
CRED = pathlib.Path.home() / ".exasol-starter-kit/credentials/mcp_readonly_password"


def call(name, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(MCP, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode()
    for line in raw.splitlines():
        if line.startswith("data: "):
            raw = line[6:]
    payload = json.loads(raw)
    if "error" in payload:
        raise SystemExit(f"{name} failed: {json.dumps(payload['error'])[:400]}")
    text = "\n".join(c.get("text", "") for c in payload["result"].get("content", []))
    result = json.loads(text[text.find("Result:") + 7:]) if "Result:" in text else {}
    return text.split("\n", 1)[0], result


def main():
    if not CRED.exists():
        raise SystemExit(f"missing {CRED} — is the starter kit installed?")
    password = CRED.read_text().strip()
    if not password:
        raise SystemExit(f"{CRED} is empty")

    head, _ = call("exasol_profile_create_local", {
        "name": "starter-kit", "backend": "onprem", "credential_mode": "password",
        "dsn": "127.0.0.1:8563", "user": "mcp_readonly",
        "description": "Exasol Personal Local Starter Kit (read-only)",
        # The kit's server certificate is self-signed, so verification must stay off
        # for this profile — the same reason ~/.exapump/config.toml carries
        # validate_certificate = false.
        "tls_verify": False, "overwrite": True,
        "secret_value": password,
    })
    print(f"profile write : {head}")

    head, result = call("exasol_profile_validate", {"name": "starter-kit"})
    print(f"validate      : {head}")
    test = result.get("connection_test", {})
    print(f"connection    : {test.get('status')}")
    # dash-server reports "succeeded" here, not "passed" — accept either rather
    # than the one this was first written against.
    if test.get("status") not in ("succeeded", "passed"):
        print(json.dumps(test, indent=2)[:800])
        return 1
    print("\nstarter-kit profile is good. Now deploy:")
    here = pathlib.Path(__file__).resolve().parent
    print(f"  python3 {here / 'deploy_dashboard.py'} {here / 'superstore-boards'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
