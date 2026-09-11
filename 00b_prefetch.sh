#!/usr/bin/env bash
# Pull EVERY byte this demo fetches from the internet, before the room is
# watching. Run it the night before, on a connection you trust.
#
#   ./00b_prefetch.sh
#
# WHY THIS EXISTS. A first run downloads two git repos, an SLC tarball, three
# container images and then builds two of them. That is several minutes and a
# few GB on conference wifi, in the middle of steps 1, 2 and 7. Every one of
# those is cacheable, and none of them has to happen live.
#
# Idempotent and safe to re-run: each item is skipped when already present.
# Nothing here touches the database, so it cannot break a working deployment.
SHOW_SQL=0
source "$(dirname "$0")/lib/common.sh"

SLC_VERSION="${SLC_VERSION:-0.23.0}"
SLC_REPO="$HOME/language-container-rs"
VS_REPO="$HOME/exasol-mongodb-vs"
ARCH="$(uname -m)"; [[ "$ARCH" == "arm64" ]] && SLC_ARCH="-aarch64" || SLC_ARCH=""
TARBALL="$WORK/lc-rust-$SLC_VERSION$SLC_ARCH.tar.gz"

# The build image the VS Makefile uses. A macOS host build is NOT loadable by the
# database, so this image is required, not an optimisation.
RUST_IMAGE="${RUST_IMAGE:-rust:1.94.1-trixie}"
ML_BASE="${ML_BASE:-python:3.12-slim}"

docker info >/dev/null 2>&1 || die "Docker is not running — open -a Docker"

say "1/6  Container images"
for img in "$MONGO_IMAGE" "$RUST_IMAGE" "$ML_BASE"; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    ok "$img (cached)"
  else
    printf '    pulling %s …\n' "$img"
    docker pull -q "$img" >/dev/null && ok "$img" || die "could not pull $img"
  fi
done

say "2/6  Rust SLC repo (the installer script)"
if [[ -d "$SLC_REPO/.git" ]]; then ok "$SLC_REPO (present)"; else
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch "v$SLC_VERSION" \
    https://github.com/exasol-labs/language-container-rs.git "$SLC_REPO" \
    && ok "cloned v$SLC_VERSION" || die "clone failed — check network"
fi

say "3/6  Rust SLC tarball (~200 MB)"
if [[ -s "$TARBALL" ]]; then ok "$(basename "$TARBALL") (cached)"; else
  curl -fsSL -o "$TARBALL" \
    "https://github.com/exasol-labs/language-container-rs/releases/download/v$SLC_VERSION/lc-rust-$SLC_VERSION$SLC_ARCH.tar.gz" \
    && ok "$(basename "$TARBALL")" \
    || die "download failed. On a non-arm64 host the asset name differs — check
  https://github.com/exasol-labs/language-container-rs/releases/tag/v$SLC_VERSION"
fi

say "4/6  Virtual Schema adapter source"
if [[ -d "$VS_REPO/.git" ]]; then ok "$VS_REPO (present)"; else
  git clone --quiet https://github.com/exasol-labs/exasol-mongodb-vs.git "$VS_REPO" \
    && ok "cloned" || die "clone failed — check network"
fi

say "5/6  Build the adapter now, not during the talk (~3 min first time)"
if [[ -f "$VS_REPO/target/release/libmongodb_vs.so" ]]; then
  ok "libmongodb_vs.so already built"
else
  make -C "$VS_REPO" build-so >/dev/null 2>&1 && ok "built" \
    || warn "build failed here — step 1 will retry and show the error"
fi

say "6/6  Build the ML training image"
if docker image inspect exasol-ml-train >/dev/null 2>&1; then
  ok "exasol-ml-train (cached)"
else
  docker build -q -t exasol-ml-train "$KIT_ROOT/ml" >/dev/null 2>&1 \
    && ok "exasol-ml-train" || warn "build failed here — step 7 will retry"
fi

say "PREFETCH DONE"
printf '    Everything the demo downloads is now local. The SLC install in step 1\n'
printf '    and the PYTHON3 SLC in step 7 still need the database, so if you want\n'
printf '    the restart out of the talk too, run this now:\n\n'
printf '        exasol slc install PYTHON3 --auto-approve\n\n'
