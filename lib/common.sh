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

WORK="${WORK:-$HOME/meetup-virtual-schema/.work}"
mkdir -p "$WORK"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[0;32mok\033[0m  %s\n' "$*"; }
warn() { printf '    \033[0;33m!!\033[0m  %s\n' "$*"; }
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
# Run SQL and fail loudly on a statement error, which `exasol connect` reports
# inside its JSON rather than through the exit code.
xsql() {
  local out
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
