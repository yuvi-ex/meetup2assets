#!/usr/bin/env bash
# STEP 1 — install the MongoDB Virtual Schema on Exasol Personal, from the CLI.
#
# Three things have to be true before a virtual schema exists:
#   a) a RUST script-language container is registered  (the adapter is Rust)
#   b) the adapter .so is in BucketFS
#   c) the adapter + scan scripts are created in SQL
# Idempotent: each step is skipped if already done.
source "$(dirname "$0")/lib/common.sh"

SLC_VERSION="${SLC_VERSION:-0.23.0}"
SLC_REPO="$HOME/language-container-rs"
VS_REPO="$HOME/exasol-mongodb-vs"
ARCH="$(uname -m)"; [[ "$ARCH" == "arm64" ]] && SLC_ARCH="-aarch64" || SLC_ARCH=""

say "1a. Rust script-language container"
if xsql -c "SELECT SYSTEM_VALUE FROM EXA_PARAMETERS WHERE PARAMETER_NAME='SCRIPT_LANGUAGES';" | grep -q 'RUST='; then
  ok "RUST already registered — skipping"
else
  # exasol slc list only offers java/python/r. Rust comes from exasol-labs.
  [[ -d "$SLC_REPO" ]] || git clone --quiet --depth 1 --branch "v$SLC_VERSION" \
      https://github.com/exasol-labs/language-container-rs.git "$SLC_REPO"
  TARBALL="$WORK/lc-rust-$SLC_VERSION$SLC_ARCH.tar.gz"
  [[ -f "$TARBALL" ]] || curl -sSL -o "$TARBALL" \
    "https://github.com/exasol-labs/language-container-rs/releases/download/v$SLC_VERSION/lc-rust-$SLC_VERSION$SLC_ARCH.tar.gz"
  # Use the PREBUILT tarball: building the container from source needs cargo-about.
  SLC_TARBALL="$TARBALL" "$SLC_REPO/scripts/install.sh" --deployment "$DEPLOYMENT"
  ok "RUST registered (ALTER SYSTEM — survives a restart)"
fi

say "1b. Build the adapter and put it in BucketFS"
[[ -d "$VS_REPO" ]] || git clone --quiet https://github.com/exasol-labs/exasol-mongodb-vs.git "$VS_REPO"
SO="$VS_REPO/target/release/libmongodb_vs.so"
if [[ -f "$SO" ]]; then ok "artifact already built"; else
  # Built inside rust:1.94.1-trixie. A macOS host build is NOT loadable.
  make -C "$VS_REPO" build-so
fi
make -C "$VS_REPO" verify-so

# BucketFS on Personal is a DIRECTORY the engine reconciles into a bucket in ~1s.
# It starts empty, so mkdir first or scp dies with an opaque "dest open ... Failure".
node_ssh 'mkdir -p /var/lib/exa/bucketfs/bfsdefault/rust'
node_scp "$SO" /var/lib/exa/bucketfs/bfsdefault/rust/libmongodb_vs.so
sleep 3
node_ssh 'ls -l /var/lib/exa/bucketfs/bfsdefault/rust/libmongodb_vs.so'
ok "visible to UDFs at /buckets/bfsdefault/rust/libmongodb_vs.so"

say "1c. Create the adapter and scan scripts"
xsql -f "$VS_REPO/sql/install.sql" >/dev/null
xsql -c "SELECT SCRIPT_NAME, SCRIPT_TYPE, SCRIPT_LANGUAGE FROM EXA_ALL_SCRIPTS WHERE SCRIPT_SCHEMA='MONGODB_VS';" | xtable

say "STEP 1 DONE — Exasol can now speak MongoDB"
