#!/bin/bash
# Shared helpers for the PHerc0826 cloud roles. Sourced, never executed.
# Every role: create-only evidence directory, periodic evidence sync, one
# failure bundle on any error, then self-delete (poweroff fallback). The
# platform max-run DELETE on the VM stays the hard cost guard.
# shellcheck disable=SC2034  # variables are used by the role scripts that source this file
set -Eeuo pipefail

: "${SCROLIQ_ROLE:?}" "${SCROLIQ_ROOT:?}" "${SCROLIQ_MANIFEST:?}" "${SCROLIQ_EVIDENCE_URI:?}" "${SCROLIQ_ZONE:?}"

ROOT=$SCROLIQ_ROOT
SQ=$ROOT/src/scrollq
VILLA=$ROOT/src/villa
ASM=$ROOT/src/assembler
DS=$ROOT/data/ds0826
STATE=$ROOT/state
RECIPE=$SQ/artifacts/2026-10-03-spiral-baseline-target/pherc0826_baseline_recipe.json
VILLA_PY=$ROOT/env/villa/bin/python
CLOUD=$ROOT/env/scrollq/bin/scroliq-spiral-cloud
SQBIN=$ROOT/env/scrollq/bin

export PATH=$ROOT/tools/uv:$PATH
export UV_PYTHON_INSTALL_DIR=$ROOT/tools/python
export UV_CACHE_DIR=$ROOT/uv-cache
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
export WANDB_MODE=disabled WANDB_DIR=$ROOT/wandb

mf() {  # manifest field by dotted path
  python3 - "$SCROLIQ_MANIFEST" "$1" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
for part in sys.argv[2].split("."):
    value = value[part]
print(value if not isinstance(value, (dict, list)) else json.dumps(value))
PY
}

GATE=init
BUNDLE_FILES=()
gate() { GATE=$1; echo "== [$SCROLIQ_ROLE] gate $GATE  $(date -u +%FT%TZ)"; }

init_role() {
  ATTEMPT=$(date -u +%Y%m%dT%H%M%SZ)
  EV=$ROOT/evidence/$SCROLIQ_ROLE/$ATTEMPT
  EV_URI=$SCROLIQ_EVIDENCE_URI/$SCROLIQ_ROLE/$ATTEMPT
  [ ! -e "$EV" ] || { echo "evidence dir exists: $EV"; exit 1; }
  mkdir -p "$EV" "$STATE"
  exec > >(tee -a "$EV/console.log") 2>&1
  export EV EV_URI ATTEMPT
  trap on_fail ERR
  echo "role=$SCROLIQ_ROLE attempt=$ATTEMPT commit=$SCROLIQ_COMMIT run=$SCROLIQ_RUN_ID"
  status running
}

sync_evidence() { gcloud storage rsync --recursive "$EV" "$EV_URI" --quiet >/dev/null 2>&1 || true; }

status() {  # status <running|pass|failed> [detail]
  python3 - "$EV/STATUS.json" "$SCROLIQ_ROLE" "$ATTEMPT" "$1" "$GATE" "${2:-}" "$EV_URI" <<'PY'
import json, sys, datetime
path, role, attempt, status, gate, detail, uri = sys.argv[1:]
json.dump({"role": role, "attempt": attempt, "status": status, "gate": gate, "detail": detail,
           "evidence_uri": uri,
           "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
          open(path, "w"), indent=2, sort_keys=True)
PY
  gcloud storage cp "$EV/STATUS.json" "$SCROLIQ_EVIDENCE_URI/$SCROLIQ_ROLE/STATUS.json" --quiet >/dev/null 2>&1 || true
}

halt_vm() {
  sync_evidence
  sync || true
  gcloud compute instances delete "$(hostname)" --zone "$SCROLIQ_ZONE" --quiet --keep-disks=data || poweroff
  poweroff
}

bundle() {  # bundle <failed-gate> <reason> [files...]
  local gate=$1 reason=$2; shift 2
  local out=$EV/failure-bundle-$gate
  if [ -x "$CLOUD" ]; then
    "$CLOUD" bundle --out-dir "$out" --stage "$SCROLIQ_ROLE" --failed-gate "$gate" \
      --reason "$reason" --include "$EV/console.log" /var/log/scroliq-bootstrap.log "$@" >/dev/null || true
  else  # the tool itself is not installed yet: plain tarball of what exists
    mkdir -p "$out"
    { uname -a; df -B1; free -b; nvidia-smi -q 2>&1 || true; } > "$out/host.txt" 2>&1 || true
    cp "$EV/console.log" /var/log/scroliq-bootstrap.log "$out/" 2>/dev/null || true
    tar -czf "$out.tar.gz" -C "$EV" "$(basename "$out")" || true
  fi
}

on_fail() {
  local rc=$?
  trap - ERR
  echo "FAILED gate=$GATE rc=$rc"
  bundle "$GATE" "exit status $rc" "${BUNDLE_FILES[@]:-}"
  status failed "gate $GATE exited $rc"
  halt_vm
}

floor() {  # floor <manifest floor name>
  gate "disk_floor:$1"
  "$CLOUD" disk-floor --path "$ROOT" --manifest "$SCROLIQ_MANIFEST" --floor "$1" --out "$EV/disk-floor-$1.json" >/dev/null
}

require_state() {  # require_state <role>: an earlier role must have passed on this disk
  gate "require:$1"
  python3 - "$STATE/$1.json" "$SCROLIQ_COMMIT" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc.get("status") == "pass", f"{sys.argv[1]} is not a pass"
assert doc.get("scrollq_commit") == sys.argv[2], "state was produced by a different scrollq commit"
PY
}

write_state() {  # write_state <json-file>: record this role's pass on the disk
  python3 - "$1" "$STATE/$SCROLIQ_ROLE.json" "$SCROLIQ_COMMIT" "$ATTEMPT" "$EV_URI" <<'PY'
import json, sys
extra = json.load(open(sys.argv[1]))
extra.update({"status": "pass", "scrollq_commit": sys.argv[3], "attempt": sys.argv[4], "evidence_uri": sys.argv[5]})
json.dump(extra, open(sys.argv[2], "w"), indent=2, sort_keys=True)
PY
  cp "$STATE/$SCROLIQ_ROLE.json" "$EV/state.json"
}

villa_clean() {
  gate villa_clean
  [ "$(git -C "$VILLA" rev-parse HEAD)" = "$(mf software.villa.commit)" ]
  [ -z "$(git -C "$VILLA" status --porcelain --untracked-files=all)" ]
}

start_sync_loop() {
  local minutes
  minutes=$(mf watchdog.evidence_sync_interval_minutes)
  ( while sleep $((minutes * 60)); do sync_evidence; done ) &
}

arm_watchdog() {  # arm_watchdog <minutes> <marker>: halt unless <marker> exists by then
  local minutes=$1 marker=$2
  systemd-run --unit="scroliq-watchdog-$ATTEMPT" --on-active="${minutes}m" --timer-property=AccuracySec=10s \
    --setenv=SCROLIQ_ROLE="$SCROLIQ_ROLE" --setenv=SCROLIQ_ROOT="$ROOT" \
    --setenv=SCROLIQ_MANIFEST="$SCROLIQ_MANIFEST" --setenv=SCROLIQ_EVIDENCE_URI="$SCROLIQ_EVIDENCE_URI" \
    --setenv=SCROLIQ_ZONE="$SCROLIQ_ZONE" --setenv=SCROLIQ_COMMIT="$SCROLIQ_COMMIT" \
    --setenv=EV="$EV" --setenv=EV_URI="$EV_URI" --setenv=ATTEMPT="$ATTEMPT" \
    /bin/bash -c "[ -e '$marker' ] || { source '$SQ/cloud/spiral-gcp/common.sh'; GATE=watchdog; \
      bundle watchdog 'preparation window of ${minutes} min exceeded before the fit started'; \
      status failed 'watchdog: ${minutes} min preparation window exceeded'; halt_vm; }"
  echo "watchdog armed: ${minutes} min, marker $marker"
}
