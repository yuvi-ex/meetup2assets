#!/bin/sh
# Dry run, then deploy only if every contract holds.
#
#   sh ship.sh superstore-boards
#   sh ship.sh                                  # every recipe with an app.py
#
# WHY THE DRY RUN COMES FIRST. Every bug that cost a deploy revision on this repo
# was a contract violation that health probes pass over: an unknown insight tone
# (HTTP 500), figure keys share_html ignores (charts silently missing), `<> ''` in
# a filters query (empty dropdowns). dryrun.py catches those in ~1-3s against live
# data, so a broken build never reaches a deploy at all.
#
# ONE RECIPE'S FAILURE MUST NOT ABORT THE REST. This script used to run under
# `set -e`, so `sh ship.sh` with no arguments died at the first recipe whose table
# no longer exists (`products`, `store-sales`) and silently skipped everything
# after it — alphabetically that is most of them. Each recipe is now independent
# and the summary at the end is the verdict; the exit code is non-zero if any
# recipe failed.
#
# DASH_SERVER_PORT is set because deploy_dashboard.py's port() otherwise shells out
# to `exakit info --json` TWICE per deploy, at ~0.7s each, then falls through to
# probing ports anyway because newer kit builds no longer emit JSON there.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# The interpreter that has plotly/dash; the system python3 does not. dash-server
# installs to one of two places depending on how the add-on was set up, and this
# was hardcoded to whichever one happened to exist on the author's laptop -- on a
# fresh clone that is a "No such file or directory" with nothing explaining it.
# Pick the first that exists and say so plainly if neither does.
VENV=""
for c in "$HOME/.exasol-starter-kit/dash-server-venv/bin/python3" \
         "$HOME/dash-server/.venv/bin/python3"; do
  [ -x "$c" ] && VENV="$c" && break
done
if [ -z "$VENV" ]; then
  echo "error: no dash-server python found. Is the add-on installed?" >&2
  echo "  EXAKIT_MARKETPLACE_ADDONS=dash-server exakit marketplace" >&2
  exit 1
fi
export DASH_SERVER_PORT="${DASH_SERVER_PORT:-5100}"

# With no arguments, redeploy only apps that are ALREADY LIVE. Looping over every
# recipe on disk silently ADDED `tpch` and `tpch-sales` to the app list — two older
# boards deliberately left undeployed — which is the last thing you want happening
# to the list you are about to show an audience. Pass --all to include every recipe
# on disk, new ones included.
ALL=0
ARGS=""
for a in "$@"; do
  case "$a" in
    --all) ALL=1 ;;
    *) ARGS="$ARGS $a" ;;
  esac
done

if [ -n "$(printf %s "$ARGS" | tr -d ' ')" ]; then
  RECIPES="$ARGS"
elif [ "$ALL" = "1" ]; then
  RECIPES=$(cd "$HERE" && for d in */app.py; do printf '%s ' "${d%/app.py}"; done)
else
  RECIPES=$(python3 - <<'PYEOF'
import json, urllib.request
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "apps_list", "arguments": {}}}).encode()
req = urllib.request.Request("http://127.0.0.1:5100/mcp", data=body, headers={
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"})
raw = urllib.request.urlopen(req, timeout=60).read().decode()
for ln in raw.splitlines():
    if ln.startswith("data: "):
        raw = ln[6:]
text = "\n".join(c.get("text", "")
                 for c in json.loads(raw)["result"].get("content", []))
apps = json.loads(text[text.find("Result:") + 7:]).get("apps", [])
print(" ".join(sorted(a.get("name", "") for a in apps if a.get("name"))))
PYEOF
)
  echo "(no recipe named; redeploying the $(printf %s "$RECIPES" | wc -w | tr -d ' ') LIVE apps — pass --all for every recipe on disk)"
  echo
fi

SHIPPED=""
BLOCKED=""
FAILED=""

for name in $RECIPES; do
  echo "######## $name ########"
  if ! "$VENV" "$HERE/dryrun.py" "$HERE/$name"; then
    echo "  -> BLOCKED: contracts failed, not deploying $name"
    BLOCKED="$BLOCKED $name"
    echo
    continue
  fi
  if python3 "$HERE/deploy_dashboard.py" "$HERE/$name" \
       | grep -E 'deploy |live KPIs|Dashboard ready'; then
    SHIPPED="$SHIPPED $name"
  else
    echo "  -> FAILED during deploy: $name"
    FAILED="$FAILED $name"
  fi
  echo
done

echo "======== summary ========"
[ -n "$SHIPPED" ] && echo "  shipped :$SHIPPED"
[ -n "$BLOCKED" ] && echo "  blocked :$BLOCKED   (dry run refused — fix contracts)"
[ -n "$FAILED"  ] && echo "  failed  :$FAILED   (deploy itself errored)"
[ -z "$BLOCKED$FAILED" ] && echo "  all clean"
[ -n "$BLOCKED$FAILED" ] && exit 1
exit 0
