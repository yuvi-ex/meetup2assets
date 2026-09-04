#!/usr/bin/env bash
# Run this the morning of the meetup. Every check is a thing that has actually
# broken a run before.
SHOW_SQL=0   # this is a morning check, not the talk: keep the output scannable
source "$(dirname "$0")/lib/common.sh"

say "Tools"
for c in exasol exapump docker jq scp ssh; do
  command -v "$c" >/dev/null && ok "$c" || die "missing: $c"
done

say "Exasol Personal"
[[ -f "$DEPLOY_DIR/deployment.json" ]] || die "no deployment at $DEPLOY_DIR"
exasol status --deployment-dir "$DEPLOY_DIR" 2>/dev/null | grep -q "database_ready" \
  && ok "database_ready" || die "database not ready — run: exasol start"
ok "ssh port $(ssh_port)  (this changes on every restart)"

say "Docker"
docker info >/dev/null 2>&1 && ok "daemon up" || die "Docker is not running"

say "Data files"
[[ -f "$CUSTOMERS_JSON" ]] && ok "$(basename "$CUSTOMERS_JSON")" || die "missing $CUSTOMERS_JSON"
[[ -f "$ORDERS_CSV" ]]     && ok "$(basename "$ORDERS_CSV")"     || die "missing $ORDERS_CSV"

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

say "PREFLIGHT DONE"
