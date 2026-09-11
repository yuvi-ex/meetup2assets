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

# --- reaching the database node ---------------------------------------------
#
# TWO LAYOUTS EXIST AND THEY NEED DIFFERENT ANSWERS. Exasol Personal 2.2.0 and
# deployments migrated to 2.3.0-rc2+ disagree about all three of the key, the
# address and where BucketFS lives, so every function below DETECTS rather than
# assumes. Hardcoding either one is what broke this kit on a machine that was
# not the author's:
#
#                 2.2.0                          migrated 2.3.0-rc2+
#   ssh port      deployment.json .connection.sshPort    absent -> 22
#   ssh host      127.0.0.1                      vm_ip from vm-runtime.json
#   ssh key       local/node_access.pem          local/runtime/vm-ssh-key
#   BucketFS      /var/lib/exa/bucketfs, on the  /mnt/host/exa/bucketfs, a
#                 VM's OWN DISK (/dev/vda) --    virtiofs share ALSO visible on
#                 reachable ONLY over ssh        the Mac, so no ssh needed
#
# Note the asymmetry in that last row: on 2.2.0 there is NO host-side directory
# to copy into, so "just use cp" is not a fix, it only moves the breakage.
#
# Every value is cached on first use -- these are called in loops and each one
# otherwise shells out to jq.

_NODE_PORT=""; _NODE_HOST=""; _NODE_KEY=""; _BFS_HOST_DIR=""; _NODE_PROBED=""

ssh_port() {
  if [[ -z "$_NODE_PORT" ]]; then
    # deployment.json first (2.2.0), then vm-state.json, which carries the same
    # port under a different name and survives on more layouts than either.
    _NODE_PORT="$(jq -r '.connection.sshPort // empty' \
                    "$DEPLOY_DIR/deployment.json" 2>/dev/null || true)"
    [[ -z "$_NODE_PORT" || "$_NODE_PORT" == "null" ]] && \
      _NODE_PORT="$(jq -r '.ports.ssh // empty' \
                      "$DEPLOY_DIR/local/runtime/vm-state.json" 2>/dev/null || true)"
    # Neither present means the migrated layout, which talks to the VM on 22.
    [[ -z "$_NODE_PORT" || "$_NODE_PORT" == "null" ]] && _NODE_PORT="22"
  fi
  printf '%s' "$_NODE_PORT"
}

ssh_host() {
  if [[ -z "$_NODE_HOST" ]]; then
    # A forwarded port means loopback. Port 22 means we dial the VM directly, so
    # we need its address -- vm-runtime.json on the migrated layout, vm-state.json
    # on 2.2.0.
    if [[ "$(ssh_port)" == "22" ]]; then
      for f in "$DEPLOY_DIR/local/runtime/vm-runtime.json" \
               "$DEPLOY_DIR/local/runtime/vm-state.json"; do
        [[ -f "$f" ]] || continue
        _NODE_HOST="$(jq -r '.vm_ip // empty' "$f" 2>/dev/null || true)"
        [[ -n "$_NODE_HOST" && "$_NODE_HOST" != "null" ]] && break
      done
    fi
    [[ -z "$_NODE_HOST" || "$_NODE_HOST" == "null" ]] && _NODE_HOST="127.0.0.1"
  fi
  printf '%s' "$_NODE_HOST"
}

ssh_key() {
  if [[ -z "$_NODE_KEY" ]]; then
    # vm-state.json names the key outright on 2.2.0; otherwise take whichever
    # file is actually present rather than guessing by version number.
    _NODE_KEY="$(jq -r '.ssh_private_key // empty' \
                   "$DEPLOY_DIR/local/runtime/vm-state.json" 2>/dev/null || true)"
    if [[ -z "$_NODE_KEY" || "$_NODE_KEY" == "null" || ! -f "$_NODE_KEY" ]]; then
      for k in "$DEPLOY_DIR/local/node_access.pem" \
               "$DEPLOY_DIR/local/runtime/vm-ssh-key"; do
        [[ -f "$k" ]] && _NODE_KEY="$k" && break
      done
    fi
  fi
  printf '%s' "$_NODE_KEY"
}

_SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
           -o LogLevel=ERROR -o ConnectTimeout=10)

node_ssh() {
  ssh "${_SSH_OPTS[@]}" -i "$(ssh_key)" -p "$(ssh_port)" \
      "root@$(ssh_host)" "$@"
}
node_scp() {
  scp "${_SSH_OPTS[@]}" -i "$(ssh_key)" -P "$(ssh_port)" \
      "$1" "root@$(ssh_host):$2"
}

# Does ssh to the node actually work? Returns 0/1 and caches, so preflight can
# VALIDATE the connection instead of printing a port and hoping. BatchMode keeps
# it from hanging on a passphrase prompt.
node_reachable() {
  if [[ -z "$_NODE_PROBED" ]]; then
    if ssh "${_SSH_OPTS[@]}" -o BatchMode=yes -i "$(ssh_key)" -p "$(ssh_port)" \
           "root@$(ssh_host)" true >/dev/null 2>&1; then
      _NODE_PROBED=yes
    else
      _NODE_PROBED=no
    fi
  fi
  [[ "$_NODE_PROBED" == "yes" ]]
}

# --- BucketFS ----------------------------------------------------------------
# If the deployment exposes BucketFS on the host (migrated layout), use it: a
# plain cp needs no ssh at all. Otherwise fall back to scp, which is the ONLY
# route on 2.2.0. bucketfs_put/rm hide the difference so no step script has to
# care which machine it is on.

bfs_host_dir() {
  if [[ -z "$_BFS_HOST_DIR" ]]; then
    for d in "$DEPLOY_DIR/local/runtime/exa/bucketfs" \
             "$DEPLOY_DIR/local/runtime/exa/bucketfs/bfsdefault"; do
      if [[ -d "$d" ]]; then
        _BFS_HOST_DIR="${DEPLOY_DIR}/local/runtime/exa/bucketfs"
        break
      fi
    done
    [[ -z "$_BFS_HOST_DIR" ]] && _BFS_HOST_DIR="none"
  fi
  printf '%s' "$_BFS_HOST_DIR"
}

# Where BucketFS lives on the NODE. Only used on the ssh path.
BFS_NODE_ROOT="${BFS_NODE_ROOT:-/var/lib/exa/bucketfs}"

# bucketfs_put <local-file> <bucket> [dest-name]
bucketfs_put() {
  local src="$1" bucket="$2" name="${3:-$(basename "$1")}" hostdir
  hostdir="$(bfs_host_dir)"
  if [[ "$hostdir" != "none" ]]; then
    mkdir -p "$hostdir/bfsdefault/$bucket"
    cp "$src" "$hostdir/bfsdefault/$bucket/$name"
  else
    # The bucket dir starts empty and scp dies with an opaque
    # "dest open ... Failure" if it does not exist, so mkdir first.
    node_ssh "mkdir -p $BFS_NODE_ROOT/bfsdefault/$bucket"
    node_scp "$src" "$BFS_NODE_ROOT/bfsdefault/$bucket/$name"
  fi
}

# bucketfs_rm <bucket> [...]  -- removes whole buckets, used by the reset scripts
bucketfs_rm() {
  local hostdir b; hostdir="$(bfs_host_dir)"
  for b in "$@"; do
    if [[ "$hostdir" != "none" ]]; then
      rm -rf "$hostdir/bfsdefault/$b"
    else
      node_ssh "rm -rf $BFS_NODE_ROOT/bfsdefault/$b"
    fi
  done
}

# bucketfs_ls <bucket>  -- for the "show the room it landed" lines
bucketfs_ls() {
  local hostdir; hostdir="$(bfs_host_dir)"
  if [[ "$hostdir" != "none" ]]; then
    ls -l "$hostdir/bfsdefault/$1" 2>/dev/null
  else
    node_ssh "ls -l $BFS_NODE_ROOT/bfsdefault/$1" 2>/dev/null
  fi
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
# Unregister a script language alias.
#
# `exasol slc remove RUST` DOES NOT WORK and never did: that subcommand only
# knows the official catalog (java-17, python-3.12, r-4.4), and RUST is not in
# it. The exasol-labs installer registers RUST with ALTER SYSTEM
# SCRIPT_LANGUAGES=..., so removing it means rewriting that same parameter
# without the alias. `exasol slc custom remove` does not exist either -- there is
# no `custom` subcommand on 2.2.0.
#
# SCRIPT_LANGUAGES is one space-separated list of ALIAS=value tokens and ALTER
# SYSTEM replaces the WHOLE value, so every other entry has to be carried over
# or the built-in languages are silently unregistered too.
unregister_script_language() {
  local alias="$1" existing kept word
  existing="$(xsql -c "SELECT SYSTEM_VALUE FROM EXA_PARAMETERS
                        WHERE PARAMETER_NAME='SCRIPT_LANGUAGES';" \
              | jq -r '.statements[0].rows[0][0] // empty')" || return 1
  [[ -z "$existing" ]] && return 1
  case "$existing" in
    *"$alias="*) ;;
    *) return 2 ;;   # not registered: nothing to do, and not an error
  esac
  kept=""
  for word in $existing; do
    case "$word" in
      "$alias="*) continue ;;
    esac
    kept="${kept:+$kept }$word"
  done
  xsql -c "ALTER SYSTEM SET SCRIPT_LANGUAGES='$kept';" >/dev/null
}

mongo_root() {
  docker exec "$MONGO_CONTAINER" mongosh --quiet -u root -p "$MONGO_ROOT_PW" \
    --authenticationDatabase admin "$@"
}
