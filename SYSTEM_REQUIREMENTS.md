# System requirements

The environment this kit is known to run on, and — more importantly — the one
platform detail that decides whether it runs at all.

Verified on **2026-09-11**. Where a figure is marked *verified*, it was read off
a working machine, not copied from a vendor page.

## Read this first: the Exasol Personal version boundary

**This kit works on Exasol Personal `2.2.0` and fails on deployments migrated to
`2.3.0-rc2` or later.** That is the single largest cause of "it doesn't run", and
it is not something the kit does wrong — the platform moved underneath it.

| | `2.2.0` (supported today) | migrated `2.3.0-rc2`+ |
|---|---|---|
| `deployment.json` → `.connection.sshPort` | present (e.g. `58817`) | **absent** (`null`) |
| SSH identity | `local/node_access.pem` | `local/runtime/vm-ssh-key` |
| SSH target | `127.0.0.1:<sshPort>` | `<vm_ip>:22`, from `local/runtime/vm-runtime.json` |
| BucketFS | `/var/lib/exa/bucketfs` on the VM's own disk (`/dev/vda`), **reachable only over SSH** | `/mnt/host/exa/bucketfs`, a virtiofs share also visible on the Mac |

Check which one you are on before anything else:

```sh
DEPLOY_DIR="$HOME/.exasol/personal/deployments/default"
exasol version
jq -r '.connection.sshPort // "ABSENT -- migrated platform, this kit will fail"' \
  "$DEPLOY_DIR/deployment.json"
```

A `null` or `ABSENT` here means steps 1 and 7 cannot copy anything into BucketFS
and will fail with `Bad port 'null'`. See `BUG_REPORT.md` / the open issue.

Note that the two layouts need **different** strategies, so a fix cannot simply
switch to the new paths: on `2.2.0` BucketFS is on the VM's own disk and there is
no host-side directory to copy into, so SSH is the only route. Anything that
supports both has to detect the layout.

## Verified-good environment

Everything below was read off the machine the kit currently runs on.

### Host

| | Verified value | Notes |
|---|---|---|
| macOS | 26.6.1 (`25G76`) | Apple silicon required |
| Architecture | `arm64` (Mac17,8) | the pinned Rust SLC asset is `aarch64` only |
| CPU | 18 cores | 8 is comfortable |
| RAM | 48 GB | see the VM note below — 16 GB total is the realistic floor |
| Free disk | 751 GB | ~25 GB is enough: VM image, SLCs, Mongo and the data |

### Exasol Personal

| | Verified value |
|---|---|
| `exasol version` | **2.2.0** |
| `deploymentVersion` | **2.2.0** |
| Deployment dir | `~/.exasol/personal/deployments/default` |
| VM allocation | 2 vCPU / 24 GB RAM |
| Status | `database_ready` |

The VM takes 24 GB of the host's RAM on this machine, which is why 48 GB is
comfortable and 16 GB is the practical floor for running the VM, Docker and a
browser at once.

Exasol Personal is licensed for **20 parallel connections**. dash-server opens
roughly three per board and leaves them idle, so six boards park ~18 of the 20
and the next statement fails with SQL state `08004`. `lib/common.sh` has
`free_connections()` for exactly this; step 6 calls it.

### Tooling

| | Verified value | Required |
|---|---|---|
| Docker | 29.7.2 | yes — MongoDB runs in it |
| MongoDB | 8.2.12 (`mongo:8.2`) | yes |
| `jq` | 1.7.1 (apple) | yes — every script parses `deployment.json` |
| `git` | 2.55.0 | yes |
| `bash` | 3.2.57 (macOS stock) | yes, and stock is fine |
| `python3` | 3.14.7 | for `ml/train.py` |
| `exapump` | kit-installed, `starter-kit` profile | yes |
| dash-server | answering on `:5100` | step 6 only |

**`bash` 3.2 is sufficient — do not install bash 4.** All 14 scripts were checked
for bash-4-only syntax (`declare -A`, `mapfile`, `readarray`, `${v^^}`) and use
none, so the stock macOS shell runs them.

`podman` is **not** a host requirement. The database VM runs podman internally;
that is Exasol's business, not yours.

### MongoDB

Use **`mongo:8.2` or newer**. `mongo:8.0` will not boot on a host kernel ≥ 6.19.

## Separate prerequisite: `exasol-recipes`

`06_dashboard.sh` reads `$HOME/exasol-recipes` and expects six boards there —
`retail-finance`, `retail-sales`, `retail-product`, `retail-datascience`,
`retail-inventory`, `retail-delivery` — plus `dryrun.py`, `ship.sh` and
`preflight.py`.

**Nothing in this repo installs it.** It is not cloned, not vendored and not
mentioned in the README. On a machine that does not already have that directory,
step 6 aborts and takes `run_all.sh` with it (`set -euo pipefail`).

It also needs `~/dash-server/.venv/bin/python3`, which is a different interpreter
from the kit's own `~/.exasol-starter-kit/dash-server-venv/bin/python3`. Only one
of the two exists on some installs.

Until that is resolved, treat `exasol-recipes` as an undocumented prerequisite:
step 6 works only where it is already present.

## What is NOT yet verified end-to-end

Stated plainly so nobody reads this file as a green light:

- **The demo has not been run start-to-finish on the verified machine.** `RETAIL`
  does not exist there, and neither the RUST nor the PYTHON3 SLC is installed.
  `00_preflight.sh` passes and the three known blockers are absent — that is not
  the same as a completed run.
- **Nothing here is verified on the migrated `2.3.0-rc2` platform.** The table at
  the top is drawn from a bug report's evidence, not from a machine in hand.
- **Whether UDFs still resolve `/buckets/bfsdefault/...` after the BucketFS move**
  is unconfirmed (`sql/predict_loss.sql:17`, `sql/loss_score_scalar.sql:25`). The
  nano image has no shell, so it could not be checked from inside.

## Quick check

```sh
sw_vers && uname -m
exasol version && exasol status | grep -i status
jq -r '.connection.sshPort // "ABSENT -- migrated, will fail"' \
  "$HOME/.exasol/personal/deployments/default/deployment.json"
docker info >/dev/null 2>&1 && echo "docker ok"
docker exec mongodb-local mongod --version | head -1
ls -d "$HOME/exasol-recipes" 2>/dev/null || echo "exasol-recipes MISSING -- step 6 will fail"
```
