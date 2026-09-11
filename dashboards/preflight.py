#!/usr/bin/env python3
"""Pre-demo preflight. Run this 10 minutes before you go on stage.

    python3 preflight.py                  # the default app, superstore-boards
    python3 preflight.py superstore-boards

Checks the whole chain the audience will exercise, in the order it breaks:
database up -> data present -> dash-server up -> credential valid -> app healthy
-> callbacks return real numbers -> filters bite -> latency acceptable.

Prints one line per check and a single GO / NO-GO at the end. Every failure line
says what to run to fix it, so there is nothing to remember under pressure.

Two deliberate design choices:

  * It REPAIRS the one thing that is known to rot on its own — dash-server's copy
    of the Exasol password, which a kit reinstall silently invalidates — rather
    than just reporting it. That failure has no demo-time workaround, so fixing it
    is strictly better than naming it.
  * The Ask panel is checked but NEVER fails the run. It calls the Anthropic API
    over the internet, so on venue wifi it is the first thing to go, and it is the
    one feature you can simply not click. Everything else is local.
"""
import ast
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

# --skip-ask drops the Anthropic round trip, which is 3-13s PER APP and the
# only network-dependent probe. Checking 11 apps with it on exceeded 600s;
# without it the same sweep is a few seconds. Use it for bulk sweeps, and
# run once WITHOUT it on the app you actually intend to demo.
SKIP_ASK = "--skip-ask" in sys.argv
APPS = [a for a in sys.argv[1:] if not a.startswith("--")] or ["retail-finance"]


def discover_personas(app):
    """The persona keys THIS app actually registers, read from its own app.py.

    This used to be the literal ["ops", "category"], which are superstore-personas'
    keys. Every other persona app in this tree registers different ones, and an
    unknown persona value does not fail: app.py falls back to DEFAULT_PERSONA, so
    the callback returns the default board and preflight reports PASS twice for a
    board it never rendered. A five-persona app was verified as though it had one.

    Parsed with ast rather than imported: importing app.py pulls in dash and
    plotly and runs module-level configure(), which is a lot of machinery to load
    to read five dict keys.
    """
    source = pathlib.Path(__file__).resolve().parent / app / "app.py"
    if not source.exists():
        return [None]
    try:
        tree = ast.parse(source.read_text())
    except SyntaxError:
        return [None]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "PERSONAS" not in names or not isinstance(node.value, ast.Dict):
            continue
        keys = [k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if keys:
            return keys
    return [None]
PORT = 5100
MCP = f"http://127.0.0.1:{PORT}/mcp"
HOME = pathlib.Path.home()
# Everything this script reaches for lives beside it. It used to be hardcoded to
# ~/exasol-recipes, which silently skipped the fact-table check (the app.py it
# looked for did not exist) and pointed every repair hint at a path a cloned
# checkout does not have.
REPO = pathlib.Path(__file__).resolve().parent

PASS, FAIL, WARN, INFO = "  PASS ", "  FAIL ", "  WARN ", "  ---- "
problems = []
warnings = []


def line(mark, label, detail=""):
    print(f"{mark} {label:<34} {detail}")


def bad(label, detail, fix):
    line(FAIL, label, detail)
    problems.append((label, fix))


def warn(label, detail, note=""):
    line(WARN, label, detail)
    warnings.append((label, note))


def mcp(name, args, timeout=300):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(MCP, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode()
    for ln in raw.splitlines():
        if ln.startswith("data: "):
            raw = ln[6:]
    payload = json.loads(raw)
    if "error" in payload:
        return "", {}
    text = "\n".join(c.get("text", "") for c in payload["result"].get("content", []))
    result = json.loads(text[text.find("Result:") + 7:]) if "Result:" in text else {}
    return text.split("\n", 1)[0], result


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


# ---------------------------------------------------------------- 1. database
print("\n=== 1. database ===")
try:
    out = subprocess.run([str(HOME / ".local/bin/exakit"), "status"],
                         capture_output=True, text=True, timeout=120).stdout
    if "running" in out.lower():
        line(PASS, "Exasol running")
    else:
        bad("Exasol not running", out.strip().splitlines()[-1] if out.strip() else "",
            "~/.local/bin/exakit start")
except Exception as exc:
    bad("Exasol status", str(exc)[:70], "~/.local/bin/exakit start")

# Row count through exapump: independent of dash-server, so a failure here is
# unambiguously the database and not the web tier.
#
# The table is read from each app's own `SCHEMA, TABLE = ...` line rather than
# hardcoded. It used to probe STARTER_KIT.GLOBAL_SUPERSTORE for every run; a kit
# reinstall drops that table, so every preflight of every OTHER app reported a
# blocking NO-GO for a table that app never touches. A fixture nobody can satisfy
# trains you to ignore the gate.
def _fact_tables(apps):
    """(schema, table) for each requested app, in order, de-duplicated."""
    seen, out = set(), []
    for app in apps:
        src = REPO / app / "app.py"
        if not src.exists():
            continue
        m = re.search(r'^SCHEMA,\s*TABLE\s*=\s*["\']([^"\']+)["\']\s*,\s*'
                      r'["\']([^"\']+)["\']', src.read_text(), re.M)
        if m and m.groups() not in seen:
            seen.add(m.groups()); out.append(m.groups())
    return out

for _schema, _table in _fact_tables(APPS) or [("STARTER_KIT", "WALMART_RETAIL")]:
    fq = f"{_schema}.{_table}"
    try:
        out = subprocess.run(
            [str(HOME / ".local/bin/exapump"), "sql", "-p", "starter-kit",
             f'SELECT COUNT(*) AS N FROM {fq}'],
            capture_output=True, text=True, timeout=180)
        digits = [int(t) for t in out.stdout.replace(",", " ").split()
                  if t.isdigit()]
        rows = max(digits) if digits else 0
        if rows:
            line(PASS, f"{_table} rows", f"{rows:,}")
        else:
            bad(f"{_table} unreadable", (out.stderr or out.stdout)[-90:].strip(),
                "check the table exists and the starter-kit exapump profile is valid")
    except Exception as exc:
        bad(f"{_table} row count", str(exc)[:70], "~/.local/bin/exakit start")

# ------------------------------------------------------------- 2. dash-server
print("\n=== 2. dash-server ===")
try:
    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=20).read(1)
    line(PASS, "dash-server responding", f"port {PORT}")
except Exception as exc:
    bad("dash-server down", str(exc)[:70],
        "start dash-server, then re-run this preflight")

# The stale-secret failure: repair rather than report. A kit reinstall rotates the
# database password and leaves dash-server's copy behind; the resulting error is
# labelled "tls_required" even though the real cause is a rejected password.
head, res = mcp("exasol_profile_validate", {"name": "starter-kit"})
if res.get("connection_test", {}).get("status") in ("succeeded", "passed"):
    line(PASS, "Exasol credential valid")
else:
    line(INFO, "credential stale, repairing", "(known: kit reinstall rotates it)")
    fix = REPO / "fix_dash_profile.py"
    subprocess.run([sys.executable, str(fix)], capture_output=True, text=True,
                   timeout=180)
    _, res = mcp("exasol_profile_validate", {"name": "starter-kit"})
    if res.get("connection_test", {}).get("status") in ("succeeded", "passed"):
        line(PASS, "Exasol credential repaired")
    else:
        bad("Exasol credential invalid",
            str(res.get("connection_test", {}).get("error", ""))[:70],
            f"python3 {REPO / 'fix_dash_profile.py'}")

# ------------------------------------------------------------------- 3. apps
for app in APPS:
    print(f"\n=== 3. app: {app} ===")
    base = f"http://127.0.0.1:{PORT}/apps/{app}"
    redeploy = f"python3 {REPO / 'deploy_dashboard.py'} {REPO / app}"

    _, health = mcp("app_run_healthcheck", {"name": app, "target": "live"})
    probes = health.get("health", {}).get("probes", [])
    failed = [p.get("name") for p in probes if p.get("status") == "failed"]
    if probes and not failed:
        line(PASS, "health probes", f"{len(probes)} probes")
    elif failed:
        bad("health probes", ", ".join(failed), redeploy)
    else:
        bad("healthcheck returned nothing", "app may not be deployed", redeploy)

    # Callbacks. Health probes pass on a page whose callbacks raise, so this is
    # the check that actually matters: fire the real callback, read real numbers.
    try:
        deps = json.loads(urllib.request.urlopen(
            base + "/_dash-dependencies", timeout=60).read())
        multi = [d for d in deps if d["output"].startswith("..")]
        # Pick the callback that CARRIES a kpi/insight output, not merely the one
        # with the most outputs. On student-performance the filters callback also
        # has 8 outputs and won the tie, so this reported "no KPI tiles rendered"
        # for an app that was working perfectly. Fall back to widest only if no
        # callback names a kpi/insight output.
        named = [d for d in multi
                 if any(s.split(".")[0].startswith(("kpi", "insight"))
                        for s in d["output"].strip(".").split("..."))]
        pool = named or multi
        cb = max(pool, key=lambda d: len(d["output"].strip(".").split("...")))
        key = cb["output"]
        outs = [{"id": s.split(".")[0], "property": s.split(".")[1]}
                for s in key.strip(".").split("...")]
        has_persona = any(i["id"] == "persona" for i in cb["inputs"])
        personas = discover_personas(app) if has_persona else [None]

        for persona in personas:
            timings = []
            for _ in range(3):
                ins = [{"id": i["id"], "property": i["property"],
                        "value": persona if i["id"] == "persona" else None}
                       for i in cb["inputs"]]
                req = urllib.request.Request(
                    base + "/_dash-update-component",
                    data=json.dumps({"output": key, "outputs": outs, "inputs": ins,
                                     "changedPropIds":
                                         [f"{ins[0]['id']}.{ins[0]['property']}"]}
                                    ).encode(),
                    headers={"Content-Type": "application/json"})
                t0 = time.time()
                resp = json.loads(urllib.request.urlopen(req, timeout=300).read())["response"]
                timings.append((time.time() - t0) * 1000)

            tag = f"callbacks [{persona}]" if persona else "callbacks"
            kpi_node = next((resp[k] for k in resp if k.startswith("kpi")), None)
            cards = texts(kpi_node["children"], []) if kpi_node else []
            pairs = [f"{cards[i]}={cards[i + 1]}"
                     for i in range(0, max(0, len(cards) - 2), 3)]
            empty = [p for p in pairs if p.endswith(("=0", "=$0", "=0.0%", "=n/a"))]

            figs = [k for k in resp if k.startswith("fig")]
            blank = [k for k in figs
                     if not resp[k].get("figure", {}).get("data")]

            if not pairs:
                bad(tag, "no KPI tiles rendered", redeploy)
            elif empty:
                bad(tag, f"zero-valued tiles: {', '.join(empty)}", redeploy)
            elif blank:
                bad(tag, f"empty charts: {', '.join(blank)}", redeploy)
            else:
                line(PASS, tag, " | ".join(pairs[:3]))
                line(INFO, f"  latency [{persona or 'main'}]",
                     f"median {sorted(timings)[1]:.0f} ms  max {max(timings):.0f} ms")
                if max(timings) > 4000:
                    warn(f"slow callback [{persona}]", f"{max(timings):.0f} ms",
                         "warm it by clicking each tab once before you present")

        # Filters must actually narrow the result, or the demo's best moment is a
        # dropdown that visibly does nothing.
        fkeys = [i["id"] for i in cb["inputs"] if i["id"].startswith("filter-")]
        if fkeys:
            fopts = [d for d in deps if fkeys[0] in d["output"]]
            if fopts:
                fk = fopts[0]["output"]
                fouts = [{"id": s.split(".")[0], "property": s.split(".")[1]}
                         for s in fk.strip(".").split("...")]
                req = urllib.request.Request(
                    base + "/_dash-update-component",
                    data=json.dumps({"output": fk, "outputs": fouts,
                                     "inputs": [{"id": "boot",
                                                 "property": "n_intervals",
                                                 "value": 1}],
                                     "changedPropIds": ["boot.n_intervals"]}).encode(),
                    headers={"Content-Type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=120).read())["response"]
                counts = {k: len(v.get("options", [])) for k, v in r.items()}
                if all(counts.values()):
                    line(PASS, "filter dropdowns populated",
                         ", ".join(f"{k.replace('filter-', '')}:{v}"
                                   for k, v in counts.items()))
                else:
                    bad("filter dropdowns empty",
                        ", ".join(k for k, v in counts.items() if not v), redeploy)
    except urllib.error.HTTPError as exc:
        bad("callbacks raised", f"HTTP {exc.code}",
            f"python3 -c \"import json,urllib.request;"
            f"print(1)\"  # then: {redeploy}")
    except Exception as exc:
        bad("callbacks", f"{type(exc).__name__}: {str(exc)[:60]}", redeploy)

    # Ask panel: reported, never fatal. Needs the internet; you can decline to
    # click it, and nothing else on the page depends on it.
    try:
        ask = [] if SKIP_ASK else [d for d in deps if "q-out" in d["output"]]
        if SKIP_ASK:
            print(f"{INFO} Ask panel                        skipped (--skip-ask)")
        if ask:
            acb = ask[0]
            ins = [{"id": i["id"], "property": i["property"],
                    "value": 1 if i["id"] == "q-run" else None}
                   for i in acb["inputs"]]
            st = [{"id": s["id"], "property": s["property"],
                   "value": "total profit by market" if s["id"] == "q-input" else None}
                  for s in acb.get("state", [])]
            body = {"output": acb["output"],
                    "outputs": {"id": "q-out", "property": "children"},
                    "inputs": ins, "changedPropIds": ["q-run.n_clicks"]}
            if st:
                body["state"] = st
            req = urllib.request.Request(base + "/_dash-update-component",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            t0 = time.time()
            raw = urllib.request.urlopen(req, timeout=120).read().decode()
            took = time.time() - t0
            if "row(s)" in raw or "SELECT" in raw:
                line(PASS, "Ask panel (needs internet)", f"answered in {took:.1f}s")
            else:
                warn("Ask panel returned no rows", f"{took:.1f}s",
                     "avoid the Ask panel, or fix the API key; nothing else needs it")
    except Exception as exc:
        warn("Ask panel unavailable", f"{type(exc).__name__}",
             "avoid the Ask panel on stage; the rest of the page is fully local")

# ------------------------------------------------------------------ verdict
print("\n" + "=" * 62)
if problems:
    print(f"NO-GO — {len(problems)} blocking issue(s)\n")
    for label, fix in problems:
        print(f"  {label}\n      fix: {fix}")
else:
    print("GO — every local check passed")
for label, note in warnings:
    print(f"\n  warning: {label}" + (f"\n      {note}" if note else ""))
if not problems:
    print(f"\n  {', '.join(APPS)}")
    print(f"  http://127.0.0.1:{PORT}/apps/{APPS[0]}")
    print("\n  Fallback if anything dies mid-demo: open the static snapshot in")
    print("  ~/demo-fallback/ — it is a plain HTML file, no database needed.")
print("=" * 62)
sys.exit(1 if problems else 0)
