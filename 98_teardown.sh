#!/usr/bin/env bash
# FULL TEARDOWN — removes everything this kit ever created, so the next run is
# genuinely from zero. Destructive. It will ask before it does anything.
#
#   ./98_teardown.sh            # asks
#   ./98_teardown.sh --yes      # does not ask
source "$(dirname "$0")/lib/common.sh"

if [[ "${1:-}" != "--yes" ]]; then
  cat <<'WARN'
This deletes:
  Exasol   MONGO_RETAIL, MONGO_SUPERSTORE, MONGODB_VS, ML, RETAIL  (+ their connections)
           the adapter .so and the model in BucketFS
           the RUST script-language container  (DATABASE RESTART)
  MongoDB  the whole mongodb-local container and its data
  Local    the model, training data, the training image, ~/exasol-mongodb-vs, ~/language-container-rs
It does NOT delete: your dashboards, the starter kit, or the sample schemas.
WARN
  read -r -p "Type DELETE to proceed: " answer
  [[ "$answer" == "DELETE" ]] || { echo "cancelled"; exit 0; }
fi

say "Exasol objects"
xsql -c "
DROP VIRTUAL SCHEMA IF EXISTS MONGO_RETAIL CASCADE;
DROP VIRTUAL SCHEMA IF EXISTS MONGO_SUPERSTORE CASCADE;
DROP SCHEMA IF EXISTS ML CASCADE;
DROP SCHEMA IF EXISTS RETAIL CASCADE;
DROP SCHEMA IF EXISTS MONGODB_VS CASCADE;
DROP CONNECTION IF EXISTS MONGODB_RETAIL;
DROP CONNECTION IF EXISTS MONGODB_SUPERSTORE;" >/dev/null && ok "schemas and connections dropped"

say "BucketFS"
bucketfs_rm ml rust \
  && ok "adapter .so and model removed"

say "MongoDB"
docker rm -f "$MONGO_CONTAINER" >/dev/null 2>&1 && ok "container removed (data gone with it)" \
  || warn "container was not running"

say "Local build artifacts"
rm -f "$KIT_ROOT/ml/loss_model.pkl" "$KIT_ROOT/ml/loss_model.meta.json" \
      "$KIT_ROOT/ml/superstore_train.csv"
rm -rf "$WORK"
docker rmi -f exasol-ml-train >/dev/null 2>&1 || true
ok "model, training data and training image removed"

say "Cloned repositories"
rm -rf "$HOME/exasol-mongodb-vs" "$HOME/language-container-rs" && ok "removed — step 1 re-clones them"

say "The Rust language container"
# NOT `exasol slc remove RUST` -- see unregister_script_language in lib/common.sh
# for why that could never have worked. No database restart is needed: the new
# SCRIPT_LANGUAGES applies to sessions opened after the ALTER SYSTEM.
unregister_script_language RUST
case $? in
  0) ok "RUST unregistered (the .so was already removed from BucketFS above)" ;;
  2) ok "RUST was not registered — nothing to do" ;;
  *) warn "could not unregister RUST — check:"
     warn "  SELECT SYSTEM_VALUE FROM EXA_PARAMETERS WHERE PARAMETER_NAME='SCRIPT_LANGUAGES';" ;;
esac

cat <<'DONE'

Gone. To rebuild from nothing:

    ./00_preflight.sh     # will now report RUST missing and adapter missing
    ./run_all.sh          # ~25 min, rebuilds every layer

DONE
