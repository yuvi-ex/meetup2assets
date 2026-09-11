#!/usr/bin/env bash
# STEP 6 — the same join, as a dashboard people can click.
source "$(dirname "$0")/lib/common.sh"
# VENDORED, not $HOME/exasol-recipes. That directory existed only on the author's
# laptop -- nothing in this repo installed it, it was in no README, and step 6
# aborted run_all.sh (set -euo pipefail) roughly 35 minutes into a fresh run.
# The boards now ship with the repo, so there is nothing to install and nothing
# to fetch while the room watches.
RECIPES="$(cd "$(dirname "$0")/dashboards" && pwd)"

# dash-server installs its venv in one of two places depending on how the add-on
# was set up. Hardcoding either one is how this broke on a machine that was not
# the author's.
VENV=""
for c in "$HOME/.exasol-starter-kit/dash-server-venv/bin/python3" \
         "$HOME/dash-server/.venv/bin/python3"; do
  [[ -x "$c" ]] && VENV="$c" && break
done
[[ -n "$VENV" ]] || die "no dash-server python found — run ./00_preflight.sh"
BOARDS="${BOARDS:-retail-finance retail-sales retail-product retail-datascience retail-inventory retail-delivery}"

free_connections   # a previous 06 run parks ~3 idle connections per board
say "6a. One view that IS the join"
# dash-server reads as mcp_readonly, which has no rights on a virtual schema you
# just created — so the join lives in a view in a normal schema, granted to it.
xsql -f "$(dirname "$0")/sql/orders_enriched.sql" >/dev/null
xsql -c "SELECT COUNT(*) AS ROWS_JOINED, COUNT(DISTINCT CUSTOMER_ID) AS CUSTOMERS,
                ROUND(SUM(REVENUE),0) AS BOOKED, ROUND(SUM(NET_REVENUE),0) AS REALISED,
                ROUND(SUM(LOST_REVENUE),0) AS LOST
         FROM RETAIL.ORDERS_ENRICHED;" | xtable

say "6b. Dry run every board (contracts, not health probes)"
for b in $BOARDS; do
  printf '    %-22s ' "$b"
  "$VENV" "$RECIPES/dryrun.py" "$RECIPES/$b" 2>&1 | grep -E "all contracts hold|FAIL" | head -1
done

say "6c. Deploy"
sh "$RECIPES/ship.sh" $BOARDS 2>&1 | grep -E "Dashboard ready|shipped|failed"

say "6d. Verify the page the audience will actually open"
for b in $BOARDS; do
  printf '    %-22s ' "$b"
  "$VENV" "$RECIPES/preflight.py" "$b" 2>&1 | grep -E "^GO|^NO-GO" | head -1
  curl -s -o /dev/null -w "                           page: HTTP %{http_code}\n" \
    "http://127.0.0.1:5100/apps/$b"
done

cat <<'NOTE'

    Six boards, one join, six audiences:
      retail-finance      booked vs realised vs lost revenue
      retail-sales        store and channel performance
      retail-product      category and product line value
      retail-datascience  which customer features survive a control (none do)
      retail-inventory    reorder pressure, and what it cannot tell you
      retail-delivery     the order pipeline and delivery tiers
NOTE
say "STEP 6 DONE"
