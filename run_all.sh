#!/usr/bin/env bash
# The whole flow, unattended. Use for a rehearsal or a rebuild — during the talk,
# run the numbered scripts one at a time so the audience sees each step land.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
for s in 00_preflight 01_install_vs 02_load_mongodb 02b_load_superstore 03_load_exasol \
         04_create_virtual_schema 05_the_question 06_dashboard 07_ml_udf; do
  "$HERE/$s.sh"
done
printf '\n\033[1;32mALL STEPS DONE — open http://127.0.0.1:5100/\033[0m\n'
