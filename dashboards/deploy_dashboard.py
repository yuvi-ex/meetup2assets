#!/usr/bin/env python3
"""Deploy a dash-server dashboard from a recipe directory.

    python3 deploy_dashboard.py superstore-boards

The recipe dir supplies dashboard.json (name/title/profile), app.py,
queries/business/*.sql and queries/sql_smoke.json.

Idempotent: creates the app if missing, otherwise just replaces its files and
redeploys. Reads the real dash-server port from `exakit info --json` — the
installer moves off 5100 when something already holds it.
"""
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

# Recipe directory is argv[1]; its dashboard.json names the app.
HERE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
_CFG = json.loads((HERE / "dashboard.json").read_text())
APP = os.environ.get("DASH_APP_NAME", _CFG["name"])
TITLE = _CFG.get("title", APP)
PROFILE = _CFG.get("profile", "starter-kit")   # kit-created, bound to mcp_readonly
EXAKIT = pathlib.Path.home() / ".local/bin/exakit"


def port():
    """Resolve the dash-server port.

    The kit used to publish this in `exakit info --json`. Newer kit builds dropped
    both the JSON flag and the dash_server component (it is a marketplace add-on
    and the marketplace command is gone), so `info` returns a text box and this
    raised JSONDecodeError. Fall back to DASH_SERVER_PORT, then to probing the
    ports the installer uses, so the script keeps working on both kit generations.
    """
    if os.environ.get("DASH_SERVER_PORT"):
        return int(os.environ["DASH_SERVER_PORT"])
    out = subprocess.run([str(EXAKIT), "info", "--json"],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(out)["components"]["dash_server"]["port"]
    except (ValueError, KeyError, TypeError):
        pass
    for candidate in (5100, 5101, 5102):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{candidate}/", timeout=3).read(1)
            return candidate
        except Exception:
            continue
    raise SystemExit("cannot find dash-server; set DASH_SERVER_PORT")


def call(name, args, url):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(req, timeout=600).read().decode()
    for line in raw.splitlines():
        if line.startswith("data: "):
            raw = line[6:]
    payload = json.loads(raw)
    if "error" in payload:
        raise SystemExit(f"{name} failed: {payload['error']}")
    text = "\n".join(c.get("text", "") for c in payload["result"].get("content", []))
    head = text.split("\n", 1)[0]
    body_json = json.loads(text[text.find("Result:") + 7:]) if "Result:" in text else {}
    return head, body_json


def main():
    mcp = f"http://127.0.0.1:{port()}/mcp"
    print(f"control plane: {mcp}")

    head, _ = call("exasol_profile_validate", {"name": PROFILE}, mcp)
    print(f"profile      : {head}")

    _, inventory = call("apps_list", {}, mcp)
    existing = {a.get("name") for a in inventory.get("apps", [])}

    # harness.py is shared: one master copy beside this script, pushed into every
    # app workspace so a formatter fix lands in all dashboards on redeploy.
    root = pathlib.Path(__file__).resolve().parent
    files = [{"path": "app.py", "content": (HERE / "app.py").read_text()},
             {"path": "queries/sql_smoke.json",
              "content": (HERE / "queries/sql_smoke.json").read_text()}]
    # Two shared modules live beside this script, and a recipe imports whichever it
    # is built on: harness.py is the plain look, board.py the persona-metrics look
    # with the Share snapshot. Both are pushed when present so a fix to either lands
    # in every dashboard on redeploy — do not edit the copy inside an app workspace.
    for shared in ("harness.py", "board.py"):
        if (root / shared).exists():
            files.append({"path": shared, "content": (root / shared).read_text()})
    for sql in sorted((HERE / "queries/business").glob("*.sql")):
        files.append({"path": f"queries/business/{sql.name}", "content": sql.read_text()})

    # Any other top-level module the recipe ships alongside app.py (e.g. llm_sql.py
    # for the Ask-the-data panel). app.py is already added and harness.py comes from
    # the master copy above, so both are excluded here.
    for module in sorted(HERE.glob("*.py")):
        if module.name in ("app.py", "harness.py", "board.py"):
            continue
        files.append({"path": module.name, "content": module.read_text()})

    # A recipe-supplied requirements.txt means the app needs packages the
    # dash-server venv does not carry. That install is cached, so a changed
    # requirements.txt only takes effect with force_clean on the deploy below.
    requirements = HERE / "requirements.txt"
    if requirements.exists():
        files.append({"path": "requirements.txt", "content": requirements.read_text()})

    if APP not in existing:
        # Scaffold first: it writes dash-app.json, requirements.txt and the
        # dash_server_exasol.py helper that app.py imports. Our files then replace
        # the generated app.py and placeholder SQL.
        head, _ = call("app_create_exasol_dashboard",
                       {"name": APP, "profile_name": PROFILE, "title": TITLE}, mcp)
        print(f"scaffold     : {head}")
        for dead in ("queries/system/meta.sql", "queries/system/monitor.sql",
                     "queries/system/usage.sql", "queries/system/sql_hist.sql",
                     "queries/business/summary.sql"):
            call("app_delete_file", {"name": APP, "path": dead}, mcp)

    # The title shown on the Dashboards index and in the browser tab comes from the
    # SERVER's dash-app.json, which the scaffold wrote once at create time — not from
    # app.py. So a renamed dashboard.json title has no visible effect until that file
    # is updated. Only the title key is touched, so the scaffold's profile binding in
    # data_sources survives.
    _, current = call("app_read_file", {"name": APP, "path": "dash-app.json"}, mcp)
    manifest_raw = current.get("content") if isinstance(current, dict) else None
    if manifest_raw:
        manifest = json.loads(manifest_raw)
        if manifest.get("title") != TITLE:
            print(f"title        : {manifest.get('title')!r} -> {TITLE!r}")
            manifest["title"] = TITLE
            files.append({"path": "dash-app.json",
                          "content": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"})

    head, _ = call("app_put_files", {"name": APP, "files": files}, mcp)
    print(f"files        : {head} ({len(files)} files)")

    head, _ = call("app_validate", {"name": APP}, mcp)
    print(f"validate     : {head}")

    head, _ = call("app_deploy_draft",
                   {"name": APP, "deployment_target": "live",
                    "auto_rollback_on_health_failure": True,
                    "force_clean": (HERE / "requirements.txt").exists()}, mcp)
    print(f"deploy       : {head}")

    _, health = call("app_run_healthcheck", {"name": APP, "target": "live"}, mcp)
    probes = health.get("health", {}).get("probes", [])
    bad = [p for p in probes if p.get("status") == "failed"]
    for p in probes:
        print(f"  {p.get('status'):16} {p.get('name')}")
    if bad:
        raise SystemExit(f"healthcheck FAILED: {[p.get('name') for p in bad]}")

    url = f"http://127.0.0.1:{port()}/apps/{APP}"
    verify(url)
    print(f"\nDashboard ready: {url}")


def verify(base):
    """Prove the callbacks return data — healthcheck alone does not.

    NOTE: Dash's multi-output key joins entries with THREE dots and wraps in two
    (`..a.children...b.figure..`). Always read it from _dash-dependencies; hand
    -composing it with '..' yields a 500 that looks like an app bug but is not.
    """
    deps = json.loads(urllib.request.urlopen(base + "/_dash-dependencies", timeout=60).read())
    # The main refresh callback is the multi-output one with the most outputs. Chosen
    # structurally rather than by a hardcoded id: this used to look for "..kpi-row",
    # which only matched recipes that happened to name that component the same way.
    multi = [d for d in deps if d["output"].startswith("..")]
    if not multi:
        raise SystemExit("no multi-output callback found in _dash-dependencies")
    # Prefer the callback that CARRIES a kpi/insight output. Widest-wins alone ties
    # with the filters callback on some recipes (student-performance has 8 outputs
    # in each) and then verifies the wrong thing entirely.
    named = [d for d in multi
             if any(s.split(".")[0].startswith(("kpi", "insight"))
                    for s in d["output"].strip(".").split("..."))]
    main_cb = max(named or multi,
                  key=lambda d: len(d["output"].strip(".").split("...")))
    key = main_cb["output"]
    outs = [{"id": s.split(".")[0], "property": s.split(".")[1]}
            for s in key.strip(".").split("...")]
    # Input ids come from the dependency graph, not a hardcoded list. They used to
    # be store-sales' own filter names, which meant this check only ever passed for
    # that one recipe -- every other dashboard got an IndexError from deep inside
    # Dash's _prepare_callback, which reads like an app bug but is just a callback
    # whose inputs did not match.
    ins = [{"id": i["id"], "property": i["property"], "value": None}
           for i in main_cb["inputs"]]
    payload = {"output": key, "outputs": outs, "inputs": ins,
               "changedPropIds": [f"{ins[0]['id']}.{ins[0]['property']}"]}
    req = urllib.request.Request(base + "/_dash-update-component",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=300).read())["response"]

    def texts(node, out):
        if isinstance(node, dict):
            child = node.get("props", {}).get("children")
            if isinstance(child, str):
                out.append(child)
            else:
                texts(child, out)
        elif isinstance(node, list):
            for item in node:
                texts(item, out)
        return out

    # Component ids differ per recipe, so find them by prefix rather than by name.
    def pick(*prefixes):
        for candidate in resp:
            if candidate.startswith(prefixes):
                return resp[candidate]
        return None

    kpi_node = pick("kpi")
    if kpi_node:
        cards = texts(kpi_node["children"], [])
        print("\nlive KPIs    : " + " | ".join(
            f"{cards[i]}={cards[i + 1]}" for i in range(0, len(cards) - 2, 3)))
    insight_node = pick("insight")
    if insight_node:
        print("live insights:")
        for card in insight_node["children"]:
            parts = [t for t in texts(card, []) if t.strip()]
            if parts:
                print(f"  {parts[0][:70]}")


if __name__ == "__main__":
    sys.exit(main())
