#!/usr/bin/env bash
# Run this the morning of the meetup. Every check is a thing that has actually
# broken a run before.
#
# THIS IS A GATE, NOT A REPORT. It previously printed values without testing
# them -- most memorably `ok  ssh port null` on a deployment where ssh was
# impossible, which is the one check that would have caught the whole failure.
# Anything that will stop a step now DIES here, in seconds, with the command
# that fixes it. Anything merely slow or first-run warns instead.
#
#   ./00_preflight.sh              check and stop at the first blocker
#   ./00_preflight.sh --warn-only  report everything, never exit non-zero
SHOW_SQL=0   # this is a morning check, not the talk: keep the output scannable
source "$(dirname "$0")/lib/common.sh"

WARN_ONLY=0
[[ "${1:-}" == "--warn-only" ]] && WARN_ONLY=1

# In --warn-only mode a blocker is reported and the run continues, so a presenter
# can see EVERY problem in one pass rather than fixing them one restart at a time.
FAILED=0
blocker() {
  FAILED=$((FAILED + 1))
  if (( WARN_ONLY )); then
    printf '    \033[0;31mXX\033[0m  %s\n' "$1"
    [[ -n "${2:-}" ]] && printf '        fix: %s\n' "$2"
  else
    [[ -n "${2:-}" ]] && die "$1
  fix: $2"
    die "$1"
  fi
}

say "Tools"
for c in exasol exapump docker jq scp ssh git make curl python3; do
  command -v "$c" >/dev/null && ok "$c" || blocker "missing: $c" \
    "$(case "$c" in
         make)   echo "xcode-select --install" ;;
         docker) echo "install Docker Desktop and start it" ;;
         exasol|exapump) echo "install the Exasol Personal starter kit" ;;
         *)      echo "brew install $c" ;;
       esac)"
done

say "Exasol Personal"
[[ -f "$DEPLOY_DIR/deployment.json" ]] || blocker "no deployment at $DEPLOY_DIR" \
  "exasol deploy   (or set DEPLOYMENT=<name>)"
exasol status --deployment-dir "$DEPLOY_DIR" 2>/dev/null | grep -q "database_ready" \
  && ok "database_ready" || blocker "database not ready" "exasol start"

# --- the version gate -------------------------------------------------------
# 2.2.0 is verified. Deployments migrated to 2.3.0-rc2+ move the ssh key, the
# ssh target AND BucketFS; lib/common.sh detects all three, but that path has
# NOT been exercised on a real migrated machine, so say so rather than implying
# it is supported.
CLI_VER="$(exasol version 2>/dev/null | head -1 | tr -d '[:space:]')"
case "$CLI_VER" in
  2.2.*) ok "Exasol Personal $CLI_VER (verified)" ;;
  "")    warn "could not read 'exasol version' — continuing" ;;
  *)     warn "Exasol Personal $CLI_VER is NOT the verified version (2.2.x)."
         warn "         lib/common.sh detects the newer layout, but that path is"
         warn "         untested on a real migrated deployment. If a BucketFS copy"
         warn "         fails, that is the first place to look." ;;
esac

# --- the check that was missing --------------------------------------------
# ssh to the node is how the adapter .so and the model reach BucketFS on 2.2.0.
# On the migrated layout BucketFS is host-side and ssh is not needed at all, so
# an unreachable node is only a blocker when there is no host-side route.
if node_reachable; then
  ok "node ssh $(ssh_host):$(ssh_port) (key $(basename "$(ssh_key)"))"
elif [[ "$(bfs_host_dir)" != "none" ]]; then
  warn "node ssh unreachable, but BucketFS is on the host — steps 1 and 7 will"
  warn "         use the host-side copy and do not need ssh"
else
  blocker "cannot ssh to the database node at $(ssh_host):$(ssh_port), and this
  deployment exposes no host-side BucketFS — steps 1 and 7 cannot copy anything" \
    "exasol stop && exasol start, then re-run. If .connection.sshPort is null,
       this is the 2.3.0 migration: see SYSTEM_REQUIREMENTS.md"
fi

if [[ "$(bfs_host_dir)" != "none" ]]; then
  ok "BucketFS reachable on the host (no ssh needed for the copies)"
else
  ok "BucketFS via ssh at $BFS_NODE_ROOT"
fi

say "Docker"
docker info >/dev/null 2>&1 && ok "daemon up" || blocker "Docker is not running" \
  "open -a Docker   (then wait for the whale to settle)"

say "Disk"
# The VM image, two SLCs, the mongo and rust images and the ML build need room.
AVAIL_G="$(df -g / 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ -n "$AVAIL_G" ]] && (( AVAIL_G < 25 )); then
  blocker "only ${AVAIL_G} GB free on / — the images and SLCs need ~25 GB" \
    "free up space, or run: docker system prune -a"
else
  ok "${AVAIL_G:-?} GB free"
fi

say "Data files"
[[ -f "$CUSTOMERS_JSON" ]] && ok "$(basename "$CUSTOMERS_JSON")" \
  || blocker "missing $CUSTOMERS_JSON" "re-clone the repo; the data ships with it"
[[ -f "$ORDERS_CSV" ]]     && ok "$(basename "$ORDERS_CSV")" \
  || blocker "missing $ORDERS_CSV" "re-clone the repo; the data ships with it"
[[ -f "$SUPERSTORE_JSON_GZ" ]] && ok "$(basename "$SUPERSTORE_JSON_GZ")" \
  || warn "missing $(basename "$SUPERSTORE_JSON_GZ") — step 7 needs it (02b loads it)"

say "Dashboards (step 6)"
# This is the dependency that used to abort run_all.sh ~35 minutes in: step 6
# read $HOME/exasol-recipes, which nothing installed. The boards are vendored
# now, so this checks the vendored copy is actually intact.
BOARDS_DIR="$(cd "$(dirname "$0")" && pwd)/dashboards"
MISSING_BOARDS=""
for b in retail-finance retail-sales retail-product retail-datascience \
         retail-inventory retail-delivery; do
  [[ -f "$BOARDS_DIR/$b/app.py" ]] || MISSING_BOARDS="$MISSING_BOARDS $b"
done
if [[ -n "$MISSING_BOARDS" ]]; then
  blocker "vendored boards missing:$MISSING_BOARDS" \
    "re-clone the repo — dashboards/ ships with it"
else
  ok "6 boards vendored in dashboards/"
fi
for t in dryrun.py ship.sh preflight.py; do
  [[ -f "$BOARDS_DIR/$t" ]] || blocker "dashboards/$t missing" "re-clone the repo"
done
DASH_VENV=""
for c in "$HOME/.exasol-starter-kit/dash-server-venv/bin/python3" \
         "$HOME/dash-server/.venv/bin/python3"; do
  [[ -x "$c" ]] && DASH_VENV="$c" && break
done
[[ -n "$DASH_VENV" ]] && ok "dash-server python: ${DASH_VENV/#$HOME/~}" \
  || blocker "no dash-server python (step 6 cannot dry-run or deploy)" \
       "EXAKIT_MARKETPLACE_ADDONS=dash-server exakit marketplace"

say "Is the RUST language registered?"
if xsql -c "SELECT SYSTEM_VALUE FROM EXA_PARAMETERS WHERE PARAMETER_NAME='SCRIPT_LANGUAGES';" \
     | grep -q 'RUST='; then
  ok "RUST alias present — 01_install_vs.sh will skip the SLC step"
else
  warn "no RUST alias yet — 01_install_vs.sh will install the Rust SLC (~2 min)"
fi

say "Is the PYTHON3 language registered? (step 7 needs it)"
# SCRIPT_LANGUAGES lists PYTHON3=builtin_python3 on a fresh deployment even when
# no container is behind it, so the alias is NOT evidence. `exasol slc list` is.
if exasol slc list --deployment-dir "$DEPLOY_DIR" 2>/dev/null \
     | awk '/^python-3/ {print $NF}' | grep -qx yes; then
  ok "PYTHON3 SLC installed — 07_ml_udf.sh will skip the install"
else
  warn "no PYTHON3 SLC — 07_ml_udf.sh will install it, which RESTARTS the database"
  warn "                 do it now to keep the restart out of the talk:"
  warn "                 exasol slc install PYTHON3 --auto-approve"
fi

say "Is the adapter installed?"
if xsql -c "SELECT SCRIPT_NAME FROM EXA_ALL_SCRIPTS WHERE SCRIPT_SCHEMA='MONGODB_VS';" \
     | grep -q MONGODB_ADAPTER; then
  ok "MONGODB_VS.MONGODB_ADAPTER exists"
else
  warn "adapter not installed — 01_install_vs.sh will build and install it"
fi

say "Connection headroom (Exasol Personal allows 20)"
OPEN="$(xsql -c "SELECT COUNT(*) FROM EXA_ALL_SESSIONS;" | jq -r '.statements[0].rows[0][0]')"
if (( OPEN >= 15 )); then
  warn "$OPEN of 20 connections already open — run: exakit stop && exakit start"
  warn "                 (dash-server parks ~3 idle sessions per deployed board)"
else
  ok "$OPEN of 20 connections open"
fi

say "dash-server"
curl -sf -o /dev/null http://127.0.0.1:5100/ && ok "dashboards page answers on :5100" \
  || warn "not running — start with: exakit start"

if (( FAILED > 0 )); then
  printf '\n\033[0;31m==> %s BLOCKER(S) — fix these before running any step\033[0m\n' "$FAILED"
  exit 1
fi
say "PREFLIGHT DONE — nothing blocking"
