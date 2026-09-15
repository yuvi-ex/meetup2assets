#!/bin/sh
# One command from nothing to the full demo: MongoDB virtual schema, six
# dashboards, and a model running inside the database.
#
#   curl -fsSL https://raw.githubusercontent.com/yuvi-ex/starterkit-dashserver-VS-UDF/main/bootstrap.sh | sh
#
# Written to be run BY AN AGENT, not by a person at a prompt:
#
#   * It never reads stdin. Nothing prompts, nothing waits for a keypress. (It
#     could not read stdin even if it wanted to -- under `curl | sh` stdin IS
#     the script.)
#   * Every failure exits non-zero with one specific line saying what to run.
#   * It is idempotent: it re-uses an existing clone, and the demo steps are
#     themselves re-runnable. Re-running after a failure is the intended repair.
#
# This is the LONG demo -- roughly 50 minutes unattended, most of it downloads
# on the first run. It is also the one with hard platform limits; the checks
# below stop early rather than failing 35 minutes in.
#
# Knobs (all optional env vars -- there are no interactive questions):
#   DEMO_DIR=~/starterkit-vs-udf   where to clone
#   BRANCH=main                    which branch
#   SKIP_PREFETCH=1                skip the download-caching pass
#   --install-kit                  install the starter kit + dash-server if
#                                  missing, instead of stopping
set -eu

REPO="https://github.com/yuvi-ex/starterkit-dashserver-VS-UDF.git"
DEMO_DIR="${DEMO_DIR:-$HOME/starterkit-vs-udf}"
BRANCH="${BRANCH:-main}"
INSTALL_KIT=0
for a in "$@"; do
  if [ "$a" = "--install-kit" ]; then INSTALL_KIT=1; fi
done

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) PATH="$HOME/.local/bin:$PATH"; export PATH ;;
esac

say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
die() { printf "\n\033[31merror: %s\033[0m\n" "$1" >&2; exit 1; }

KIT_INSTALL='curl -fsSL https://raw.githubusercontent.com/exasol/local-agent-ready-starter/main/install.sh | sh'
DASH_INSTALL='EXAKIT_MARKETPLACE_ADDONS=dash-server exakit marketplace'

# --- 1. platform ------------------------------------------------------------
# The prebuilt Rust language container is aarch64-only, so an Intel Mac or a
# Linux box cannot complete step 1 no matter what else is right. Say so now.
say "1/5  checking the platform"
[ "$(uname -s)" = "Darwin" ] || die "this demo runs on macOS only.
  The MongoDB adapter ships as a prebuilt aarch64 Darwin container."
[ "$(uname -m)" = "arm64" ] || die "this demo needs an Apple silicon Mac.
  The prebuilt Rust language container is aarch64 only."
for t in git jq docker; do
  command -v "$t" >/dev/null 2>&1 || die "missing: $t
  Install it and re-run. (brew install $t)"
done
docker info >/dev/null 2>&1 || die "Docker is not running -- MongoDB runs in it.
  Start Docker Desktop and re-run."
echo "  macOS on arm64, git + jq + docker present"

# --- 2. the kit -------------------------------------------------------------
say "2/5  checking the Exasol starter kit"
if ! command -v exakit >/dev/null 2>&1; then
  [ "$INSTALL_KIT" = 1 ] || die "the Exasol starter kit is not installed.
  Install it, then re-run this script:
      $KIT_INSTALL
  Or re-run with --install-kit to have this script do it."
  say "      installing the starter kit (a few minutes)"
  sh -c "$KIT_INSTALL" || die "starter kit install failed -- run it by hand: $KIT_INSTALL"
fi
command -v exakit >/dev/null 2>&1 || die "exakit installed but not on PATH.
  Add it and re-run:  export PATH=\"\$HOME/.local/bin:\$PATH\""

exakit status 2>/dev/null | grep -qi running || {
  say "      starting the database"
  exakit start || die "could not start Exasol. Try: exakit status"
}

# The platform version decides whether this kit runs at all: 2.3.0-rc2 moved
# BucketFS and dropped the ssh port, so steps 1 and 7 cannot copy anything.
DEPLOY="$HOME/.exasol/personal/deployments/default/deployment.json"
if [ -f "$DEPLOY" ]; then
  PORT=$(jq -r '.connection.sshPort // "null"' "$DEPLOY")
  [ "$PORT" != "null" ] || die "this Exasol Personal deployment has been migrated
  to 2.3.0-rc2 or later: .connection.sshPort is absent, BucketFS has moved, and
  steps 1 and 7 will fail. See SYSTEM_REQUIREMENTS.md. This kit needs 2.2.0."
  echo "  deployment looks like 2.2.x (ssh port $PORT)"
fi

VENV=""
for c in "$HOME/.exasol-starter-kit/dash-server-venv/bin/python3" \
         "$HOME/dash-server/.venv/bin/python3"; do
  [ -x "$c" ] && VENV="$c" && break
done
if [ -z "$VENV" ]; then
  [ "$INSTALL_KIT" = 1 ] || die "the dash-server add-on is not installed (step 6 needs it).
  Install it, then re-run this script:
      $DASH_INSTALL
  Or re-run with --install-kit to have this script do it."
  say "      installing dash-server"
  sh -c "$DASH_INSTALL" || die "dash-server install failed -- run it by hand: $DASH_INSTALL"
fi

# --- 3. the demo ------------------------------------------------------------
say "3/5  fetching the demo into $DEMO_DIR"
if [ -d "$DEMO_DIR/.git" ]; then
  echo "  already cloned -- updating"
  git -C "$DEMO_DIR" fetch --quiet origin "$BRANCH" \
    && git -C "$DEMO_DIR" checkout --quiet "$BRANCH" \
    && git -C "$DEMO_DIR" reset --hard --quiet "origin/$BRANCH" \
    || die "could not update $DEMO_DIR. Delete it and re-run."
elif [ -e "$DEMO_DIR" ]; then
  die "$DEMO_DIR exists but is not a git clone. Move it aside, or set DEMO_DIR."
else
  git clone --quiet --branch "$BRANCH" "$REPO" "$DEMO_DIR" \
    || die "clone failed. Check the network, or clone by hand: git clone $REPO"
fi
cd "$DEMO_DIR"
chmod +x ./*.sh 2>/dev/null || true

# --- 4. gate and cache ------------------------------------------------------
# 00_preflight.sh is the real gate: disk, boards, venv, ssh to the node. It
# names the fixing command for every blocker, so just let it speak.
say "4/5  preflight"
./00_preflight.sh || die "preflight found a blocker -- fix the line above and re-run this script."

if [ "${SKIP_PREFETCH:-0}" = "1" ]; then
  echo "  SKIP_PREFETCH=1 -- not caching downloads"
else
  say "      caching every download (first run: ~8 min)"
  ./00b_prefetch.sh || die "prefetch failed -- re-run this script; it resumes."
fi

# --- 5. run it --------------------------------------------------------------
# run_all.sh is the unattended path. Presenting? Run the numbered steps one at
# a time instead so the room sees each land -- see RUNSHEET.md.
say "5/5  running every step (~35 min)"
./run_all.sh
