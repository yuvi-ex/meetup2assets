#!/usr/bin/env bash
# Run this the morning of the meetup. Every check is a thing that has actually
# broken a run before.
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

say "Is the adapter installed?"
if xsql -c "SELECT SCRIPT_NAME FROM EXA_ALL_SCRIPTS WHERE SCRIPT_SCHEMA='MONGODB_VS';" \
     | grep -q MONGODB_ADAPTER; then
  ok "MONGODB_VS.MONGODB_ADAPTER exists"
else
  warn "adapter not installed — 01_install_vs.sh will build and install it"
fi

say "dash-server"
curl -sf -o /dev/null http://127.0.0.1:5100/ && ok "dashboards page answers on :5100" \
  || warn "not running — start with: exakit start"

say "PREFLIGHT DONE"
