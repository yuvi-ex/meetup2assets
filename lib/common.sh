# Shared settings for the Virtual Schema meetup flow.
set -euo pipefail

DEPLOYMENT="${DEPLOYMENT:-default}"
DEPLOY_DIR="$HOME/.exasol/personal/deployments/$DEPLOYMENT"
MONGO_CONTAINER="${MONGO_CONTAINER:-mongodb-local}"
MONGO_IMAGE="${MONGO_IMAGE:-mongo:8.2}"     # NOT 8.0 — see note in 02
MONGO_ROOT_PW="${MONGO_ROOT_PW:-secret}"
MONGO_READER="${MONGO_READER:-analytics_reader}"
MONGO_READER_PW="${MONGO_READER_PW:-reader-pass}"
# The address the Exasol VM uses to reach this Mac. 127.0.0.1 would resolve
# INSIDE the VM and the connection would fail.
HOST_GATEWAY="${HOST_GATEWAY:-192.168.64.1}"

# Data ships WITH the repo, so a fresh clone works with no external downloads.
KIT_ROOT="${KIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CUSTOMERS_JSON="${CUSTOMERS_JSON:-$KIT_ROOT/data/retail_customers.json}"
ORDERS_CSV="${ORDERS_CSV:-$KIT_ROOT/data/retail_orders.csv}"
SUPERSTORE_JSON_GZ="${SUPERSTORE_JSON_GZ:-$KIT_ROOT/data/StoreSales.json.gz}"

WORK="${WORK:-$KIT_ROOT/.work}"
mkdir -p "$WORK"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[0;32mok\033[0m  %s\n' "$*"; }
warn() { printf '    \033[0;33m!!\033[0m  %s\n' "$*"; }
# The business question, in English, before the SQL. The room reads this; the
# SQL underneath is the proof, not the message. Feed it on stdin:
#     ask <<'Q'
#     Who are our most valuable customers?
#     Q
ask() {
  # Reverse video, not a colour: it inverts whatever the terminal background is,
  # so it stays readable on a light theme and on a washed-out projector.
  printf '\n\033[7;1m  THE QUESTION                                                  \033[0m\n'
  while IFS= read -r line; do printf '\033[7m \033[0m  \033[1m%s\033[0m\n' "$line"; done
  printf '\033[7m \033[0m\n'
}
die()  { printf '\n\033[0;31merror: %s\033[0m\n' "$*" >&2; exit 1; }

ssh_port() { jq -r '.connection.sshPort' "$DEPLOY_DIR/deployment.json"; }
node_ssh() {
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
      -i "$DEPLOY_DIR/local/node_access.pem" -p "$(ssh_port)" root@127.0.0.1 "$@"
}
node_scp() {
  scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
      -i "$DEPLOY_DIR/local/node_access.pem" -P "$(ssh_port)" "$1" "root@127.0.0.1:$2"
}
# Exasol Personal is licensed for 20 PARALLEL CONNECTIONS, and dash-server opens
# roughly three per board and leaves them IDLE forever. Six boards therefore park
# ~18 of the 20, and the next statement anybody runs — step 7, a dashboard, an MCP
# query — fails with SQL state 08004 "license limit of 20 parallel connections has
# been reached". Killing the idle ones is safe: dash-server reconnects on demand,
# and boards keep serving (verified 2026-09-04, callbacks and filters intact).
free_connections() {
  local ids n
  ids="$(SHOW_SQL=0 xsql -c "SELECT SESSION_ID FROM EXA_ALL_SESSIONS
           WHERE USER_NAME = 'MCP_READONLY' AND STATUS = 'IDLE';" \
         | jq -r '.statements[0].rows[][0]' 2>/dev/null)" || return 0
  [[ -z "$ids" ]] && return 0
  n="$(printf '%s\n' "$ids" | grep -c .)"
  for id in $ids; do SHOW_SQL=0 xsql -c "KILL SESSION $id;" >/dev/null 2>&1 || true; done
  ok "reclaimed $n idle dash-server connections (license ceiling is 20)"
}

# Print the SQL a step is about to run, indented and dimmed, so the audience
# always sees the statement before its result. SHOW_SQL=0 silences it (used by
# the handful of internal catalog probes that are plumbing, not story).
SHOW_SQL="${SHOW_SQL:-1}"
# Everything here goes to STDERR on purpose. xsql's stdout is a JSON document
# that callers pipe into jq/xtable or send to /dev/null; printing the banner on
# stdout would both corrupt that pipe and be silenced by the >/dev/null callers.
show_sql() {
  [[ "$SHOW_SQL" == "1" ]] || return 0
  local body="$1"
  {
    printf '\033[0;36m    ┌─ SQL ─────────────────────────────────────────────────────\033[0m\n'
    # Trim leading blank lines, strip the heredoc indent, re-indent uniformly.
    # Comment lines are kept: they are part of the teaching.
    # Dedent by the COMMON indent only. Stripping every leading space (the
    # obvious sed) would left-align every line and destroy the alignment that
    # makes a projected SELECT readable.
    printf '%s\n' "$body" | sed -e '/./,$!d' -e :a -e '/^\n*$/{$d;N;};/\n$/ba' | awk '
      { line[NR] = $0
        if ($0 ~ /[^[:space:]]/) { match($0, /[^[:space:]]/)
          if (min == "" || RSTART - 1 < min) min = RSTART - 1 } }
      END { for (i = 1; i <= NR; i++) print substr(line[i], min + 1) }' \
      | sed 's/^/\x1b[0;36m    │\x1b[0m /'
    printf '\033[0;36m    └───────────────────────────────────────────────────────────\033[0m\n'
  } >&2
}

# Run SQL and fail loudly on a statement error, which `exasol connect` reports
# inside its JSON rather than through the exit code.
xsql() {
  local out
  # Echo the statement (-c) or the whole file (-f) before executing it.
  case "${1:-}" in
    -c) show_sql "$2" ;;
    -f) show_sql "$(cat "$2")" ;;
  esac
  out="$(exasol connect --deployment-dir "$DEPLOY_DIR" --json=compact "$@" 2>&1 | grep '^{' | head -1)"
  printf '%s' "$out" | jq -e '[.statements[].error] | map(select(. != null)) | length == 0' >/dev/null \
    || { printf '%s' "$out" | jq -r '.statements[] | select(.error) | "SQL error: " + .error.message' >&2; return 1; }
  printf '%s' "$out"
}
# Print a result set as an aligned table.
xtable() { jq -r '.statements[] | select(.rows | length > 0) | (.columns|@tsv), (.rows[]|@tsv)' | column -t -s"$(printf '\t')"; }
mongo_root() {
  docker exec "$MONGO_CONTAINER" mongosh --quiet -u root -p "$MONGO_ROOT_PW" \
    --authenticationDatabase admin "$@"
}
