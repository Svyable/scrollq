#!/bin/bash
# GCE startup script for the frozen PHerc0826 Spiral baseline.
# Hash-pinned in artifacts/2026-10-05-spiral-cloud-plan/cloud_execution_manifest.json;
# see docs/spiral-cloud-execution.md. It mounts the shared data disk, proves the
# scrollq checkout is the exact clean commit carrying the expected manifest
# bytes, verifies the role script against that manifest, then hands over.
set -Eeuo pipefail

MANIFEST_REL=artifacts/2026-10-05-spiral-cloud-plan/cloud_execution_manifest.json
ROOT=/mnt/scroliq
DEV=/dev/disk/by-id/google-scroliq-data
LOG=/var/log/scroliq-bootstrap.log
exec > >(tee -a "$LOG") 2>&1

md() {
  curl -fsS -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}
ROLE=unknown EVIDENCE_URI="" ZONE=""
ROLE=$(md scroliq-role)
COMMIT=$(md scroliq-commit)
MANIFEST_SHA=$(md scroliq-manifest-sha256)
EVIDENCE_URI=$(md scroliq-evidence-uri)
RUN_ID=$(md scroliq-run-id)
ZONE=$(md scroliq-zone)

halt_vm() {
  sync || true
  [ -z "$ZONE" ] || gcloud compute instances delete "$(hostname)" --zone "$ZONE" --quiet \
    --keep-disks=data || poweroff
  poweroff
}

fail() {
  echo "BOOTSTRAP FAILED [$ROLE]: $*"
  printf '{"role":"%s","status":"failed","gate":"bootstrap","detail":"%s","utc":"%s"}\n' \
    "$ROLE" "$*" "$(date -u +%FT%TZ)" > /tmp/STATUS.json
  if [ -n "$EVIDENCE_URI" ]; then
    gcloud storage cp /tmp/STATUS.json "$EVIDENCE_URI/$ROLE/STATUS.json" || true
    gcloud storage cp "$LOG" "$EVIDENCE_URI/$ROLE/bootstrap-failure.log" || true
  fi
  halt_vm
}
trap 'fail "unexpected error at line $LINENO"' ERR

case "$ROLE" in
  stage-env|gpu-gate|stage-data|gpu-run) ;;
  *) fail "unknown role '$ROLE'" ;;
esac
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "scroliq-commit is not a 40-hex commit"
[[ "$MANIFEST_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "scroliq-manifest-sha256 is not a sha256"
[ -b "$DEV" ] || fail "data disk (device-name scroliq-data) is not attached"

mkdir -p "$ROOT"
if ! blkid "$DEV" >/dev/null 2>&1; then
  [ "$ROLE" = stage-env ] || fail "data disk is blank but role $ROLE needs a staged disk"
  mkfs.ext4 -q -m 0 -F -L scroliq-data "$DEV"
fi
mountpoint -q "$ROOT" || mount -o discard,defaults "$DEV" "$ROOT"

SQ=$ROOT/src/scrollq
if [ "$ROLE" = stage-env ]; then
  [ ! -e "$SQ" ] || fail "stage-env requires a fresh data disk; $SQ already exists"
  mkdir -p "$ROOT/src"
  git clone --quiet https://github.com/Svyable/scrollq "$SQ"
  git -C "$SQ" -c advice.detachedHead=false checkout --quiet "$COMMIT"
fi
[ "$(git -C "$SQ" rev-parse HEAD)" = "$COMMIT" ] || fail "scrollq HEAD is not $COMMIT"
[ -z "$(git -C "$SQ" status --porcelain --untracked-files=all)" ] || fail "scrollq checkout is dirty"
[ "$(sha256sum "$SQ/$MANIFEST_REL" | cut -c1-64)" = "$MANIFEST_SHA" ] \
  || fail "manifest bytes at $COMMIT do not match scroliq-manifest-sha256"

SCRIPT_REL=cloud/spiral-gcp/$ROLE.sh
EXPECTED=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["scripts"][sys.argv[2]])' \
  "$SQ/$MANIFEST_REL" "$SCRIPT_REL")
for rel in cloud/spiral-gcp/common.sh "$SCRIPT_REL"; do
  want=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["scripts"][sys.argv[2]])' \
    "$SQ/$MANIFEST_REL" "$rel")
  [ "$(sha256sum "$SQ/$rel" | cut -c1-64)" = "$want" ] || fail "$rel does not match its manifest hash"
done
[ -n "$EXPECTED" ] || fail "manifest does not pin $SCRIPT_REL"

export SCROLIQ_ROLE=$ROLE SCROLIQ_RUN_ID=$RUN_ID SCROLIQ_COMMIT=$COMMIT SCROLIQ_ZONE=$ZONE \
  SCROLIQ_EVIDENCE_URI=$EVIDENCE_URI SCROLIQ_ROOT=$ROOT SCROLIQ_MANIFEST=$SQ/$MANIFEST_REL
trap - ERR
exec bash "$SQ/$SCRIPT_REL"
